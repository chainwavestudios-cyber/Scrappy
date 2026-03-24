"""
Default Accela CapDetail flow for cities without a dedicated detail module.

Chula Vista, Oakland, Anaheim, etc. — expand standard sections; optional
parse_owner_on_application (Contacts) from city CONFIGS.
"""
from bs4 import BeautifulSoup

from accela_name_utils import extract_homeowner_name, parse_system_size
from accela_detail_primitives import (
    accela_table_row_labeled,
    extract_job_value_with_valuation_fallback,
    extract_labeled_multiline,
    extract_work_location_accela,
    get_field_from_soup,
    infer_pds_fields_from_narrative,
    primary_scope_allowed,
    resolve_permit_url_from_href,
    sync_address_zip_for_ingest,
)
from accela_detail_ui import (
    expand_accela_detail_sections,
    resolve_accela_ui_context,
    try_parse_owner_from_contacts_tab,
    wait_accela_detail_dom,
)


async def fetch_permit_detail(detail_page, base_url, module, permit_num, lead, cfg, log):
    resolve_permit_url_from_href(base_url, permit_num, module, lead)
    detail_url = lead['permitUrl']
    log.info(f'  → {detail_url}')

    await detail_page.goto(detail_url, wait_until='domcontentloaded', timeout=20000)
    try:
        await detail_page.wait_for_load_state('networkidle', timeout=15000)
    except Exception:
        pass
    ctx = await wait_accela_detail_dom(detail_page, log)

    await expand_accela_detail_sections(ctx)

    ctx = await resolve_accela_ui_context(detail_page, log)
    html = await ctx.content()
    soup = BeautifulSoup(html, 'lxml')

    if cfg.get('require_primary_scope_contains') and not primary_scope_allowed(soup, cfg):
        lead['_skip_ingest'] = True
        log.info(f'  skip (primary scope): {permit_num}')
        return

    def get_field(label):
        return get_field_from_soup(soup, label)

    lead['jobValue'] = extract_job_value_with_valuation_fallback(soup)

    lp_text = accela_table_row_labeled(soup, 'licensed professional')
    if not lp_text:
        for el in soup.find_all(['span', 'td', 'div', 'th', 'h2', 'h3']):
            if 'licensed professional' in el.get_text(strip=True).lower():
                container = el.find_parent(['div', 'table', 'section', 'fieldset'])
                if container:
                    parts = []
                    for child in container.find_all(['span', 'td', 'div', 'label', 'p']):
                        t = child.get_text(strip=True)
                        if t and t.lower() not in ('licensed professional', ''):
                            parts.append(t)
                    if parts:
                        lp_text = ' | '.join(dict.fromkeys(parts))
                        break

    if not lp_text:
        for el in soup.find_all(['span', 'td', 'div', 'th']):
            if 'licensed professional' in el.get_text().lower():
                parent = el.find_parent(['tr', 'div', 'section', 'table'])
                if parent:
                    nxt = parent.find_next_sibling()
                    if nxt:
                        lp_text = nxt.get_text(separator=' | ', strip=True)
                        break

    lead['licensedProfessional'] = lp_text

    lead['subType'] = get_field('Sub Type')
    lead['occupancyType'] = get_field('What is the occupancy type?')
    _pn = get_field('Number of Panels') or get_field('Number of Modules')
    if (_pn or '').strip():
        lead['numberOfPanels'] = _pn.strip()
        lead['_panels_from_app_info'] = True
    else:
        lead['numberOfPanels'] = ''

    work_loc = extract_work_location_accela(soup)
    if work_loc:
        lead['siteAddress'] = work_loc

    project_desc_clean = (
        accela_table_row_labeled(soup, 'project description')
        or extract_labeled_multiline(soup, 'Project Description')
        or get_field('Project Description')
    )
    if project_desc_clean:
        lead['projectDescription'] = project_desc_clean
        if not (lead.get('description') or '').strip():
            lead['description'] = project_desc_clean

    system_size = (
        get_field('System Size')
        or get_field('DC System Size')
        or get_field('Rounded Kilowatts Total System Size')
        or get_field('kW')
        or ''
    )
    if not system_size:
        system_size = parse_system_size(project_desc_clean or '')
    if not system_size and lead.get('description'):
        system_size = parse_system_size(lead['description'])
    if system_size:
        lead['systemSize'] = system_size

    if project_desc_clean:
        first_line = project_desc_clean.split('\n')[0].strip()
        first, last = extract_homeowner_name(first_line, '')
        if not first:
            first, last = extract_homeowner_name(project_desc_clean, '')
        if first and not lead.get('homeownerFirstName'):
            lead['homeownerFirstName'] = first
            lead['homeownerLastName'] = last

    kwh = get_field('Rounded Kilowatts Total System Size')
    if kwh:
        lead['systemSize'] = kwh + ' kW'
    elec = get_field('Electrical Service Upgrade')
    if elec:
        lead['electricalServiceUpgrade'] = elec
    ess = get_field('Advanced Energy Storage System')
    if ess:
        lead['advancedEnergyStorage'] = ess
    cs = get_field('Cross Street')
    if cs:
        lead['crossStreet'] = cs
    dow = get_field('Description of Work')
    if dow:
        lead['descriptionOfWork'] = dow
    nob = get_field('Number of Buildings')
    if nob:
        lead['numberOfBuildings'] = nob
    hu = get_field('Housing Units')
    if hu:
        lead['housingUnits'] = hu

    if cfg.get('parse_owner_on_application') and not cfg.get('owner_from_contacts'):
        await try_parse_owner_from_contacts_tab(detail_page, lead)

    infer_pds_fields_from_narrative(lead)
    sync_address_zip_for_ingest(lead)

    ji = (lead.get('jobInfo') or '').replace('\n', ' | ')
    log.info(
        f'  jobValue={lead.get("jobValue","?")} | jobInfo={ji[:100] or "—"} | '
        f'size={lead.get("systemSize","?")} | '
        f'elec={lead.get("electricalServiceUpgrade","?")} | ess={lead.get("advancedEnergyStorage","?")} | '
        f'owner={lead.get("homeownerFirstName","")} {lead.get("homeownerLastName","")}'
    )
