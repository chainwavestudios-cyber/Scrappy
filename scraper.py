import asyncio
import logging
from playwright.async_api import async_playwright
from bs4 import BeautifulSoup
from urllib.parse import urljoin

logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)

BASE_URL = 'https://publicservices.sandiegocounty.gov/CitizenAccess'

async def scrape_permits_async(start_date, end_date):
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context()
        page = await context.new_page()

        try:
            log.info('Loading homepage...')
            await page.goto(f'{BASE_URL}/Default.aspx', wait_until='networkidle')
            await page.wait_for_timeout(2000)

            log.info('Clicking PDS tab...')
            await page.evaluate("""
                () => {
                    const links = Array.from(document.querySelectorAll('a'));
                    const pds = links.find(l => l.textContent.trim() === 'PDS');
                    if (pds) pds.click();
                }
            """)
            await page.wait_for_load_state('networkidle')
            await page.wait_for_timeout(2000)

            log.info('Clicking Search Records...')
            await page.evaluate("""
                () => {
                    const links = Array.from(document.querySelectorAll('a'));
                    const search = links.find(l => l.textContent.trim() === 'Search Records');
                    if (search) search.click();
                }
            """)
            await page.wait_for_load_state('networkidle')
            await page.wait_for_timeout(2000)

            for f in page.frames:
                log.info(f'Frame URL: {f.url}')

            frame = next(
                (f for f in page.frames if 'Welcome.aspx' in f.url),
                None
            )
            if not frame:
                log.warning('Welcome.aspx frame not found, using main page')
                frame = page

            log.info(f'Using frame: {frame.url}')

            log.info(f'Injecting dates: {start_date} to {end_date}')
            await frame.evaluate(f"""
                () => {{
                    const s = document.querySelector('[id*="txtGSStartDate"]');
                    const e = document.querySelector('[id*="txtGSEndDate"]');
                    if (s) {{
                        s.value = '{start_date}';
                        s.dispatchEvent(new Event('change'));
                        s.dispatchEvent(new Event('blur'));
                    }}
                    if (e) {{
                        e.value = '{end_date}';
                        e.dispatchEvent(new Event('change'));
                        e.dispatchEvent(new Event('blur'));
                    }}
                }}
            """)
            log.info('Dates injected')

            log.info('Expanding additional criteria...')
            await frame.evaluate("""
                () => {
                    const links = Array.from(document.querySelectorAll('a'));
                    const expand = links.find(l => l.textContent.includes('Search Additional Criteria'));
                    if (expand) expand.click();
                }
            """)

            # Wait for Primary Scope Code dropdown using exact ID from inspection
            await frame.wait_for_selector(
                '#ctl00_PlaceHolderMain_asiGSForm_COSD_ddl_30_0',
                timeout=15000
            )

            # Log all available options to confirm exact label text
            options = await frame.evaluate("""
                () => Array.from(
                    document.querySelector('#ctl00_PlaceHolderMain_asiGSForm_COSD_ddl_30_0').options
                ).map(o => o.text)
            """)
            log.info(f'Primary Scope Code options: {options}')

            log.info('Selecting solar scope code...')
            await frame.select_option(
                '#ctl00_PlaceHolderMain_asiGSForm_COSD_ddl_30_0',
                label='8002-REN-Solar Photovoltaic Roof Mount Residential - Online'
            )
            log.info('Solar scope code selected')

            log.info('Scrolling to bottom and clicking search...')
            await frame.evaluate('() => window.scrollTo(0, document.body.scrollHeight)')
            await frame.wait_for_timeout(1000)
            await frame.click('a[id*="btnSearch"]')
            await frame.wait_for_selector('tr.gdvPermitList_Row', timeout=60000)
            log.info('Results loaded')

            html = await frame.content()
            soup = BeautifulSoup(html, 'lxml')
            rows = soup.select('tr.gdvPermitList_Row')
            log.info(f'Found {len(rows)} records')

            leads = []
            for row in rows:
                cells = row.find_all('td')
                if len(cells) < 7:
                    continue
                link = row.find('a')
                href = link['href'] if link else None
                lead = {
                    'recordId': cells[1].get_text(strip=True),
                    'openedDate': cells[2].get_text(strip=True),
                    'recordType': cells[3].get_text(strip=True),
                    'projectName': cells[4].get_text(strip=True),
                    'address': cells[5].get_text(strip=True),
                    'status': cells[6].get_text(strip=True),
                    'action': cells[7].get_text(strip=True) if len(cells) > 7 else '',
                    'shortNotes': cells[8].get_text(strip=True) if len(cells) > 8 else '',
                    'detailHref': href,
                }
                leads.append(lead)

            for i, lead in enumerate(leads):
                if not lead['detailHref']:
                    continue
                log.info(f'Getting details {lead["recordId"]} ({i+1}/{len(leads)})...')

                detail_page = await context.new_page()
                try:
                    # urljoin prevents double-path URLs
                    detail_url = urljoin(BASE_URL + '/', lead['detailHref'].lstrip('/'))
                    await detail_page.goto(detail_url, wait_until='networkidle')

                    await detail_page.evaluate("""
                        () => {
                            const links = Array.from(document.querySelectorAll('a'));
                            const more = links.find(l => l.textContent.includes('More Details'));
                            if (more) more.click();
                        }
                    """)
                    await detail_page.wait_for_timeout(2000)

                    await detail_page.evaluate("""
                        () => {
                            const links = Array.from(document.querySelectorAll('a'));
                            const appInfo = links.find(l => l.textContent.includes('Application Information'));
                            if (appInfo) appInfo.click();
                        }
                    """)
                    await detail_page.wait_for_selector('div.appInfoTable', timeout=15000)

                    detail_html = await detail_page.content()
                    detail_soup = BeautifulSoup(detail_html, 'lxml')

                    def get_field(label):
                        for span in detail_soup.find_all('span'):
                            if label.lower() in span.get_text().lower():
                                parent = span.find_parent()
                                if parent:
                                    next_sib = parent.find_next_sibling()
                                    if next_sib:
                                        return next_sib.get_text(strip=True)
                        return 'N/A'

                    lead['primaryScopeCode'] = get_field('Primary Scope Code')
                    lead['kwSystemSize'] = get_field('Rounded Kilowatts Total System Size')
                    lead['electricalUpgrade'] = get_field('Electrical Service Upgrade')
                    lead['energyStorage'] = get_field('Advanced Energy Storage System')

                except Exception as e:
                    log.error(f'Detail failed {lead["recordId"]}: {e}')
                    lead['primaryScopeCode'] = 'N/A'
                    lead['kwSystemSize'] = 'N/A'
                    lead['electricalUpgrade'] = 'N/A'
                    lead['energyStorage'] = 'N/A'

                finally:
                    # Always close detail page even if it times out
                    await detail_page.close()

            return leads

        finally:
            await browser.close()

def scrape_permits(start_date, end_date):
    return asyncio.run(scrape_permits_async(start_date, end_date))
