"""
San Diego County PDS — permit detail page flow and field extraction.

Isolated from other cities so changes here do not affect Oakland, Chula Vista, etc.
"""
import re

from bs4 import BeautifulSoup

from accela_detail_primitives import (
    accela_field_first_nonempty,
    accela_table_row_labeled,
    accela_td_value_after_label_contains,
    build_job_info_text,
    extract_job_value_accela,
    extract_job_value_with_valuation_fallback,
    extract_labeled_multiline,
    extract_work_location_accela,
    get_field_from_soup,
    infer_pds_fields_from_narrative,
    parse_owner_contacts_soup,
    primary_scope_allowed,
    resolve_permit_url_from_href,
    sync_address_zip_for_ingest,
)
from accela_detail_ui import (
    click_more_details_visible,
    pds_expand_application_information_heading,
    pds_expand_contacts_heading,
    pds_expand_record_more_details,
    resolve_cap_detail_content_frame,
    wait_accela_detail_dom,
)


async def fetch_permit_detail(detail_page, base_url, module, permit_num, lead, cfg, log):
    """
    San Diego residential/commercial PDS detail scrape.
    cfg: merged city CONFIGS for this scrape.
    """
    resolve_permit_url_from_href(base_url, permit_num, module, lead)
    detail_url = lead['permitUrl']
    log.info(f'  → {detail_url}')

    await detail_page.goto(detail_url, wait_until='domcontentloaded', timeout=20000)
    try:
        await detail_page.wait_for_load_state('networkidle', timeout=18000)
    except Exception:
        pass
    ctx = await wait_accela_detail_dom(detail_page, log)

    await pds_expand_record_more_details(ctx)
    ctx = await wait_accela_detail_dom(detail_page, log=None)

    ctx = await resolve_cap_detail_content_frame(detail_page, log)
    html = await ctx.content()
    soup = BeautifulSoup(html, 'lxml')

    if cfg.get('require_primary_scope_contains') and not primary_scope_allowed(soup, cfg):
        lead['_skip_ingest'] = True
        log.info(f'  skip (primary scope): {permit_num}')
        return

    def get_field(label):
        return get_field_from_soup(soup, label)

    job_value = extract_job_value_with_valuation_fallback(soup)
    lead['jobValue'] = job_value

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
    if work_loc and not (lead.get('siteAddress') or lead.get('address') or '').strip():
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

    await pds_expand_contacts_heading(ctx)
    await click_more_details_visible(ctx)
    ctx = await wait_accela_detail_dom(detail_page, log=None)
    ctx = await resolve_cap_detail_content_frame(detail_page, log)
    html2 = await ctx.content()
    soup2 = BeautifulSoup(html2, 'lxml')
    parse_owner_contacts_soup(soup2, lead)

    await pds_expand_application_information_heading(ctx)
    ctx = await wait_accela_detail_dom(detail_page, log=None)
    ctx = await resolve_cap_detail_content_frame(detail_page, log)
    html_app = await ctx.content()
    soup_app = BeautifulSoup(html_app, 'lxml')

    jv_app = extract_job_value_accela(soup_app)
    if (jv_app or '').strip():
        lead['jobValue'] = jv_app

    if not (lead.get('licensedProfessional') or '').strip():
        lpa = accela_table_row_labeled(soup_app, 'licensed professional')
        if lpa:
            lead['licensedProfessional'] = lpa

    if not (lead.get('projectDescription') or '').strip():
        pd2 = (
            accela_table_row_labeled(soup_app, 'project description')
            or extract_labeled_multiline(soup_app, 'Project Description')
            or get_field_from_soup(soup_app, 'Project Description')
        )
        if pd2:
            lead['projectDescription'] = pd2
            if not (lead.get('description') or '').strip():
                lead['description'] = pd2

    kwh = accela_field_first_nonempty(
        soup_app,
        'Rounded Kilowatts Total',
        'Rounded Kilowatts Total System Size',
        'DC System Size',
        'System Size',
        'Total System Size in Kilowatts',
    )
    if not (kwh or '').strip():
        kwh = (
            accela_td_value_after_label_contains(soup_app, 'rounded kilowatt')
            or accela_td_value_after_label_contains(soup_app, 'kilowatt total')
            or accela_td_value_after_label_contains(soup_app, 'dc system size')
        )

    elec = accela_field_first_nonempty(
        soup_app,
        'Electrical Service Upgrade',
        'Electrical Upgrade',
        'Service Upgrade',
    )
    if not (elec or '').strip():
        elec = (
            accela_td_value_after_label_contains(soup_app, 'electrical service upgrade')
            or accela_td_value_after_label_contains(soup_app, 'meter upgrade')
            or accela_td_value_after_label_contains(soup_app, 'service upgrade')
        )

    ess = accela_field_first_nonempty(
        soup_app,
        'Advanced Energy Storage System',
        'Advanced Energy Storage',
        'Energy Storage System',
        'Battery Energy Storage',
    )
    if not (ess or '').strip():
        ess = (
            accela_td_value_after_label_contains(soup_app, 'advanced energy storage')
            or accela_td_value_after_label_contains(soup_app, 'energy storage system')
        )
    if not (elec or '').strip():
        narr = f"{lead.get('projectDescription') or ''}\n{lead.get('description') or ''}"
        if re.search(r'\(?\s*no\s+meter\s+upgrade\s*\)?', narr, re.I):
            elec = 'No'
    if elec:
        lead['electricalServiceUpgrade'] = elec
    if ess:
        lead['advancedEnergyStorage'] = ess
    jt = build_job_info_text(kwh, elec, ess)
    if jt:
        lead['jobInfo'] = jt
    if kwh:
        lead['systemSize'] = kwh + (' kW' if 'kw' not in kwh.lower() else '')

    cs = get_field_from_soup(soup_app, 'Cross Street')
    if cs:
        lead['crossStreet'] = cs
    dow = get_field_from_soup(soup_app, 'Description of Work')
    if dow:
        lead['descriptionOfWork'] = dow
    nob = get_field_from_soup(soup_app, 'Number of Buildings')
    if nob:
        lead['numberOfBuildings'] = nob
    hu = get_field_from_soup(soup_app, 'Housing Units')
    if hu:
        lead['housingUnits'] = hu
    pan = (
        get_field_from_soup(soup_app, 'Number of Panels')
        or get_field_from_soup(soup_app, 'Number of Modules')
    )
    if (pan or '').strip():
        lead['numberOfPanels'] = pan.strip()
        lead['_panels_from_app_info'] = True

    infer_pds_fields_from_narrative(lead)
    sync_address_zip_for_ingest(lead)

    ji = (lead.get('jobInfo') or '').replace('\n', ' | ')
    desc_prev = ((lead.get('description') or '')[:100] + '…') if len(lead.get('description') or '') > 100 else (lead.get('description') or '')
    log.info(
        f'  jobValue={lead.get("jobValue","?")} | jobInfo={ji[:100] or "—"} | '
        f'size={lead.get("systemSize","?")} | '
        f'elec={lead.get("electricalServiceUpgrade","?")} | ess={lead.get("advancedEnergyStorage","?")} | '
        f'owner={lead.get("homeownerFirstName","")} {lead.get("homeownerLastName","")} | '
        f'desc={desc_prev or "—"}'
    )
