"""
Generic Accela scraper — works for any standard Accela portal.
Each city passes its own config dict.
"""
import asyncio
import re


# Words that are NOT names even if capitalized
_NOT_NAME_WORDS = {
    'install', 'new', 'roof', 'solar', 'remove', 'energy', 'pv', 'photovoltaic',
    'this', 'residential', 'commercial', 'battery', 'upgrade', 'addition',
    'replacement', 'ess', 'lift', 'uninstall', 'reinstall', 'removal', 'level',
    'existing', 'mount', 'mounted', 'system', 'panel', 'panels', 'module',
    'modules', 'inverter', 'storage', 'electric', 'electrical', 'circuit',
    'charger', 'garage', 'tesla', 'powerwall', 'expansion', 'backup', 'back',
    'main', 'service', 'permit', 'building', 'construction', 'project',
    'unit', 'phase', 'model', 'sunrun', 'sunpower', 'vivint', 'sunnova',
    'otc', 'ac', 'dc', 'mpu', 'buss', 'breaker', 'reroof', 'installation',
    'correction', 'corrections', 'review', 'applied', 'issued', 'finaled',
    'repair', 'replace', 'replacement', 'dedicated', 'existing',
    'st', 'ave', 'av', 'blvd', 'dr', 'ln', 'rd', 'ct', 'pl', 'way', 'ter',
    'cir', 'loop', 'pkwy', 'hwy', 'fwy', 'expy', 'north', 'south', 'east', 'west',
}


def _looks_like_name_word(word):
    if not word or len(word) < 2:
        return False
    if word.lower() in _NOT_NAME_WORDS:
        return False
    if not word[0].isupper():
        return False
    if any(c.isdigit() for c in word):
        return False
    if re.match(r'^[A-Z]{2,}$', word) and len(word) > 3:
        return False
    return True


def extract_homeowner_name(description='', project_name=''):
    if project_name and project_name.strip():
        pn = project_name.strip()
        m = re.match(r'^([A-Z][a-zA-Z\'-]+),\s*([A-Z][a-zA-Z\'-]+)', pn)
        if m:
            last, first = m.group(1), m.group(2)
            if _looks_like_name_word(first) and _looks_like_name_word(last):
                return first, last
        words = re.split(r'[\s_]+', pn)
        name_words = [w for w in words[:3] if _looks_like_name_word(w)]
        non_name = [w for w in words[:len(name_words)+1]
                    if not _looks_like_name_word(w) and w not in (',', '-', '_')]
        if len(name_words) >= 2 and len(non_name) == 0:
            return name_words[0], ' '.join(name_words[1:])
        if len(words) >= 3 and not _looks_like_name_word(words[0]):
            rest = [w for w in words[1:3] if _looks_like_name_word(w)]
            if len(rest) >= 2:
                return rest[0], ' '.join(rest[1:])

    if description and description.strip():
        desc = description.strip()
        words = desc.split()
        if not words or not _looks_like_name_word(words[0]):
            return '', ''
        name_words = []
        for word in words:
            clean = re.sub(r'[^a-zA-Z\-\' ]', '', word).strip()
            if _looks_like_name_word(clean):
                name_words.append(clean)
            else:
                break
            if len(name_words) == 3:
                break
        if len(name_words) >= 2:
            return name_words[0], ' '.join(name_words[1:])

    return '', ''


def parse_system_size(text):
    """Extract system size (kW/kWh) from any text string."""
    if not text:
        return ''
    # Match patterns like 7.425kwp, 8.8kw, 4.92KW, 10kwh, 13.2 kW
    m = re.search(r'(\d+\.?\d*)\s*(kwp|kwh|kw|kip)', text, re.IGNORECASE)
    if m:
        val = m.group(1)
        unit = m.group(2).lower()
        if unit == 'kwp':
            unit = 'kW'
        elif unit == 'kwh':
            unit = 'kWh'
        elif unit == 'kip':
            unit = 'kW'
        else:
            unit = 'kW'
        return f'{val} {unit}'
    return ''


import logging
import os
from playwright.async_api import async_playwright
from bs4 import BeautifulSoup

logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# City configs — loaded from cities/ folder (one file per city)
# Add new cities by creating cities/<name>.py with CONFIGS dict.
# ---------------------------------------------------------------------------
from cities import get_city_configs

CITY_CONFIGS = get_city_configs()


# ---------------------------------------------------------------------------
# PDS / iframe portals (e.g. San Diego Default.aspx)
# ---------------------------------------------------------------------------

async def _try_click_pds_entry(surface, labels: list, city_name: str) -> bool:
    """
    Click county portal entry (e.g. San Diego 'PDS' tile).

    Often a <div> with visible text, role=generic, no accessible name — not a link.
    Order: exact text → div with exact text → link role (other sites).
    """
    for raw in labels:
        rw = (raw or '').strip()
        if not rw:
            continue
        # 1) Exact visible text (matches div/button with "PDS")
        try:
            tloc = surface.get_by_text(rw, exact=True)
            if await tloc.count() > 0:
                await tloc.first.click(timeout=20000)
                log.info(f'[{city_name}] Clicked portal entry (get_by_text exact={rw!r})')
                return True
        except Exception as e:
            log.debug(f'[{city_name}] PDS get_by_text {rw!r}: {e}')
        # 2) Small tile divs (e.g. navy box ~27×25px)
        try:
            pat = re.compile(r'^' + re.escape(rw) + r'$', re.I)
            dloc = surface.locator('div', has_text=pat)
            if await dloc.count() > 0:
                await dloc.first.click(timeout=20000)
                log.info(f'[{city_name}] Clicked portal entry (div + text {rw!r})')
                return True
        except Exception as e:
            log.debug(f'[{city_name}] PDS div {rw!r}: {e}')
        # 3) Real <a> on other counties
        try:
            loc = surface.get_by_role('link', name=re.compile(rw, re.I))
            if await loc.count() > 0:
                await loc.first.click(timeout=20000)
                log.info(f'[{city_name}] Clicked portal entry (link {rw!r})')
                return True
        except Exception as e:
            log.debug(f'[{city_name}] PDS link {rw!r}: {e}')
    return False


async def _surface_has_visible_search_form(surface) -> bool:
    try:
        loc = surface.locator('[id*="txtGSStartDate"]')
        if await loc.count() == 0:
            return False
        return await loc.first.is_visible()
    except Exception:
        return False


async def _resolve_accela_search_surface(page, config: dict, city_name: str):
    """
    County PDS sites often wrap Citizen Access in an iframe and require a
    'PDS' (or similar) link first. Returns Page or Frame where the Accela
    general search form lives.
    """
    if not config.get('portal_pds_iframe'):
        return page

    labels = list(config.get('pds_entry_link_names', ['PDS']))

    async def _wait_portal_idle():
        try:
            await page.wait_for_load_state('networkidle', timeout=90000)
        except Exception:
            pass
        await page.wait_for_timeout(2500)

    # 1) Entry control on main page (often a div "PDS", not a link)
    if await _try_click_pds_entry(page, labels, city_name):
        await _wait_portal_idle()

    if await _surface_has_visible_search_form(page):
        log.info(f'[{city_name}] Accela search form on main document')
        return page

    # 2) Form already inside a child iframe
    for fr in page.frames:
        if fr == page.main_frame:
            continue
        if await _surface_has_visible_search_form(fr):
            log.info(f'[{city_name}] Accela search form in iframe (no main PDS click): {fr.url[:90]}...')
            return fr

    # 3) PDS tile only inside iframe → click then re-scan
    for fr in page.frames:
        if fr == page.main_frame:
            continue
        if await _try_click_pds_entry(fr, labels, city_name):
            await _wait_portal_idle()
            break

    if await _surface_has_visible_search_form(page):
        log.info(f'[{city_name}] Accela search form on main (after in-iframe PDS)')
        return page

    for fr in page.frames:
        if fr == page.main_frame:
            continue
        if await _surface_has_visible_search_form(fr):
            log.info(f'[{city_name}] Accela search form in iframe after PDS: {fr.url[:90]}...')
            return fr

    log.warning(
        f'[{city_name}] portal_pds_iframe set but Accela form not found; '
        f'continuing on main page (may fail).'
    )
    return page


# ---------------------------------------------------------------------------
# Generic Accela scraper
# ---------------------------------------------------------------------------

async def scrape_accela_async(config: dict, start_date: str, end_date: str):
    base_url  = config['base_url']
    module    = config['module']
    city_name = config['name']
    source    = config['source']

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            viewport={'width': 1280, 'height': 800},
            accept_downloads=True,
        )
        page = await context.new_page()

        try:
            # Use portal_url override if set (e.g. San Diego uses Default.aspx entry)
            if config.get('portal_url'):
                search_url = config['portal_url']
            else:
                search_url = (
                    f'{base_url}/Cap/CapHome.aspx?module={module}'
                    f'&TabName={module}&TabList=HOME%7C0%7C{module}%7C1%7CCurrentTabIndex%7C1'
                )
            log.info(f'[{city_name}] Loading search form directly: {search_url}')
            await page.goto(search_url, wait_until='networkidle')
            await page.wait_for_timeout(3000)

            search = await _resolve_accela_search_surface(page, config, city_name)

            log.info(f'[{city_name}] Waiting for search form...')
            try:
                await search.wait_for_selector('[id*="txtGSStartDate"]', timeout=20000, state='visible')
                log.info(f'[{city_name}] Search form loaded')
            except Exception:
                log.warning(f'[{city_name}] Direct URL failed, trying menu navigation...')
                # Menu links may be on main page while form is in iframe — try both
                _seen = set()
                _targets = []
                for t in (page, search):
                    tid = id(t)
                    if tid not in _seen:
                        _seen.add(tid)
                        _targets.append(t)
                for target in _targets:
                    for label in ['Search Applications', 'Search Records', 'Building Records', 'Search Permits']:
                        try:
                            loc = target.get_by_role('link', name=label)
                            if await loc.count() > 0:
                                await loc.first.click()
                                await page.wait_for_load_state('networkidle')
                                await page.wait_for_timeout(2000)
                                log.info(f'[{city_name}] Clicked: {label}')
                                break
                        except Exception:
                            continue
                search = await _resolve_accela_search_surface(page, config, city_name)
                await search.wait_for_selector('[id*="txtGSStartDate"]', timeout=20000, state='visible')

            # Select permit type FIRST
            if config.get('permit_type'):
                log.info(f'[{city_name}] Selecting permit type: {config["permit_type"]}')
                try:
                    type_sel = await search.evaluate("""
                        () => {
                            const candidates = [
                                'select[id*="ddlGSPermitType"]',
                                'select[id*="selGSPermitType"]',
                                'select[id*="ddlSearchType"]',
                                'select[id*="PermitType"]',
                            ];
                            for (const sel of candidates) {
                                const el = document.querySelector(sel);
                                if (el) return '#' + el.id;
                            }
                            const selects = Array.from(document.querySelectorAll('select'));
                            const visible = selects.find(s => s.offsetParent !== null);
                            return visible ? '#' + visible.id : null;
                        }
                    """)
                    if type_sel:
                        await search.wait_for_selector(type_sel, timeout=15000)
                        options = await search.evaluate(f"""
                            () => Array.from(
                                document.querySelector('{type_sel}').options
                            ).map(o => o.text)
                        """)
                        log.info(f'[{city_name}] Permit type options: {options}')
                        await search.evaluate(f"""
                            () => {{
                                const sel = document.querySelector('{type_sel}');
                                const opt = Array.from(sel.options).find(
                                    o => o.text.trim() === '{config["permit_type"]}'
                                );
                                if (opt) {{
                                    sel.value = opt.value;
                                    sel.dispatchEvent(new Event('change'));
                                }}
                            }}
                        """)
                        await page.wait_for_load_state('networkidle')
                        await page.wait_for_timeout(2000)
                        log.info(f'[{city_name}] Permit type selected')
                except Exception as e:
                    log.warning(f'[{city_name}] Could not select permit type: {e}')

            # Inject dates AFTER permit type postback
            log.info(f'[{city_name}] Injecting dates: {start_date} to {end_date}')
            await search.evaluate(f"""
                () => {{
                    const sVis = document.querySelector('#ctl00_PlaceHolderMain_generalSearchForm_txtGSStartDate');
                    const eVis = document.querySelector('#ctl00_PlaceHolderMain_generalSearchForm_txtGSEndDate');
                    if (sVis) sVis.value = '{start_date}';
                    if (eVis) eVis.value = '{end_date}';

                    const sState = document.querySelector('#ctl00_PlaceHolderMain_generalSearchForm_txtGSStartDate_ext_ClientState');
                    const eState = document.querySelector('#ctl00_PlaceHolderMain_generalSearchForm_txtGSEndDate_ext_ClientState');
                    if (sState) sState.value = JSON.stringify({{selectedDate: '{start_date}', minDateStr: '', maxDateStr: ''}});
                    if (eState) eState.value = JSON.stringify({{selectedDate: '{end_date}', minDateStr: '', maxDateStr: ''}});

                    if (sVis) {{ sVis.dispatchEvent(new Event('change')); sVis.dispatchEvent(new Event('blur')); }}
                    if (eVis) {{ eVis.dispatchEvent(new Event('change')); eVis.dispatchEvent(new Event('blur')); }}
                }}
            """)
            await search.wait_for_timeout(500)

            dates_check = await search.evaluate("""
                () => ({
                    visStart: document.querySelector('#ctl00_PlaceHolderMain_generalSearchForm_txtGSStartDate')?.value,
                    visEnd:   document.querySelector('#ctl00_PlaceHolderMain_generalSearchForm_txtGSEndDate')?.value,
                    hidStart: document.querySelector('#ctl00_PlaceHolderMain_generalSearchForm_txtGSStartDate_ext_ClientState')?.value,
                    hidEnd:   document.querySelector('#ctl00_PlaceHolderMain_generalSearchForm_txtGSEndDate_ext_ClientState')?.value,
                })
            """)
            log.info(f'[{city_name}] Dates verified: {dates_check}')

            if config.get('use_project_name'):
                try:
                    await search.fill('[id*="txtGSProjectName"]', config['use_project_name'])
                except Exception:
                    pass

            # Click Search
            log.info(f'[{city_name}] Clicking Search...')
            await search.evaluate('() => window.scrollTo(0, document.body.scrollHeight)')
            await search.wait_for_timeout(500)

            clicked = False
            for btn_sel in [
                '#ctl00_PlaceHolderMain_btnNewSearch',
                'a[id*="btnNewSearch"]',
                'a[id*="btnSearch"]',
                'input[id*="btnSearch"]',
                'button[id*="btnSearch"]',
                'a[id*="btnGS"]',
                'input[value="Search"]',
            ]:
                try:
                    loc = search.locator(btn_sel)
                    if await loc.count() > 0:
                        await loc.first.click()
                        clicked = True
                        log.info(f'[{city_name}] Clicked: {btn_sel}')
                        break
                except Exception:
                    continue
            if not clicked:
                raise Exception('Could not find search button')

            await search.wait_for_selector(
                'tr.ACA_TabRow_Odd, tr.ACA_TabRow_Even, tr.gdvPermitList_Row',
                timeout=60000
            )
            log.info(f'[{city_name}] Results loaded')

            log.info(f'[{city_name}] Scraping filtered results...')
            leads = await _scrape_rows(search, source, base_url, module, config)
            log.info(f'[{city_name}] Found {len(leads)} permits in date range')

            for i, lead in enumerate(leads):
                permit_num = lead.get('permitNumber')
                if not permit_num:
                    continue
                log.info(f'[{city_name}] Details {permit_num} ({i+1}/{len(leads)})...')
                detail_context = await browser.new_context(
                    viewport={'width': 1280, 'height': 800},
                )
                detail_page = await detail_context.new_page()
                try:
                    await _get_permit_details(detail_page, base_url, module, permit_num, lead)
                except Exception as e:
                    log.error(f'[{city_name}] Detail failed {permit_num}: {e}')
                    _set_defaults(lead)
                finally:
                    await detail_page.close()
                    await detail_context.close()

            # Strip internal flags before returning
            for lead in leads:
                lead.pop("_owner_from_contacts", None)
                lead.pop("detailHref", None)
            return leads

        finally:
            await context.close()
            await browser.close()


async def _scrape_rows(page, source, base_url, module, config=None):
    leads = []
    page_num = 1

    while True:
        html = await page.content()
        soup = BeautifulSoup(html, 'lxml')
        rows = soup.select('tr.ACA_TabRow_Odd, tr.ACA_TabRow_Even, tr.gdvPermitList_Row')
        log.info(f'  Scraping page {page_num}: {len(rows)} rows')

        for row_idx, row in enumerate(rows):
            cells = row.find_all('td')
            if len(cells) < 3:
                continue

            if page_num == 1 and row_idx == 0:
                log.info(f'  Column sample: {[c.get_text(strip=True)[:40] for c in cells]}')

            raw_cells = [c.get_text(strip=True) for c in cells]

            cfg = config or {}
            col_date         = cfg.get('col_date',         1)
            col_permit_type  = cfg.get('col_permit_type',  3)
            col_description  = cfg.get('col_description',  4)
            col_project_name = cfg.get('col_project_name', 5)
            col_status       = cfg.get('col_status',       6)
            col_address      = cfg.get('col_address',      9)

            link = row.find('a')
            href = link['href'] if link else None
            link_text = link.get_text(strip=True) if link else ''

            col_permit_num = cfg.get('col_permit_num', None)
            if col_permit_num is not None:
                permit_num = raw_cells[col_permit_num] if len(raw_cells) > col_permit_num else ''
            else:
                permit_num = link_text if link_text else (raw_cells[2] if len(raw_cells) > 2 else '')

            description = raw_cells[col_description] if len(raw_cells) > col_description else ''
            desc_lower = description.lower()

            # San Diego commercial: filter by short notes containing config value (e.g. "8004")
            short_notes_filter = cfg.get('short_notes_filter', None)
            if short_notes_filter:
                col_sn = cfg.get('col_short_notes', 8)
                short_notes = raw_cells[col_sn] if len(raw_cells) > col_sn else ''
                if short_notes_filter.lower() not in short_notes.lower():
                    log.info(f'  Skipping (no {short_notes_filter} in notes): {short_notes[:60]}')
                    continue
            else:
                INCLUDE_KEYWORDS = [
                    'solar', 'pv', 'photovoltaic', 'panel', 'module', 'kw', 'kwp',
                    'energy storage', 'powerwall', 'battery', 'ess',
                ]
                EXCLUDE_PATTERNS = [
                    'ev charger', 'ev charge', 'level ii ev', 'level 2 ev',
                    'uninstall and reinstall', 'reinstall existing', 'reinstall of existing',
                    'lift and reinstall', 'uninstallation and reinstallation',
                    'removal and reinstall', 'removal & re-install', 'removal & reinstall',
                    'remove & re-install', 'remove and reinstall',
                    'removal and reinstallation',
                ]
                has_solar_or_battery = any(kw in desc_lower for kw in INCLUDE_KEYWORDS)
                is_excluded = any(kw in desc_lower for kw in EXCLUDE_PATTERNS)
                if not (has_solar_or_battery and not is_excluded):
                    log.info(f'  Skipping (not new install): {description[:60]}')
                    continue

            status = raw_cells[col_status] if col_status is not None and len(raw_cells) > col_status else ''
            permit_date_str = raw_cells[col_date] if len(raw_cells) > col_date else ''

            issued_filter_days = cfg.get('issued_filter_days', 7)
            if status.lower() == 'issued' and permit_date_str:
                try:
                    from datetime import datetime
                    permit_date = datetime.strptime(permit_date_str, '%m/%d/%Y')
                    days_old = (datetime.now() - permit_date).days
                    if days_old > issued_filter_days:
                        log.info(f'  Skipping (issued {days_old}d ago): {description[:50]}')
                        continue
                except Exception:
                    pass

            project_name = raw_cells[col_project_name] if col_project_name is not None and len(raw_cells) > col_project_name else ''

            raw_address = raw_cells[col_address] if len(raw_cells) > col_address else ''
            address = re.sub(r',?\s*\d+\s*\d*\s*$', '', raw_address).strip().rstrip(',').strip()

            zip_match = re.search(r'\b(\d{5})(?:-\d{4})?\b', address)
            zip_code = zip_match.group(1) if zip_match else ''

            owner_first, owner_last = extract_homeowner_name(description, project_name)

            # Try to parse system size from description immediately
            system_size = parse_system_size(description)

            lead_category = cfg.get('lead_category', 'residential')
            leads.append({
                'homeownerFirstName':   owner_first,
                'homeownerLastName':    owner_last,
                'permitNumber':         permit_num,
                'permitUrl':            f'{base_url}/Cap/CapDetail.aspx?altId={permit_num}&module={module}' if permit_num else '',
                'date':                 permit_date_str,
                'siteAddress':          address,
                'zipCode':              zip_code,
                'city':                 cfg.get('name', ''),
                'description':          description,
                'systemSize':           system_size,
                'numberOfPanels':       '',
                'jobValue':             '',
                'status':               status,
                'subType':              '',
                'occupancyType':        '',
                'licensedProfessional': '',
                'projectName':          project_name,
                'permitType':           raw_cells[col_permit_type] if len(raw_cells) > col_permit_type else '',
                'leadCategory':         lead_category,
                'source':               source,
                'enrichmentStage':      'scraped',
                'uniqueId':             f'{cfg.get("source", source)}_{permit_num}',
                # Internal flags — stripped before output
                'detailHref':           href,
                '_owner_from_contacts':  cfg.get('owner_from_contacts', False),
            })

        next_link = soup.find('a', string=str(page_num + 1))
        if not next_link:
            log.info(f'  No page {page_num + 1} link found — done paginating')
            break

        if page_num > 1:
            current_nums = set(l['permitNumber'] for l in leads[-len(rows):] if l.get('permitNumber'))
            prev_nums = set(l['permitNumber'] for l in leads[:-len(rows)] if l.get('permitNumber'))
            if len(current_nums & prev_nums) > 8:
                log.warning(f'  Detected page loop — stopping pagination')
                break

        await page.click(f'a:text("{page_num + 1}")')
        await page.wait_for_selector(
            'tr.ACA_TabRow_Odd, tr.ACA_TabRow_Even, tr.gdvPermitList_Row',
            timeout=30000
        )
        page_num += 1

    seen = set()
    unique_leads = []
    for lead in leads:
        pn = lead.get('permitNumber', '')
        if pn and pn not in seen:
            seen.add(pn)
            unique_leads.append(lead)
        elif not pn:
            unique_leads.append(lead)

    log.info(f'  After dedup: {len(unique_leads)} unique permits (was {len(leads)})')
    return unique_leads


def _get_field_from_soup(soup, label):
    """Label/value pairs on Accela detail HTML (table or sibling layout)."""
    lbl = label.lower().rstrip(':')
    for el in soup.find_all(['span', 'td', 'div', 'label', 'th']):
        if el.get_text(strip=True).lower().rstrip(':') == lbl:
            nxt = el.find_next_sibling()
            if nxt and nxt.get_text(strip=True):
                return nxt.get_text(strip=True)
            parent = el.find_parent()
            if parent:
                nxt2 = parent.find_next_sibling()
                if nxt2 and nxt2.get_text(strip=True):
                    return nxt2.get_text(separator=' ', strip=True)
    return ''


async def _expand_accela_detail_sections(detail_page):
    """Expand More Details → Additional Information → Application Information."""
    await detail_page.evaluate("""
        () => {
            const links = Array.from(document.querySelectorAll('a'));
            const more = links.find(l => l.textContent.includes('More Details'));
            if (more) more.click();
        }
    """)
    await detail_page.wait_for_timeout(1500)
    await detail_page.evaluate("""
        () => {
            const els = Array.from(document.querySelectorAll('a, span'));
            const ai = els.find(l => l.textContent.trim() === 'Additional Information');
            if (ai) ai.click();
        }
    """)
    await detail_page.wait_for_timeout(1500)
    await detail_page.evaluate("""
        () => {
            const els = Array.from(document.querySelectorAll('a, span'));
            const ai = els.find(l => l.textContent.trim() === 'Application Information');
            if (ai) ai.click();
        }
    """)
    await detail_page.wait_for_timeout(1500)


async def _click_record_details_tab(detail_page):
    """Return from Contacts (etc.) to the main record / cap detail view."""
    await detail_page.evaluate("""
        () => {
            const links = Array.from(document.querySelectorAll('a, span'));
            const labels = ['Record Details', 'Record Information', 'Record Info'];
            for (const text of labels) {
                const el = links.find(l => l.textContent.trim() === text);
                if (el) { el.click(); return true; }
            }
            return false;
        }
    """)
    await detail_page.wait_for_timeout(2000)


async def _get_permit_details(detail_page, base_url, module, permit_num, lead):
    detail_url = f"{base_url}/Cap/CapDetail.aspx?altId={permit_num}&module={module}"
    lead['permitUrl'] = detail_url
    log.info(f'  → {detail_url}')

    # domcontentloaded is faster and more reliable than networkidle — avoids timeouts
    await detail_page.goto(detail_url, wait_until='domcontentloaded', timeout=20000)
    await detail_page.wait_for_timeout(2000)

    await _expand_accela_detail_sections(detail_page)

    html = await detail_page.content()
    soup = BeautifulSoup(html, 'lxml')

    def get_field(label):
        return _get_field_from_soup(soup, label)

    # ---------------------------------------------------------------------------
    # Job Value — Valuation field under Application Information
    # ---------------------------------------------------------------------------
    job_value = ''
    for el in soup.find_all(string=lambda t: t and 'valuation' in t.lower()):
        parent = el.parent
        if not parent:
            continue
        for sibling in parent.next_siblings:
            text = sibling.get_text(strip=True) if hasattr(sibling, 'get_text') else str(sibling).strip()
            if text and text.replace(',', '').replace('.', '').replace('$', '').strip().isdigit():
                job_value = text
                break
            elif text and text not in ('', 'Valuation:', 'Valuation'):
                job_value = text
                break
        if job_value:
            break

    if not job_value:
        for el in soup.find_all(['span', 'td', 'div', 'label', 'th']):
            text = el.get_text(strip=True).lower().rstrip(':')
            if text == 'valuation':
                nxt = el.find_next_sibling()
                if nxt:
                    val = nxt.get_text(strip=True)
                    if val and val.lower() not in ('valuation', ''):
                        job_value = val
                        break
                parent = el.find_parent()
                if parent:
                    nxt2 = parent.find_next_sibling()
                    if nxt2:
                        val2 = nxt2.get_text(separator=' ', strip=True)
                        if val2 and val2.lower() not in ('valuation', ''):
                            job_value = val2
                            break

    JS_INDICATORS = ['function', 'CDATA', 'document.', 'var ', 'ACADialog']
    if any(ind in str(job_value) for ind in JS_INDICATORS):
        job_value = ''
    lead['jobValue'] = job_value

    # ---------------------------------------------------------------------------
    # Licensed Professional — grab the entire section block
    # Full block includes: company name, address, phone, license number
    # ---------------------------------------------------------------------------
    lp_text = ''
    for el in soup.find_all(['span', 'td', 'div', 'th', 'h2', 'h3']):
        if 'licensed professional' in el.get_text(strip=True).lower():
            # Walk up to containing section/panel
            container = el.find_parent(['div', 'table', 'section', 'fieldset'])
            if container:
                # Grab all text from the container, skip the header itself
                parts = []
                for child in container.find_all(['span', 'td', 'div', 'label', 'p']):
                    t = child.get_text(strip=True)
                    if t and t.lower() not in ('licensed professional', ''):
                        parts.append(t)
                if parts:
                    lp_text = ' | '.join(dict.fromkeys(parts))  # deduplicate while preserving order
                    break

    # Fallback: just grab the next sibling block
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

    # ---------------------------------------------------------------------------
    # Other detail fields
    # ---------------------------------------------------------------------------
    lead['subType']        = get_field('Sub Type')
    lead['occupancyType']  = get_field('What is the occupancy type?')
    lead['numberOfPanels'] = get_field('Number of Panels') or get_field('Number of Modules')

    # System size — try detail page fields first, fall back to what was parsed from description
    system_size = (
        get_field('System Size') or
        get_field('DC System Size') or
        get_field('Rounded Kilowatts Total System Size') or
        get_field('kW') or
        ''
    )
    if not system_size:
        # Try parsing from description on the detail page
        project_desc = get_field('Project Description')
        system_size = parse_system_size(project_desc)
    if not system_size and lead.get('description'):
        system_size = parse_system_size(lead['description'])
    if system_size:
        lead['systemSize'] = system_size

    # Work Location — actual site address from detail page
    work_loc = ''
    for el in soup.find_all(['span', 'td', 'div', 'th']):
        if 'work location' in el.get_text().lower():
            parent = el.find_parent(['tr', 'div', 'section', 'table'])
            if parent:
                nxt = parent.find_next_sibling()
                if nxt:
                    work_loc = nxt.get_text(separator=' ', strip=True)
                    break
    if work_loc:
        lead['siteAddress'] = work_loc

    # Project description — full text
    project_desc_clean = get_field('Project Description')
    if project_desc_clean:
        lead['projectDescription'] = project_desc_clean

    # Owner from Contacts tab (San Diego) or from description (other cities)
    if lead.get('_owner_from_contacts'):
        await detail_page.evaluate("""
            () => {
                const links = Array.from(document.querySelectorAll('a'));
                const c = links.find(l => l.textContent.trim() === 'Contacts');
                if (c) c.click();
            }
        """)
        await detail_page.wait_for_timeout(1500)
        html2 = await detail_page.content()
        soup2 = BeautifulSoup(html2, 'lxml')
        owner_block = ''
        for el in soup2.find_all(['span', 'td', 'div', 'th', 'h2', 'h3', 'strong']):
            if 'owner on application' in el.get_text(strip=True).lower():
                container = el.find_parent(['div', 'table', 'section', 'fieldset', 'tr'])
                if container:
                    parts = []
                    for sib in container.find_next_siblings():
                        t = sib.get_text(separator=' ', strip=True)
                        if t:
                            parts.append(t)
                        if sib.find(['h2', 'h3', 'strong']) and len(parts) > 1:
                            break
                    if parts:
                        flat = [p.strip() for p in parts if p.strip()]
                        owner_block = ' | '.join(list(dict.fromkeys(flat))[:5])
                        break
        if owner_block:
            lead['ownerOnApplication'] = owner_block
            name_part = owner_block.split('|')[0].strip()
            name_words = name_part.split()
            if len(name_words) >= 2:
                lead['homeownerFirstName'] = name_words[0]
                lead['homeownerLastName']  = ' '.join(name_words[1:])

        # Contacts tab swaps the DOM — old soup is stale. Return to record view,
        # re-open Application Information, then read kW / Electrical / ESS (etc.).
        await _click_record_details_tab(detail_page)
        await _expand_accela_detail_sections(detail_page)
        html_app = await detail_page.content()
        soup_app = BeautifulSoup(html_app, 'lxml')

        kwh = _get_field_from_soup(soup_app, 'Rounded Kilowatts Total System Size')
        if kwh:
            lead['systemSize'] = kwh + ' kW'
        elec = _get_field_from_soup(soup_app, 'Electrical Service Upgrade')
        if elec:
            lead['electricalServiceUpgrade'] = elec
        ess = _get_field_from_soup(soup_app, 'Advanced Energy Storage System')
        if ess:
            lead['advancedEnergyStorage'] = ess
        cs = _get_field_from_soup(soup_app, 'Cross Street')
        if cs:
            lead['crossStreet'] = cs
        dow = _get_field_from_soup(soup_app, 'Description of Work')
        if dow:
            lead['descriptionOfWork'] = dow
        nob = _get_field_from_soup(soup_app, 'Number of Buildings')
        if nob:
            lead['numberOfBuildings'] = nob
        hu = _get_field_from_soup(soup_app, 'Housing Units')
        if hu:
            lead['housingUnits'] = hu
    else:
        if project_desc_clean:
            first, last = extract_homeowner_name(project_desc_clean, '')
            if first and not lead.get('homeownerFirstName'):
                lead['homeownerFirstName'] = first
                lead['homeownerLastName']  = last

        # Application Information fields (non–Contacts-tab portals)
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

    log.info(
        f'  jobValue={lead.get("jobValue","?")} | size={lead.get("systemSize","?")} | '
        f'elec={lead.get("electricalServiceUpgrade","?")} | ess={lead.get("advancedEnergyStorage","?")} | '
        f'owner={lead.get("homeownerFirstName","")} {lead.get("homeownerLastName","")}'
    )


def _set_defaults(lead):
    for field in ['jobValue', 'subType', 'occupancyType', 'numberOfPanels',
                  'licensedProfessional', 'systemSize', 'projectDescription',
                  'ownerOnApplication', 'electricalServiceUpgrade',
                  'advancedEnergyStorage', 'crossStreet', 'descriptionOfWork',
                  'numberOfBuildings', 'housingUnits']:
        lead.setdefault(field, '')


def scrape_accela(city_key: str, start_date: str, end_date: str):
    config = CITY_CONFIGS.get(city_key)
    if not config:
        raise ValueError(f'Unknown city: {city_key}. Available: {list(CITY_CONFIGS.keys())}')
    return asyncio.run(scrape_accela_async(config, start_date, end_date))
