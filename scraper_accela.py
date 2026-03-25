"""
Generic Accela scraper — works for any standard Accela portal.
Each city passes its own config dict.
"""
import asyncio
import csv
import re

from accela_name_utils import extract_homeowner_name, parse_system_size
from accela_detail_primitives import resolve_permit_url_from_href, zip_from_address_line
from cities.detail_registry import get_detail_fetcher

import json
import logging
import os
import tempfile
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


def _csv_norm_key(k):
    return re.sub(r'[^a-z0-9]', '', (k or '').lower())


def _csv_get(row: dict, *aliases: str) -> str:
    """First non-empty cell matching common Accela export header variants."""
    if not row:
        return ''
    by_norm = {_csv_norm_key(k): (k, v) for k, v in row.items()}
    for a in aliases:
        na = _csv_norm_key(a)
        if na in by_norm:
            v = by_norm[na][1]
            if v is not None and str(v).strip():
                return str(v).strip()
    return ''


def _accela_row_passes_filters(description: str, short_notes: str, status: str,
                               permit_date_str: str, cfg: dict) -> bool:
    """Same rules as HTML row scrape (short notes / solar keywords / issued age)."""
    desc_lower = (description or '').lower()
    short_notes_filter = cfg.get('short_notes_filter', None)
    if short_notes_filter:
        if short_notes_filter.lower() not in (short_notes or '').lower():
            return False
    elif cfg.get('skip_solar_description_filter'):
        pass
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
            return False

    issued_filter_days = cfg.get('issued_filter_days', 7)
    if (status or '').lower() == 'issued' and permit_date_str:
        try:
            from datetime import datetime
            permit_date = datetime.strptime(permit_date_str, '%m/%d/%Y')
            if (datetime.now() - permit_date).days > issued_filter_days:
                return False
        except Exception:
            pass
    return True


def _accela_csv_row_raw(row: dict) -> dict:
    """All columns from export as stripped strings (source of truth blob)."""
    out = {}
    for k, v in (row or {}).items():
        if k is None:
            continue
        key = str(k).strip()
        if not key:
            continue
        out[key] = '' if v is None else str(v).strip()
    return out


def _csv_description_fallback(
    description: str, permit_type: str, project_name: str, short_notes: str
) -> str:
    """
    Many Accela exports (e.g. San Diego PDS) omit Permit Description; narrative
    is in Record Type + Project Name + Short Notes. Merge so Base44/UI/search
    get text even when CapDetail enrichment fails.
    """
    if (description or '').strip():
        return description.strip()
    parts = []
    if (permit_type or '').strip():
        parts.append(permit_type.strip())
    if (project_name or '').strip():
        parts.append(project_name.strip())
    if (short_notes or '').strip():
        parts.append(short_notes.strip())
    return ' | '.join(parts) if parts else ''


def _leads_from_accela_csv_path(path: str, config: dict, source: str,
                                base_url: str, module: str) -> list:
    """
    Parse Accela export CSV in one pass: map known fields + attach full row as accelaCsv.
    """
    cfg = config or {}
    leads = []
    with open(path, 'r', encoding='utf-8-sig', newline='') as f:
        reader = csv.DictReader(f)
        if reader.fieldnames:
            log.info(f'  CSV columns ({len(reader.fieldnames)}): {reader.fieldnames[:20]}{"..." if len(reader.fieldnames) > 20 else ""}')
        for row in reader:
            raw = _accela_csv_row_raw(row)
            permit_num = _csv_get(row, 'Permit #', 'Record ID', 'Record Id', 'Permit Number', 'Permit No')
            if not permit_num or permit_num.lower() in ('log in', 'login'):
                continue
            description = _csv_get(row, 'Permit Description', 'Description', 'Work Description')
            short_notes = _csv_get(row, 'Short Notes', 'Comments')
            status = _csv_get(row, 'Status', 'Record Status')
            permit_date_str = _csv_get(row, 'Date', 'File Date', 'Opened Date')
            project_name = _csv_get(row, 'Project Name', 'Project')
            permit_type = _csv_get(row, 'Permit Type', 'Record Type', 'Type')
            raw_address = _csv_get(
                row,
                'Address',
                'Full Address',
                'Property Address',
                'Street Address',
                'Site Address',
                'Site Location',
                'Parcel Address',
                'Location',
                'Primary Address',
            )

            if not _accela_row_passes_filters(description, short_notes, status, permit_date_str, cfg):
                log.info(f'  CSV skip (filter): {(description or permit_num)[:60]}')
                continue

            description = _csv_description_fallback(
                description, permit_type, project_name, short_notes
            )

            # Only strip trailing 5-digit ZIP, not all trailing digits (avoids eating street numbers)
            address = re.sub(r',?\s*\b\d{5}(?:-\d{4})?\s*$', '', raw_address).strip().rstrip(',').strip()
            zip_code = zip_from_address_line(address)

            owner_first, owner_last = extract_homeowner_name(description, project_name)
            system_size = parse_system_size(description) or parse_system_size(project_name)
            if not system_size:
                for hk, hv in raw.items():
                    lhk = (hk or '').lower()
                    if any(x in lhk for x in ('description', 'project', 'note', 'work', 'scope')):
                        system_size = parse_system_size(hv)
                        if system_size:
                            break
            lead_category = cfg.get('lead_category', 'residential')

            leads.append({
                'homeownerFirstName':   owner_first,
                'homeownerLastName':    owner_last,
                'permitNumber':         permit_num,
                'permitUrl':            f'{base_url}/Cap/CapDetail.aspx?altId={permit_num}&module={module}' if permit_num else '',
                'date':                 permit_date_str,
                'siteAddress':          address,
                'address':              address,
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
                'permitType':           permit_type,
                'shortNotes':           short_notes,
                'leadCategory':         lead_category,
                'source':               source,
                'enrichmentStage':      'scraped',
                'uniqueId':             f'{cfg.get("source", source)}_{permit_num}',
                'detailHref':           None,
                'jobInfo':              '',
                '_owner_from_contacts':  cfg.get('owner_from_contacts', False),
                # Full export row — all portal columns in one place for APIs / debugging
                'accelaCsv':            raw,
            })

    seen = set()
    unique = []
    for lead in leads:
        pn = lead.get('permitNumber', '')
        if pn and pn not in seen:
            seen.add(pn)
            unique.append(lead)
        elif not pn:
            unique.append(lead)
    log.info(f'  CSV parsed: {len(unique)} unique permits (from {len(leads)} rows)')
    return unique


async def _inject_search_project_name(search, city_name: str, value: str) -> bool:
    """
    Set Accela general-search Project Name (e.g. OTC). Playwright fill() can fail silently
    (strict mode, hidden duplicates); match date injection via DOM + events.
    """
    raw = (value or '').strip()
    if not raw:
        return False
    want_js = json.dumps(raw)
    result = await search.evaluate(
        f"""
        () => {{
            const want = {want_js};
            const el = document.querySelector('[id*="txtGSProjectName"]')
                || document.querySelector('input[name*="txtGSProjectName" i]')
                || document.querySelector('input[id*="ProjectName" i]');
            if (!el) return {{ ok: false, reason: 'no matching input' }};
            el.focus();
            el.value = want;
            el.dispatchEvent(new Event('input', {{ bubbles: true }}));
            el.dispatchEvent(new Event('change', {{ bubbles: true }}));
            el.dispatchEvent(new Event('blur', {{ bubbles: true }}));
            return {{ ok: true, id: el.id, value: el.value }};
        }}
        """
    )
    if result.get('ok'):
        log.info(
            f'[{city_name}] Project name filter set to {result.get("value")!r} '
            f'(#{result.get("id")})'
        )
        return True
    log.warning(
        f'[{city_name}] Project name filter NOT applied ({result.get("reason")}) '
        f'— wanted {raw!r}'
    )
    return False


async def _download_accela_results_csv(search, city_name: str, source: str) -> str:
    """
    Click Accela export and save CSV to a temp file. Returns path.
    """
    export_selectors = [
        'a[id*="lnkExport"]',
        'a[title*="Export"]',
        'a[title*="Download"]',
        'a:text("Export")',
        'a:text("Download")',
        'input[value*="Export"]',
        'input[value*="export"]',
    ]
    log.info(f'[{city_name}] Downloading results CSV (export)...')
    await search.evaluate('() => window.scrollTo(0, document.body.scrollHeight)')
    await search.wait_for_timeout(400)
    # Downloads attach to Page; Frame has no expect_download.
    download_page = search if hasattr(search, 'expect_download') else search.page
    async with download_page.expect_download(timeout=120000) as dl_info:
        clicked = False
        for sel in export_selectors:
            try:
                loc = search.locator(sel)
                if await loc.count() > 0:
                    await loc.first.click(timeout=8000)
                    clicked = True
                    log.info(f'[{city_name}] Triggered export via: {sel}')
                    break
            except Exception:
                continue
        if not clicked:
            raise RuntimeError('No CSV/Export control found on results page')
    download = await dl_info.value
    fd, path = tempfile.mkstemp(suffix='.csv', prefix=f'accela_{source}_')
    os.close(fd)
    await download.save_as(path)
    log.info(f'[{city_name}] CSV saved: {path} ({download.suggested_filename})')
    return path


# Row selectors: classic Accela grid + fallbacks when markup differs by portal/version.
_ACCELA_RESULT_ROW_SELECTORS = (
    'tr.ACA_TabRow_Odd, tr.ACA_TabRow_Even, tr.gdvPermitList_Row'
)
_ACCELA_RESULT_ROW_SELECTORS_ALT = (
    'table[id*="gvPermit"] tbody tr, '
    'table[id*="PermitList"] tbody tr, '
    'table.ACA_GridView tbody tr'
)


def _soup_select_result_rows(soup):
    """Parse permit list rows from Accela HTML; try fallbacks if classic classes missing."""
    rows = soup.select(_ACCELA_RESULT_ROW_SELECTORS)
    if rows:
        return rows
    out = []
    for tr in soup.select(_ACCELA_RESULT_ROW_SELECTORS_ALT):
        if tr.find('th') is not None:
            continue
        tds = tr.find_all('td')
        if len(tds) >= 2:
            out.append(tr)
    return out


async def _wait_accela_results_after_search(search, city_name: str, timeout_ms: int = 120000) -> str:
    """
    After Search: wait for result rows, explicit empty message, or timeout.
    Returns 'rows' or 'empty'.
    """
    import time as _time
    deadline = _time.monotonic() + timeout_ms / 1000.0
    while _time.monotonic() < deadline:
        state = await search.evaluate(
            """() => {
                const sel = 'tr.ACA_TabRow_Odd, tr.ACA_TabRow_Even, tr.gdvPermitList_Row';
                let n = document.querySelectorAll(sel).length;
                if (n > 0) return { k: 'rows', n: n };
                const alts = [
                    'table[id*="gvPermit"] tbody tr',
                    'table[id*="PermitList"] tbody tr',
                    'table.ACA_GridView tbody tr',
                ];
                for (const a of alts) {
                    const trs = Array.from(document.querySelectorAll(a))
                        .filter(t => !t.querySelector('th') && t.querySelectorAll('td').length >= 2);
                    if (trs.length > 0) return { k: 'rows', n: trs.length };
                }
                const t = (document.body && document.body.innerText || '').toLowerCase();
                const hints = [
                    'no records', 'no record', 'no results', 'did not return',
                    'there are no records', '0 records', 'nothing found',
                    'your search did not return', 'no data',
                ];
                if (hints.some(h => t.includes(h))) return { k: 'empty' };
                return { k: 'wait' };
            }"""
        )
        kind = state.get('k')
        if kind == 'wait':
            await search.wait_for_timeout(800)
            continue
        if kind == 'rows':
            log.info(f'[{city_name}] Results grid ready ({state.get("n", "?")} row elements)')
            return 'rows'
        if kind == 'empty':
            log.info(f'[{city_name}] Search returned no records (empty state)')
            return 'empty'

    final = await search.evaluate(
        """() => {
            const t = (document.body && document.body.innerText || '').toLowerCase();
            if (t.includes('no record') || t.includes('no results') || t.includes('did not return'))
                return 'empty';
            const sel = 'tr.ACA_TabRow_Odd, tr.ACA_TabRow_Even, tr.gdvPermitList_Row';
            if (document.querySelectorAll(sel).length > 0) return 'rows';
            const alts = [
                'table[id*="gvPermit"] tbody tr',
                'table[id*="PermitList"] tbody tr',
                'table.ACA_GridView tbody tr',
            ];
            for (const a of alts) {
                const trs = Array.from(document.querySelectorAll(a))
                    .filter(x => !x.querySelector('th') && x.querySelectorAll('td').length >= 2);
                if (trs.length > 0) return 'rows';
            }
            return 'unknown';
        }"""
    )
    if final == 'empty':
        log.warning(f'[{city_name}] Grid wait timed out; page indicates no results — treating as empty')
        return 'empty'
    if final == 'rows':
        log.warning(f'[{city_name}] Grid appeared after extended wait — continuing')
        return 'rows'
    raise TimeoutError(
        f'[{city_name}] No result rows or empty-state text after search (Accela UI may have changed)'
    )


# ---------------------------------------------------------------------------
# Generic Accela scraper
# ---------------------------------------------------------------------------

async def scrape_accela_async(config: dict, start_date: str, end_date: str):
    base_url  = config['base_url']
    module    = config['module']
    # CapDetail URLs must use the record's module (e.g. SD PDS permits → PDS, not Building).
    detail_module = (config.get('cap_detail_module') or module or '').strip() or module
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
                        _pt = json.dumps(config['permit_type'])
                        await search.evaluate(f"""
                            () => {{
                                const sel = document.querySelector('{type_sel}');
                                const want = {_pt};
                                const opt = Array.from(sel.options).find(
                                    o => o.text.trim() === want
                                );
                                if (opt) {{
                                    sel.value = opt.value;
                                    sel.dispatchEvent(new Event('change'));
                                }}
                            }}
                        """)
                        # Accela keeps long-polling / beacon traffic — networkidle often times out.
                        await search.wait_for_timeout(1500)
                        try:
                            await page.wait_for_load_state('domcontentloaded', timeout=12000)
                        except Exception:
                            pass
                        await search.wait_for_timeout(1000)
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
                await _inject_search_project_name(
                    search, city_name, str(config['use_project_name'])
                )

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

            outcome = await _wait_accela_results_after_search(search, city_name, timeout_ms=120000)
            if outcome == 'empty':
                log.info(f'[{city_name}] No permits in range — returning empty list')
                return []

            # CSV export first for all cities (full row → accelaCsv); HTML grid is fallback.
            # Set skip_csv_download: True in city config to force HTML-only.
            leads = []
            csv_path = None
            if config.get('skip_csv_download'):
                log.info(f'[{city_name}] skip_csv_download set — using HTML grid only')
                leads = await _scrape_rows(search, source, base_url, detail_module, config)
            else:
                try:
                    csv_path = await _download_accela_results_csv(search, city_name, source)
                    leads = _leads_from_accela_csv_path(
                        csv_path, config, source, base_url, detail_module,
                    )
                    # For PDS iframe portals (e.g. SD), the constructed CapDetail URL is
                    # rejected with Error.aspx. Harvest real hrefs from the grid while
                    # we still have the results page loaded, then match to leads by permit num.
                    if config.get('portal_pds_iframe') and leads:
                        try:
                            # Paginate through ALL grid pages to collect every href before CSV parse.
                            # SD portal rejects CapDetail?altId= URLs; only the session-signed
                            # hrefs from the grid work (Module=LUEG-PDS&capID1=...&capID3=...).
                            all_hrefs = {}
                            harvest_page = 1
                            while True:
                                page_hrefs = await search.evaluate("""
                                    () => {
                                        const rows = document.querySelectorAll(
                                            'tr.ACA_TabRow_Odd, tr.ACA_TabRow_Even, tr.gdvPermitList_Row, tr[class*="PermitList"]'
                                        );
                                        const out = {};
                                        rows.forEach(row => {
                                            const a = row.querySelector('a[href]');
                                            if (!a) return;
                                            const href = a.getAttribute('href') || '';
                                            const text = a.textContent.trim();
                                            if (text) out[text] = href;
                                        });
                                        return out;
                                    }
                                """)
                                all_hrefs.update(page_hrefs)
                                log.info(f'[{city_name}] Grid page {harvest_page}: harvested {len(page_hrefs)} hrefs (total {len(all_hrefs)})')
                                # Check for next page link
                                has_next = await search.evaluate(f"""
                                    () => !!document.querySelector('a[href*="Page$"][title="{harvest_page + 1}"], a:not([href="#"]):not([href="javascript:void(0)"]):not([href="javascript:;"])')
                                        && Array.from(document.querySelectorAll('a')).some(a => a.textContent.trim() === '{harvest_page + 1}')
                                """)
                                if not has_next:
                                    break
                                try:
                                    await search.click(f'a:text-is("{harvest_page + 1}")', timeout=5000)
                                    await _wait_accela_results_after_search(search, city_name, timeout_ms=30000)
                                    harvest_page += 1
                                except Exception:
                                    break
                            matched = 0
                            for lead in leads:
                                pn = lead.get('permitNumber', '')
                                if pn and pn in all_hrefs:
                                    lead['detailHref'] = all_hrefs[pn]
                                    matched += 1
                            unmatched = [l.get('permitNumber','') for l in leads if not l.get('detailHref') and l.get('permitNumber')]
                            log.info(f'[{city_name}] Total grid hrefs: {len(all_hrefs)}, matched {matched}/{len(leads)} leads')
                            if unmatched:
                                log.info(f'[{city_name}] Unmatched permit#s: {unmatched[:5]} ... sample grid keys: {list(all_hrefs.keys())[:5]}')
                        except Exception as e:
                            log.warning(f'[{city_name}] Could not harvest grid hrefs: {e}')
                except Exception as e:
                    log.warning(f'[{city_name}] CSV export failed, using HTML grid: {e}')
                    leads = await _scrape_rows(search, source, base_url, detail_module, config)
                finally:
                    if csv_path and os.path.isfile(csv_path):
                        try:
                            os.unlink(csv_path)
                        except OSError:
                            pass
            log.info(f'[{city_name}] Found {len(leads)} permits in date range')

            if config.get('skip_detail_fetch'):
                # Grid / CSV already has all fields; only set permit URL from row link + defaults.
                for lead in leads:
                    permit_num = lead.get('permitNumber')
                    if not permit_num:
                        continue
                    resolve_permit_url_from_href(base_url, permit_num, detail_module, lead)
                    _set_defaults(lead)
            else:
                # Reuse the same browser context as search/CSV export — Accela (esp. county PDS)
                # ties session cookies to Citizen Access; a fresh context yields empty/login detail pages.
                # For portal_pds_iframe cities (e.g. SD), CapDetail must be loaded
                # within the same page that navigated through the PDS entry — a new_page()
                # in the same context still gets an Error.aspx because the portal checks
                # the navigation chain, not just cookies. Reuse the search page for these.
                use_same_page = bool(config.get('portal_pds_iframe'))

                for i, lead in enumerate(leads):
                    permit_num = lead.get('permitNumber')
                    if not permit_num:
                        continue
                    log.info(f'[{city_name}] Details {permit_num} ({i+1}/{len(leads)})...')
                    if use_same_page:
                        detail_page = page
                        close_after = False
                    else:
                        detail_page = await context.new_page()
                        close_after = True
                    try:
                        await _get_permit_details(
                            detail_page, base_url, detail_module, permit_num, lead, config,
                        )
                    except Exception as e:
                        log.error(f'[{city_name}] Detail failed {permit_num}: {e}')
                        _set_defaults(lead)
                    finally:
                        if close_after:
                            await detail_page.close()

            leads = [l for l in leads if not l.get('_skip_ingest')]
            # Strip internal flags before returning
            for lead in leads:
                lead.pop("_owner_from_contacts", None)
                lead.pop("detailHref", None)
                lead.pop("_skip_ingest", None)
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
        rows = _soup_select_result_rows(soup)
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

            col_permit_num = cfg.get('col_permit_num', None)
            link = None
            href = None
            link_text = ''
            if isinstance(col_permit_num, int) and len(cells) > col_permit_num:
                link = cells[col_permit_num].find('a', href=True)
            if link is None:
                link = row.find('a', href=True)
            if link is not None:
                href = link.get('href')
                link_text = (link.get_text(strip=True) or '').strip()

            if col_permit_num is not None:
                cell_txt = raw_cells[col_permit_num] if len(raw_cells) > col_permit_num else ''
                permit_num = (link_text or cell_txt).strip()
            else:
                permit_num = link_text if link_text else (raw_cells[2] if len(raw_cells) > 2 else '')

            description = raw_cells[col_description] if len(raw_cells) > col_description else ''
            col_sn = cfg.get('col_short_notes', 8)
            short_notes = raw_cells[col_sn] if len(raw_cells) > col_sn else ''
            status = raw_cells[col_status] if col_status is not None and len(raw_cells) > col_status else ''
            permit_date_str = raw_cells[col_date] if len(raw_cells) > col_date else ''

            if not _accela_row_passes_filters(description, short_notes, status, permit_date_str, cfg):
                log.info(f'  Skipping (filter): {(description or permit_num)[:60]}')
                continue

            project_name = raw_cells[col_project_name] if col_project_name is not None and len(raw_cells) > col_project_name else ''
            permit_type = raw_cells[col_permit_type] if len(raw_cells) > col_permit_type else ''
            description = _csv_description_fallback(
                description, permit_type, project_name, short_notes
            )

            raw_address = raw_cells[col_address] if len(raw_cells) > col_address else ''
            if cfg.get('skip_address_apn_strip'):
                address = raw_address.strip()
            else:
                # Only strip trailing 5-digit ZIP, not all trailing digits (avoids eating street numbers)
                address = re.sub(r',?\s*\b\d{5}(?:-\d{4})?\s*$', '', raw_address).strip().rstrip(',').strip()

            zip_code = zip_from_address_line(address)

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
                'address':              address,
                'zipCode':              zip_code,
                'city':                 cfg.get('name', ''),
                'description':          description,
                'systemSize':           system_size,
                'numberOfPanels':       '',
                'jobValue':             '',
                'status':               status,
                'recordStatus':         status,
                'subType':              '',
                'occupancyType':        '',
                'licensedProfessional': '',
                'projectName':          project_name,
                'permitType':           permit_type,
                'leadCategory':         lead_category,
                'source':               source,
                'enrichmentStage':      'scraped',
                'uniqueId':             f'{cfg.get("source", source)}_{permit_num}',
                # Internal flags — stripped before output
                'detailHref':           href,
                'jobInfo':              '',
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
        cfg = config or {}
        pname = cfg.get('name') or 'permits'
        nxt = await _wait_accela_results_after_search(page, pname, timeout_ms=45000)
        if nxt == 'empty':
            log.warning(f'  Page {page_num + 1} click returned no rows — stopping pagination')
            break
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



async def _get_permit_details(detail_page, base_url, module, permit_num, lead, config=None):
    cfg = config or {}
    fetcher = get_detail_fetcher(cfg.get('_city_key') or '')
    await fetcher(detail_page, base_url, module, permit_num, lead, cfg, log)


def _set_defaults(lead):
    for field in ['jobValue', 'jobInfo', 'subType', 'occupancyType', 'numberOfPanels',
                  'licensedProfessional', 'systemSize', 'projectDescription',
                  'ownerOnApplication', 'homeownerEmail', 'homeownerPhone',
                  'ownerMailingAddress', 'electricalServiceUpgrade',
                  'advancedEnergyStorage', 'crossStreet', 'descriptionOfWork',
                  'numberOfBuildings', 'housingUnits', 'address', 'recordStatus']:
        lead.setdefault(field, '')


def scrape_accela(city_key: str, start_date: str, end_date: str):
    config = CITY_CONFIGS.get(city_key)
    if not config:
        raise ValueError(f'Unknown city: {city_key}. Available: {list(CITY_CONFIGS.keys())}')
    merged = {**config, '_city_key': city_key}
    return asyncio.run(scrape_accela_async(merged, start_date, end_date))
