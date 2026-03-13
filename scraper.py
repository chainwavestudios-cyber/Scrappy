import asyncio
import logging
from playwright.async_api import async_playwright
from bs4 import BeautifulSoup
from urllib.parse import urljoin

logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)

BASE_URL = 'https://publicservices.sandiegocounty.gov/CitizenAccess'
TARGET_NOTE = '8002 - REN - Solar Photovoltaic Roof Mount Residential - Online'


async def scrape_permits_async(start_date, end_date):
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context()
        page = await context.new_page()

        try:
            # ----------------------------------------------------------------
            # 1. Load homepage
            # ----------------------------------------------------------------
            log.info('Loading homepage...')
            await page.goto(f'{BASE_URL}/Default.aspx', wait_until='networkidle')
            await page.wait_for_timeout(2000)

            # ----------------------------------------------------------------
            # 2. Click PDS tab — search form loads by default
            # ----------------------------------------------------------------
            log.info('Clicking PDS tab...')
            await page.evaluate("""
                () => {
                    const links = Array.from(document.querySelectorAll('a'));
                    const pds = links.find(l => l.textContent.trim() === 'PDS');
                    if (pds) pds.click();
                }
            """)
            await page.wait_for_load_state('networkidle')
            await page.wait_for_timeout(3000)

            # ----------------------------------------------------------------
            # 3. Find Welcome.aspx frame and wait for form to fully render
            # ----------------------------------------------------------------
            frame = next(
                (f for f in page.frames if 'Welcome.aspx' in f.url),
                None
            )
            if not frame:
                log.warning('Welcome.aspx frame not found, using main page')
                frame = page
            log.info(f'Using frame: {frame.url}')

            # Wait up to 30s for the record type dropdown to appear in the frame
            log.info('Waiting for search form to render in frame...')
            try:
                await frame.wait_for_selector(
                    '#ctl00_PlaceHolderMain_generalSearchForm_ddlGSPermitType',
                    timeout=30000
                )
                log.info('Search form ready')
            except Exception:
                # Log what IS in the frame for debugging
                html_snapshot = await frame.content()
                log.info(f'Frame HTML snippet: {html_snapshot[:2000]}')
                raise

            # Log all record type options to confirm exact label
            rt_options = await frame.evaluate("""
                () => Array.from(
                    document.querySelector('#ctl00_PlaceHolderMain_generalSearchForm_ddlGSPermitType').options
                ).map(o => o.text)
            """)
            log.info(f'Record type options: {rt_options}')

            # ----------------------------------------------------------------
            # 4. Inject dates via JS (bypasses datepicker widgets)
            # ----------------------------------------------------------------
            log.info(f'Injecting dates: {start_date} to {end_date}')
            await frame.evaluate(f"""
                () => {{
                    const s = document.querySelector('[id*="txtGSStartDate"]');
                    const e = document.querySelector('[id*="txtGSEndDate"]');
                    if (s) {{
                        s.value = '{start_date}';
                        s.dispatchEvent(new Event('change'));
                        s.dispatchEvent(new Event('blur'));
                    }} else {{ console.log('start date field not found'); }}
                    if (e) {{
                        e.value = '{end_date}';
                        e.dispatchEvent(new Event('change'));
                        e.dispatchEvent(new Event('blur'));
                    }} else {{ console.log('end date field not found'); }}
                }}
            """)
            log.info('Dates injected')

            # ----------------------------------------------------------------
            # 5. Select Record Type
            # ----------------------------------------------------------------
            log.info('Selecting record type...')
            await frame.select_option(
                '#ctl00_PlaceHolderMain_generalSearchForm_ddlGSPermitType',
                label='Residential Alteration or Addition - Plan Check-Permit'
            )
            log.info('Record type selected')
            await frame.wait_for_timeout(1000)

            # ----------------------------------------------------------------
            # 6. Enter Project Name = "OTC"
            # ----------------------------------------------------------------
            log.info('Entering project name: OTC')
            await frame.fill('[id*="txtGSProjectName"]', 'OTC')

            # ----------------------------------------------------------------
            # 7. Click Search
            # ----------------------------------------------------------------
            log.info('Clicking search...')
            await frame.evaluate('() => window.scrollTo(0, document.body.scrollHeight)')
            await frame.wait_for_timeout(500)
            await frame.click('a[id*="btnSearch"], input[id*="btnSearch"]')
            await frame.wait_for_selector('tr.gdvPermitList_Row', timeout=60000)
            log.info('Search results loaded')

            # ----------------------------------------------------------------
            # 8. Collect all matching rows across all pages
            # ----------------------------------------------------------------
            all_leads = []
            page_num = 1

            while True:
                log.info(f'Scraping results page {page_num}...')
                html = await frame.content()
                soup = BeautifulSoup(html, 'lxml')
                rows = soup.select('tr.gdvPermitList_Row')
                log.info(f'  Found {len(rows)} rows on page {page_num}')

                for row in rows:
                    cells = row.find_all('td')
                    if len(cells) < 7:
                        continue

                    short_notes = cells[8].get_text(strip=True) if len(cells) > 8 else ''

                    if TARGET_NOTE not in short_notes:
                        continue

                    link = cells[1].find('a')
                    href = link['href'] if link else None
                    lead = {
                        'recordId':     cells[1].get_text(strip=True),
                        'openedDate':   cells[2].get_text(strip=True),
                        'recordType':   cells[3].get_text(strip=True),
                        'projectName':  cells[4].get_text(strip=True),
                        'address':      cells[5].get_text(strip=True),
                        'recordStatus': cells[6].get_text(strip=True),
                        'action':       cells[7].get_text(strip=True) if len(cells) > 7 else '',
                        'shortNotes':   short_notes,
                        'detailHref':   href,
                    }
                    all_leads.append(lead)
                    log.info(f'  Matched: {lead["recordId"]} | {lead["address"]}')

                next_link = soup.find('a', string=str(page_num + 1))
                if not next_link:
                    log.info('No more pages')
                    break

                log.info(f'Going to page {page_num + 1}...')
                await frame.click(f'a:text("{page_num + 1}")')
                await frame.wait_for_selector('tr.gdvPermitList_Row', timeout=30000)
                await frame.wait_for_timeout(1000)
                page_num += 1

            log.info(f'Total matching leads: {len(all_leads)}')

            # ----------------------------------------------------------------
            # 9. Visit each record detail page
            # ----------------------------------------------------------------
            for i, lead in enumerate(all_leads):
                if not lead['detailHref']:
                    continue
                log.info(f'Getting details for {lead["recordId"]} ({i+1}/{len(all_leads)})...')

                detail_page = await context.new_page()
                try:
                    detail_url = urljoin(BASE_URL + '/', lead['detailHref'].lstrip('/'))
                    await detail_page.goto(detail_url, wait_until='networkidle')
                    await detail_page.wait_for_timeout(1500)

                    detail_html = await detail_page.content()
                    detail_soup = BeautifulSoup(detail_html, 'lxml')

                    # -- Record ID and Status --
                    record_id_el = detail_soup.find(string=lambda t: t and 'Record ID' in t)
                    lead['detailRecordId'] = record_id_el.strip() if record_id_el else lead['recordId']

                    status_el = detail_soup.find(string=lambda t: t and 'Record Status' in t)
                    if status_el:
                        parent = status_el.find_parent()
                        lead['detailRecordStatus'] = parent.get_text(strip=True).replace('Record Status:', '').strip()
                    else:
                        lead['detailRecordStatus'] = 'N/A'

                    # -- Licensed Professional --
                    lp_section = detail_soup.find(string=lambda t: t and 'Licensed Professional' in t)
                    if lp_section:
                        parent = lp_section.find_parent()
                        block = parent.find_next_sibling()
                        lead['licensedProfessional'] = block.get_text(separator='\n', strip=True) if block else 'N/A'
                    else:
                        lead['licensedProfessional'] = 'N/A'

                    # -- Click "More Details" arrow --
                    await detail_page.evaluate("""
                        () => {
                            const links = Array.from(document.querySelectorAll('a'));
                            const more = links.find(l => l.textContent.includes('More Details'));
                            if (more) more.click();
                        }
                    """)
                    await detail_page.wait_for_timeout(1500)

                    # -- Click "+" next to Application Information --
                    await detail_page.evaluate("""
                        () => {
                            const els = Array.from(document.querySelectorAll('a, span, div'));
                            const appInfo = els.find(l => l.textContent.trim() === 'Application Information');
                            if (appInfo) {
                                const parent = appInfo.closest('tr') || appInfo.parentElement;
                                const btn = parent ? parent.querySelector('a, img, span.expand') : null;
                                if (btn) btn.click();
                                else appInfo.click();
                            }
                        }
                    """)
                    await detail_page.wait_for_timeout(2000)

                    detail_html2 = await detail_page.content()
                    detail_soup2 = BeautifulSoup(detail_html2, 'lxml')

                    def get_field(soup_obj, label):
                        for el in soup_obj.find_all(['span', 'td', 'div', 'label']):
                            if label.lower() in el.get_text().lower():
                                nxt = el.find_next_sibling()
                                if nxt:
                                    return nxt.get_text(strip=True)
                                parent = el.find_parent()
                                if parent:
                                    nxt2 = parent.find_next_sibling()
                                    if nxt2:
                                        return nxt2.get_text(strip=True)
                        return 'N/A'

                    lead['primaryScopeCode'] = get_field(detail_soup2, 'Primary Scope Code')
                    lead['kwSystemSize']      = get_field(detail_soup2, 'Rounded Kilowatts Total System Size')
                    lead['electricalUpgrade'] = get_field(detail_soup2, 'Electrical Service Upgrade')
                    lead['energyStorage']     = get_field(detail_soup2, 'Advanced Energy Storage System')
                    lead['crossStreet']       = get_field(detail_soup2, 'Cross Street')
                    lead['use']               = get_field(detail_soup2, 'Use')

                    log.info(f'  kW={lead["kwSystemSize"]} | upgrade={lead["electricalUpgrade"]} | storage={lead["energyStorage"]}')

                except Exception as e:
                    log.error(f'Detail failed {lead["recordId"]}: {e}')
                    for field in ['detailRecordId', 'detailRecordStatus', 'licensedProfessional',
                                  'primaryScopeCode', 'kwSystemSize', 'electricalUpgrade',
                                  'energyStorage', 'crossStreet', 'use']:
                        lead.setdefault(field, 'N/A')
                finally:
                    await detail_page.close()

            return all_leads

        finally:
            await browser.close()


def scrape_permits(start_date, end_date):
    return asyncio.run(scrape_permits_async(start_date, end_date))
