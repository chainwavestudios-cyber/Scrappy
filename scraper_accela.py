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


import csv
import json
import logging
import os
import tempfile
from urllib.parse import urljoin
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
            raw_address = _csv_get(row, 'Address', 'Location', 'Site Address', 'Parcel Address')

            if not _accela_row_passes_filters(description, short_notes, status, permit_date_str, cfg):
                log.info(f'  CSV skip (filter): {(description or permit_num)[:60]}')
                continue

            address = re.sub(r',?\s*\d+\s*\d*\s*$', '', raw_address).strip().rstrip(',').strip()
            zip_match = re.search(r'\b(\d{5})(?:-\d{4})?\b', address)
            zip_code = zip_match.group(1) if zip_match else ''

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
                leads = await _scrape_rows(search, source, base_url, module, config)
            else:
                try:
                    csv_path = await _download_accela_results_csv(search, city_name, source)
                    leads = _leads_from_accela_csv_path(
                        csv_path, config, source, base_url, module,
                    )
                except Exception as e:
                    log.warning(f'[{city_name}] CSV export failed, using HTML grid: {e}')
                    leads = await _scrape_rows(search, source, base_url, module, config)
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
                    _resolve_permit_url_from_href(base_url, permit_num, module, lead)
                    _set_defaults(lead)
            else:
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
                        await _get_permit_details(
                            detail_page, base_url, module, permit_num, lead, config,
                        )
                    except Exception as e:
                        log.error(f'[{city_name}] Detail failed {permit_num}: {e}')
                        _set_defaults(lead)
                    finally:
                        await detail_page.close()
                        await detail_context.close()

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

            link = row.find('a')
            href = link['href'] if link else None
            link_text = link.get_text(strip=True) if link else ''

            col_permit_num = cfg.get('col_permit_num', None)
            if col_permit_num is not None:
                permit_num = raw_cells[col_permit_num] if len(raw_cells) > col_permit_num else ''
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


def _get_field_from_soup(soup, label):
    """Label/value pairs on Accela detail HTML (table or sibling layout)."""
    lbl = label.lower().rstrip(':')
    for el in soup.find_all(['span', 'td', 'div', 'label', 'th']):
        raw = el.get_text(strip=True)
        tl = raw.lower().rstrip(':')
        if tl == lbl:
            nxt = el.find_next_sibling()
            if nxt and nxt.get_text(strip=True):
                return nxt.get_text(strip=True)
            parent = el.find_parent()
            if parent:
                nxt2 = parent.find_next_sibling()
                if nxt2 and nxt2.get_text(strip=True):
                    return nxt2.get_text(separator=' ', strip=True)
            continue
        # e.g. "Job Value($): $9,000.00" in one element (Chula Vista)
        if lbl in ('job value($)', 'job value') and 'job value' in tl and ':' in raw:
            parts = raw.split(':', 1)
            if len(parts) == 2 and parts[1].strip():
                return parts[1].strip()
        # e.g. "Rounded Kilowatts Total System Size:6" (San Diego — label + value same node)
        if tl.startswith(lbl + ':') or tl.startswith(lbl + ' :'):
            parts = raw.split(':', 1)
            if len(parts) == 2 and parts[1].strip():
                return parts[1].strip()
    return ''


def _extract_work_location_accela(soup):
    """
    Chula Vista / Accela often put site address under 'Work Location' as:
    - multiline in one cell, or
    - label row + next table row, or
    - label + adjacent td (same row).
    """
    w = _get_field_from_soup(soup, 'Work Location')
    if w:
        return w

    for el in soup.find_all(['td', 'div', 'span']):
        txt = el.get_text(separator='\n', strip=True)
        if not txt:
            continue
        first = txt.split('\n')[0].strip().lower().rstrip(':')
        if first == 'work location' and '\n' in txt:
            lines = [ln.strip() for ln in txt.split('\n') if ln.strip()]
            if len(lines) >= 2:
                return '\n'.join(lines[1:])

    for el in soup.find_all(['span', 'td', 'div', 'th', 'label', 'strong']):
        raw = el.get_text(strip=True)
        low = raw.lower().rstrip(':').strip()
        if low != 'work location':
            continue
        nxt = el.find_next_sibling()
        if nxt and getattr(nxt, 'get_text', None):
            val = nxt.get_text(separator=' ', strip=True)
            if val:
                return val
        tr = el.find_parent('tr')
        if tr:
            ntr = tr.find_next_sibling('tr')
            if ntr:
                val = ntr.get_text(separator=' ', strip=True)
                if val:
                    return val
            tds = tr.find_all('td')
            for i, td in enumerate(tds):
                if 'work location' in td.get_text().lower() and i + 1 < len(tds):
                    val2 = tds[i + 1].get_text(separator=' ', strip=True)
                    if val2 and 'work location' not in val2.lower():
                        return val2
        par = el.find_parent('div')
        if par:
            for sib in el.find_next_siblings():
                if getattr(sib, 'get_text', None):
                    val = sib.get_text(separator=' ', strip=True)
                    if val:
                        return val
    return ''


def _extract_job_value_accela(soup):
    """
    Prefer 'Job Value($)' / 'Job Value' under Additional Information (Chula Vista).
    Fall back to empty so caller can try legacy 'Valuation' parsing.
    """
    for lbl in ('Job Value($)', 'Job Value', 'Valuation'):
        v = _get_field_from_soup(soup, lbl)
        if v and len(v) < 200:
            return v

    for el in soup.find_all(['span', 'td', 'div', 'label', 'th']):
        t = el.get_text(strip=True)
        tl = t.lower()
        if 'job value' not in tl or len(t) > 60:
            continue
        if ':' in t:
            parts = t.split(':', 1)
            if len(parts) == 2 and parts[1].strip():
                return parts[1].strip()
        nxt = el.find_next_sibling()
        if nxt and getattr(nxt, 'get_text', None):
            val = nxt.get_text(strip=True)
            if val:
                return val
        tr = el.find_parent('tr')
        if tr:
            ntr = tr.find_next_sibling('tr')
            if ntr:
                val = ntr.get_text(separator=' ', strip=True)
                if val:
                    return val
            tds = tr.find_all('td')
            for i, td in enumerate(tds):
                if 'job value' in td.get_text().lower() and i + 1 < len(tds):
                    val2 = tds[i + 1].get_text(strip=True)
                    if val2:
                        return val2

    blob = soup.get_text(' ', strip=True)
    m = re.search(
        r'Job Value\s*\(\s*\$\s*\)\s*:?\s*(\$?\s*[\d,]+\.?\d*)',
        blob,
        re.I,
    )
    if m:
        return re.sub(r'\s+', '', m.group(1))
    return ''


def _sync_address_zip_for_ingest(lead):
    """Base44 SolarPermit uses `address` + `zipCode`; keep `siteAddress` in sync."""
    loc = (lead.get('siteAddress') or lead.get('address') or '').strip()
    if not loc:
        return
    single = re.sub(r'\s+', ' ', loc.replace('\n', ' ')).strip()
    lead['siteAddress'] = single
    lead['address'] = single
    zm = re.search(r'\b(\d{5})(?:-\d{4})?\b', single)
    if zm:
        z = lead.get('zipCode') or ''
        if not (str(z).strip()):
            lead['zipCode'] = zm.group(1)


def _resolve_permit_url_from_href(base_url: str, permit_num: str, module: str, lead: dict) -> None:
    """Prefer the grid row link (real Accela URL); fallback to CapDetail altId."""
    href = lead.get('detailHref')
    if href and str(href).strip() and not str(href).lower().startswith('javascript'):
        h = str(href).strip()
        if h.startswith('http'):
            lead['permitUrl'] = h
        else:
            base = (base_url or '').rstrip('/')
            lead['permitUrl'] = urljoin(base + '/', h.lstrip('/'))
        return
    lead['permitUrl'] = f'{base_url}/Cap/CapDetail.aspx?altId={permit_num}&module={module}'


def _primary_scope_allowed(soup, cfg: dict) -> bool:
    """
    When configured (e.g. San Diego residential solar), require Primary Scope text
    to contain all substrings (e.g. 8002 + Solar Photovoltaic).
    """
    reqs = cfg.get('require_primary_scope_contains')
    if not reqs:
        return True
    if isinstance(reqs, str):
        reqs = [reqs]
    scope_line = (
        _get_field_from_soup(soup, 'Primary Scope Code')
        or _get_field_from_soup(soup, 'Primary Scope')
        or ''
    )
    blob = soup.get_text(' ', strip=True)
    combined = f'{scope_line} {blob}'.lower()
    return all(str(r).lower() in combined for r in reqs)


def _parse_owner_contacts_soup(soup2, lead: dict) -> None:
    """
    San Diego / Accela Contacts tab: Owner on Application — name, address, zip, email.
    """
    blob = ''
    best_len = 0
    for el in soup2.find_all(['div', 'table', 'td', 'fieldset', 'section', 'tbody']):
        t = el.get_text(separator='\n', strip=True)
        tl = t.lower()
        if 'owner on application' not in tl:
            continue
        if '@' in t or 'e-mail' in tl or 'email' in tl:
            if len(t) > best_len:
                blob = t
                best_len = len(t)
    if not blob:
        for el in soup2.find_all(string=re.compile(r'owner\s+on\s+application', re.I)):
            p = el.find_parent(['div', 'table', 'td', 'tr'])
            if p:
                t = p.get_text(separator='\n', strip=True)
                if len(t) > 30:
                    blob = t
                    break
    if not blob:
        return

    lead['ownerOnApplication'] = re.sub(r'\s+', ' ', blob.replace('\n', ' | ')).strip()

    em = re.search(
        r'E-?mail\s*:?\s*([\w.\-+]+@[\w.\-]+\.[a-zA-Z]{2,})',
        blob,
        re.I,
    )
    if em:
        lead['homeownerEmail'] = em.group(1).strip()

    zm = re.search(r'\b(\d{5})(?:-\d{4})?\b', blob)
    if zm:
        lead['zipCode'] = zm.group(1)

    addr_line = None
    for line in blob.split('\n'):
        ln = line.strip()
        if not ln:
            continue
        if re.search(r'\b(CA|California)\b', ln, re.I) and re.search(r'\d{5}', ln):
            addr_line = re.sub(r'\s+', ' ', ln)
            break
        if re.search(r'\b(ST|AVE|RD|DR|LN|CT|WAY|BLVD|CIR)\b', ln, re.I) and re.search(r'\d', ln):
            addr_line = re.sub(r'\s+', ' ', ln)

    # Job-site address usually comes from CSV; owner block is often mailing — do not replace.
    if addr_line and not (lead.get('siteAddress') or lead.get('address') or '').strip():
        lead['siteAddress'] = addr_line
        lead['address'] = addr_line
    elif addr_line:
        lead['ownerMailingAddress'] = addr_line

    pm = re.search(
        r'Primary\s+Phone\s*:?\s*([\d\s\-\(\)\.]+)',
        blob,
        re.I,
    )
    if pm:
        lead['homeownerPhone'] = re.sub(r'\s+', ' ', pm.group(1)).strip()

    lines = [x.strip() for x in blob.split('\n') if x.strip()]
    name_line = None
    for i, ln in enumerate(lines):
        if 'owner on application' in ln.lower():
            for j in range(i + 1, min(i + 5, len(lines))):
                cand = lines[j]
                if '@' in cand or re.search(r'\d{5}', cand):
                    continue
                if re.search(r'\b(st|ave|rd|dr|ln|ct|way|blvd|cir|hwy)\b', cand, re.I):
                    continue
                parts = cand.split()
                if len(parts) >= 2 and len(cand) < 120:
                    name_line = cand
                    break
            break
    if not name_line:
        for ln in lines:
            if '@' in ln or re.search(r'\d{5}', ln):
                continue
            if re.search(r'\b(st|ave|rd|dr|ln|ct|way|blvd|cir)\b', ln, re.I):
                continue
            parts = ln.split()
            if len(parts) >= 2 and len(ln) < 100 and re.match(r'^[A-Za-z]', ln):
                name_line = ln
                break
    if name_line:
        parts = name_line.split()
        lead['homeownerFirstName'] = parts[0]
        lead['homeownerLastName'] = ' '.join(parts[1:]) if len(parts) > 1 else ''


async def _click_more_details_visible(detail_page):
    """Accela Contacts (and Record) panels often hide rows until More Details is clicked."""
    await detail_page.evaluate("""
        () => {
            const els = Array.from(document.querySelectorAll('a, button, span'));
            const more = els.find(l => (l.textContent || '').includes('More Details'));
            if (more) { more.click(); return true; }
            return false;
        }
    """)
    await detail_page.wait_for_timeout(1800)


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
    # San Diego: Primary Scope / kW / ESS often under Application Details
    await detail_page.evaluate("""
        () => {
            const els = Array.from(document.querySelectorAll('a, span, button'));
            const ad = els.find(l => l.textContent.trim() === 'Application Details');
            if (ad) ad.click();
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


async def _get_permit_details(detail_page, base_url, module, permit_num, lead, config=None):
    cfg = config or {}
    _resolve_permit_url_from_href(base_url, permit_num, module, lead)
    detail_url = lead['permitUrl']
    log.info(f'  → {detail_url}')

    # domcontentloaded is faster and more reliable than networkidle — avoids timeouts
    await detail_page.goto(detail_url, wait_until='domcontentloaded', timeout=20000)
    await detail_page.wait_for_timeout(2000)

    owner_fc = bool(lead.get('_owner_from_contacts'))
    # San Diego PDS: Record Details (LP + Project Description) is visible first; expand
    # Application Information only after Contacts → More Details → owner.
    if not owner_fc:
        await _expand_accela_detail_sections(detail_page)

    html = await detail_page.content()
    soup = BeautifulSoup(html, 'lxml')

    if cfg.get('require_primary_scope_contains') and not _primary_scope_allowed(soup, cfg):
        lead['_skip_ingest'] = True
        log.info(f'  skip (primary scope): {permit_num}')
        return

    def get_field(label):
        return _get_field_from_soup(soup, label)

    # ---------------------------------------------------------------------------
    # Job Value — Chula Vista: "Job Value($)" under Additional Information;
    # other portals: "Valuation" etc.
    # ---------------------------------------------------------------------------
    job_value = _extract_job_value_accela(soup)
    if not job_value:
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

    # Work Location — site address (Chula Vista: multiline under label)
    work_loc = _extract_work_location_accela(soup)
    if work_loc:
        if owner_fc and (lead.get('siteAddress') or lead.get('address') or '').strip():
            pass
        else:
            lead['siteAddress'] = work_loc

    # Project description — full text
    project_desc_clean = get_field('Project Description')
    if project_desc_clean:
        lead['projectDescription'] = project_desc_clean

    # Owner from Contacts tab (San Diego PDS): Contacts → More Details → Owner on Application
    if lead.get('_owner_from_contacts'):
        await detail_page.evaluate("""
            () => {
                const links = Array.from(document.querySelectorAll('a'));
                const c = links.find(l => l.textContent.trim() === 'Contacts');
                if (c) c.click();
            }
        """)
        await detail_page.wait_for_timeout(2000)
        await _click_more_details_visible(detail_page)
        html2 = await detail_page.content()
        soup2 = BeautifulSoup(html2, 'lxml')
        _parse_owner_contacts_soup(soup2, lead)

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

    _sync_address_zip_for_ingest(lead)

    log.info(
        f'  jobValue={lead.get("jobValue","?")} | size={lead.get("systemSize","?")} | '
        f'elec={lead.get("electricalServiceUpgrade","?")} | ess={lead.get("advancedEnergyStorage","?")} | '
        f'owner={lead.get("homeownerFirstName","")} {lead.get("homeownerLastName","")}'
    )


def _set_defaults(lead):
    for field in ['jobValue', 'subType', 'occupancyType', 'numberOfPanels',
                  'licensedProfessional', 'systemSize', 'projectDescription',
                  'ownerOnApplication', 'homeownerEmail', 'homeownerPhone',
                  'ownerMailingAddress', 'electricalServiceUpgrade',
                  'advancedEnergyStorage', 'crossStreet', 'descriptionOfWork',
                  'numberOfBuildings', 'housingUnits', 'address']:
        lead.setdefault(field, '')


def scrape_accela(city_key: str, start_date: str, end_date: str):
    config = CITY_CONFIGS.get(city_key)
    if not config:
        raise ValueError(f'Unknown city: {city_key}. Available: {list(CITY_CONFIGS.keys())}')
    return asyncio.run(scrape_accela_async(config, start_date, end_date))
