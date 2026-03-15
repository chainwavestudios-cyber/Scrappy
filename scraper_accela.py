"""
Generic Accela scraper — works for any standard Accela portal.
Each city passes its own config dict.
"""
import asyncio
import logging
import os
import csv
from playwright.async_api import async_playwright
from bs4 import BeautifulSoup

logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)

VIDEO_DIR = '/app/videos'


# ---------------------------------------------------------------------------
# City configs — add new Accela cities here
# ---------------------------------------------------------------------------

CITY_CONFIGS = {
    'sacramento': {
        'name':        'Sacramento',
        'base_url':    'https://aca-prod.accela.com/SACRAMENTO',
        'module':      'Building',
        'permit_type': 'Solar Photovoltaic',   # update after recon
        'use_project_name': 'OTC',             # Sacramento uses project name filter
        'source':      'sacramento_accela',
    },
    'oakland': {
        'name':        'Oakland',
        'base_url':    'https://aca-prod.accela.com/OAKLAND',
        'module':      'Building',
        'permit_type': None,                   # no filter, date range only
        'use_project_name': None,
        'source':      'oakland_accela',
    },
    'anaheim': {
        'name':        'Anaheim',
        'base_url':    'https://aca-prod.accela.com/ANAHEIM',
        'module':      'Building',
        'permit_type': None,
        'use_project_name': None,
        'source':      'anaheim_accela',
    },
    'santa_ana': {
        'name':        'Santa Ana',
        'base_url':    'https://aca-prod.accela.com/SANTAANA',
        'module':      'Building',
        'permit_type': None,
        'use_project_name': None,
        'source':      'santa_ana_accela',
    },
    'chula_vista': {
        'name':        'Chula Vista',
        'base_url':    'https://aca-prod.accela.com/CHULAVISTA',
        'module':      'Building',
        'permit_type': 'Residential Solar Energy',
        'use_project_name': None,
        'source':      'chula_vista_accela',
    },
    'fontana': {
        'name':        'Fontana',
        'base_url':    'https://aca-prod.accela.com/FONTANA',
        'module':      'Building',
        'permit_type': None,
        'use_project_name': None,
        'source':      'fontana_accela',
    },
    'palmdale': {
        'name':        'Palmdale',
        'base_url':    'https://aca-prod.accela.com/PALMDALE',
        'module':      'Building',
        'permit_type': None,
        'use_project_name': None,
        'source':      'palmdale_accela',
    },
    'concord': {
        'name':        'Concord',
        'base_url':    'https://aca-prod.accela.com/CONCORD',
        'module':      'Building',
        'permit_type': None,
        'use_project_name': None,
        'source':      'concord_accela',
    },
    'berkeley': {
        'name':        'Berkeley',
        'base_url':    'https://aca-prod.accela.com/BERKELEY',
        'module':      'Building',
        'permit_type': None,
        'use_project_name': None,
        'source':      'berkeley_accela',
    },
    'downey': {
        'name':        'Downey',
        'base_url':    'https://aca-prod.accela.com/DOWNEY',
        'module':      'Building',
        'permit_type': None,
        'use_project_name': None,
        'source':      'downey_accela',
    },
}


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
        os.makedirs(VIDEO_DIR, exist_ok=True)
        context = await browser.new_context(
            record_video_dir=VIDEO_DIR,
            record_video_size={'width': 1280, 'height': 800},
            viewport={'width': 1280, 'height': 800},
            accept_downloads=True,
        )
        page = await context.new_page()

        try:
            # 1. Load portal
            log.info(f'[{city_name}] Loading portal...')
            await page.goto(
                f'{base_url}/Cap/CapHome.aspx?module={module}',
                wait_until='networkidle'
            )
            await page.wait_for_timeout(3000)

            # 2. Click Search Applications / Search Records / Building Records
            log.info(f'[{city_name}] Finding search entry...')
            for label in ['Search Applications', 'Search Records', 'Building Records', 'Search Permits']:
                try:
                    loc = page.get_by_role('link', name=label)
                    if await loc.count() > 0:
                        await loc.first.click()
                        await page.wait_for_load_state('networkidle')
                        await page.wait_for_timeout(2000)
                        log.info(f'[{city_name}] Clicked: {label}')
                        break
                except Exception:
                    continue

            # 3. Click Building tab
            try:
                await page.get_by_role('link', name='Building').first.click()
                await page.wait_for_timeout(2000)
                log.info(f'[{city_name}] Clicked Building tab')
            except Exception:
                log.warning(f'[{city_name}] No Building tab found')

            # 4. Wait for search form
            log.info(f'[{city_name}] Waiting for search form...')
            await page.wait_for_selector('[id*="txtGSStartDate"]', timeout=20000, state='visible')

            # 5. Inject dates
            log.info(f'[{city_name}] Injecting dates: {start_date} to {end_date}')
            await page.evaluate(f"""
                () => {{
                    const s = document.querySelector('[id*="txtGSStartDate"]');
                    const e = document.querySelector('[id*="txtGSEndDate"]');
                    if (s) {{ s.value = '{start_date}'; s.dispatchEvent(new Event('change')); s.dispatchEvent(new Event('blur')); }}
                    if (e) {{ e.value = '{end_date}'; e.dispatchEvent(new Event('change')); e.dispatchEvent(new Event('blur')); }}
                }}
            """)

            # 6. Select permit type if configured
            if config.get('permit_type'):
                log.info(f'[{city_name}] Selecting permit type: {config["permit_type"]}')
                try:
                    # Find the first visible select on the page
                    type_sel = await page.evaluate("""
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
                            // fallback: first visible select
                            const selects = Array.from(document.querySelectorAll('select'));
                            const visible = selects.find(s => s.offsetParent !== null);
                            return visible ? '#' + visible.id : null;
                        }
                    """)
                    log.info(f'[{city_name}] Using type selector: {type_sel}')

                    if type_sel:
                        await page.wait_for_selector(type_sel, timeout=8000)
                        options = await page.evaluate(f"""
                            () => Array.from(
                                document.querySelector('{type_sel}').options
                            ).map(o => o.text)
                        """)
                        log.info(f'[{city_name}] Permit type options: {options}')
                        # Use JS to set value to avoid timing issues with postback
                        await page.evaluate(f"""
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
                        # Wait for postback to complete
                        await page.wait_for_load_state('networkidle')
                        await page.wait_for_timeout(2000)
                        log.info(f'[{city_name}] Permit type selected')
                except Exception as e:
                    log.warning(f'[{city_name}] Could not select permit type: {e}')

            # 7. Enter project name if configured
            if config.get('use_project_name'):
                log.info(f'[{city_name}] Entering project name: {config["use_project_name"]}')
                try:
                    await page.fill('[id*="txtGSProjectName"]', config['use_project_name'])
                except Exception:
                    pass

            # 8. Click Search
            log.info(f'[{city_name}] Clicking Search...')
            await page.evaluate('() => window.scrollTo(0, document.body.scrollHeight)')
            await page.wait_for_timeout(500)

            # Debug — log all buttons/links with IDs
            btns = await page.evaluate("""
                () => Array.from(document.querySelectorAll('a, input[type=submit], button'))
                    .filter(el => el.id || el.value || el.textContent.trim())
                    .map(el => ({
                        tag: el.tagName,
                        id: el.id,
                        value: el.value || '',
                        text: el.textContent.trim().substring(0, 30)
                    }))
            """)
            log.info(f'[{city_name}] Buttons/links on page: {btns}')

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
                    loc = page.locator(btn_sel)
                    if await loc.count() > 0:
                        await loc.first.click()
                        clicked = True
                        log.info(f'[{city_name}] Clicked: {btn_sel}')
                        break
                except Exception:
                    continue
            if not clicked:
                raise Exception('Could not find search button')
            await page.wait_for_selector(
                'tr.ACA_TabRow_Odd, tr.ACA_TabRow_Even, tr.gdvPermitList_Row',
                timeout=60000
            )
            log.info(f'[{city_name}] Results loaded')

            # 9. Try CSV download first, fall back to scraping rows
            leads = []
            try:
                log.info(f'[{city_name}] Attempting CSV download...')
                async with page.expect_download(timeout=15000) as dl_info:
                    await page.click(
                        'a[id*="lnkExport"], a[title*="Export"], '
                        'a[title*="Download"], a:text("Export"), a:text("Download")'
                    )
                download = await dl_info.value
                csv_path = f'/app/{source}_permits.csv'
                await download.save_as(csv_path)
                log.info(f'[{city_name}] CSV downloaded: {csv_path}')

                with open(csv_path, 'r', encoding='utf-8-sig') as f:
                    reader = csv.DictReader(f)
                    for row in reader:
                        leads.append(_parse_csv_row(row, source))
                log.info(f'[{city_name}] Parsed {len(leads)} permits from CSV')

            except Exception as e:
                log.warning(f'[{city_name}] Download failed, scraping rows instead: {e}')
                leads = await _scrape_rows(page, source)

            # 10. Get details for each permit
            for i, lead in enumerate(leads):
                permit_num = lead.get('permitNumber') or lead.get('recordId')
                if not permit_num:
                    continue
                log.info(f'[{city_name}] Details {permit_num} ({i+1}/{len(leads)})...')
                detail_page = await context.new_page()
                try:
                    await _get_permit_details(detail_page, base_url, module, permit_num, lead)
                except Exception as e:
                    log.error(f'[{city_name}] Detail failed {permit_num}: {e}')
                    _set_defaults(lead)
                finally:
                    await detail_page.close()

            return leads

        finally:
            await context.close()
            await browser.close()
            videos = os.listdir(VIDEO_DIR) if os.path.exists(VIDEO_DIR) else []
            log.info(f'[{city_name}] Videos saved: {videos}')


def _parse_csv_row(row, source):
    """Normalize CSV row — handles different column name variants."""
    return {
        'source':            source,
        'date':              row.get('Date', '').strip(),
        'permitNumber':      (row.get('Permit #') or row.get('Record ID') or '').strip(),
        'permitType':        (row.get('Permit Type') or row.get('Record Type') or '').strip(),
        'permitDescription': (row.get('Permit Description') or row.get('Project Name') or '').strip(),
        'projectName':       row.get('Project Name', '').strip(),
        'status':            (row.get('Status') or row.get('Record Status') or '').strip(),
        'shortNotes':        row.get('Short Notes', '').strip(),
    }


async def _scrape_rows(page, source):
    """Fallback: scrape results table row by row across all pages."""
    leads = []
    page_num = 1
    while True:
        html = await page.content()
        soup = BeautifulSoup(html, 'lxml')
        rows = soup.select('tr.ACA_TabRow_Odd, tr.ACA_TabRow_Even, tr.gdvPermitList_Row')
        log.info(f'  Scraping page {page_num}: {len(rows)} rows')

        for row in rows:
            cells = row.find_all('td')
            if len(cells) < 3:
                continue
            link = row.find('a')
            href = link['href'] if link else None
            leads.append({
                'source':       source,
                'date':         cells[0].get_text(strip=True) if len(cells) > 0 else '',
                'permitNumber': cells[1].get_text(strip=True) if len(cells) > 1 else '',
                'permitType':   cells[2].get_text(strip=True) if len(cells) > 2 else '',
                'status':       cells[4].get_text(strip=True) if len(cells) > 4 else '',
                'shortNotes':   cells[6].get_text(strip=True) if len(cells) > 6 else '',
                'detailHref':   href,
            })

        next_link = soup.find('a', string=str(page_num + 1))
        if not next_link:
            break
        await page.click(f'a:text("{page_num + 1}")')
        await page.wait_for_selector(
            'tr.ACA_TabRow_Odd, tr.ACA_TabRow_Even, tr.gdvPermitList_Row',
            timeout=30000
        )
        page_num += 1

    return leads


async def _get_permit_details(detail_page, base_url, module, permit_num, lead):
    """Navigate to permit detail and extract all fields."""
    await detail_page.goto(
        f'{base_url}/Cap/CapHome.aspx?module={module}',
        wait_until='networkidle'
    )
    await detail_page.wait_for_timeout(2000)

    # Click Building tab
    try:
        await detail_page.get_by_role('link', name='Building').first.click()
        await detail_page.wait_for_timeout(2000)
    except Exception:
        pass

    # Search by permit number
    await detail_page.wait_for_selector(
        '[id*="txtGSPermitNumber"], [id*="txtPermitNo"], [id*="txtGSCapNumber"]',
        timeout=10000
    )
    await detail_page.fill(
        '[id*="txtGSPermitNumber"], [id*="txtPermitNo"], [id*="txtGSCapNumber"]',
        permit_num
    )
    await detail_page.click('a[id*="btnSearch"], input[id*="btnSearch"]')
    await detail_page.wait_for_selector(
        'tr.ACA_TabRow_Odd, tr.ACA_TabRow_Even',
        timeout=30000
    )

    # Click the permit link
    await detail_page.click('tr.ACA_TabRow_Odd a, tr.ACA_TabRow_Even a')
    await detail_page.wait_for_load_state('networkidle')
    await detail_page.wait_for_timeout(2000)

    # More Details
    await detail_page.evaluate("""
        () => {
            const links = Array.from(document.querySelectorAll('a'));
            const more = links.find(l => l.textContent.includes('More Details'));
            if (more) more.click();
        }
    """)
    await detail_page.wait_for_timeout(1500)

    # Additional Information
    await detail_page.evaluate("""
        () => {
            const els = Array.from(document.querySelectorAll('a, span'));
            const ai = els.find(l => l.textContent.trim() === 'Additional Information');
            if (ai) ai.click();
        }
    """)
    await detail_page.wait_for_timeout(1500)

    # Application Details / Application Information
    await detail_page.evaluate("""
        () => {
            const els = Array.from(document.querySelectorAll('a, span'));
            const ad = els.find(l =>
                l.textContent.trim() === 'Application Details' ||
                l.textContent.trim() === 'Application Information'
            );
            if (ad) ad.click();
        }
    """)
    await detail_page.wait_for_timeout(2000)

    html = await detail_page.content()
    soup = BeautifulSoup(html, 'lxml')

    def get_field(label):
        for el in soup.find_all(['span', 'td', 'div', 'label', 'th']):
            if el.get_text(strip=True).lower().rstrip(':') == label.lower().rstrip(':'):
                nxt = el.find_next_sibling()
                if nxt and nxt.get_text(strip=True):
                    return nxt.get_text(strip=True)
                parent = el.find_parent()
                if parent:
                    nxt2 = parent.find_next_sibling()
                    if nxt2 and nxt2.get_text(strip=True):
                        return nxt2.get_text(separator=' ', strip=True)
        return 'N/A'

    def get_block(label):
        for el in soup.find_all(['span', 'td', 'div', 'th']):
            if label.lower() in el.get_text().lower():
                parent = el.find_parent(['tr', 'div', 'section', 'table'])
                if parent:
                    nxt = parent.find_next_sibling()
                    if nxt:
                        return nxt.get_text(separator=' ', strip=True)
        return 'N/A'

    lead['workLocation']        = get_block('Work Location')
    lead['applicantName']       = get_block('Applicant')
    lead['applicantPhone']      = get_field('Phone')
    lead['licensedProfessional']= get_block('Licensed Professional')
    lead['projectDescription']  = get_field('Project Description')
    lead['jobValue']            = get_field('Job Value($)')
    lead['occupancyType']       = get_field('What is the occupancy type?')
    lead['subType']             = get_field('Sub Type')
    lead['numberOfPanels']      = get_field('Number of Panels')
    lead['zone']                = get_field('Zone')
    lead['climateZone']         = get_field('Climate Zone')
    lead['floodPlain']          = get_field('Flood Plain')
    lead['inspectorArea']       = get_field('Inspector Area')
    # Also try San Diego style fields
    lead['primaryScopeCode']    = get_field('Primary Scope Code')
    lead['kwSystemSize']        = get_field('Rounded Kilowatts Total System Size')
    lead['electricalUpgrade']   = get_field('Electrical Service Upgrade')
    lead['energyStorage']       = get_field('Advanced Energy Storage System')
    lead['crossStreet']         = get_field('Cross Street')

    log.info(f'  panels={lead["numberOfPanels"]} | subType={lead["subType"]} | kW={lead["kwSystemSize"]}')


def _set_defaults(lead):
    for field in ['workLocation', 'applicantName', 'applicantPhone', 'licensedProfessional',
                  'projectDescription', 'jobValue', 'occupancyType', 'subType',
                  'numberOfPanels', 'zone', 'climateZone', 'floodPlain', 'inspectorArea',
                  'primaryScopeCode', 'kwSystemSize', 'electricalUpgrade',
                  'energyStorage', 'crossStreet']:
        lead.setdefault(field, 'N/A')


def scrape_accela(city_key: str, start_date: str, end_date: str):
    """Public entry point — call with city key from CITY_CONFIGS."""
    config = CITY_CONFIGS.get(city_key)
    if not config:
        raise ValueError(f'Unknown city: {city_key}. Available: {list(CITY_CONFIGS.keys())}')
    return asyncio.run(scrape_accela_async(config, start_date, end_date))
