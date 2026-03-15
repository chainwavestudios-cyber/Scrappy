import asyncio
import logging
import os
import csv
import io
from playwright.async_api import async_playwright
from bs4 import BeautifulSoup
from urllib.parse import urljoin

logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)

BASE_URL = 'https://aca-prod.accela.com/CHULAVISTA'
VIDEO_DIR = '/app/videos'


async def scrape_chula_vista_async(start_date, end_date):
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
            # ----------------------------------------------------------------
            # 1. Load portal
            # ----------------------------------------------------------------
            log.info('Loading Chula Vista portal...')
            await page.goto(
                f'{BASE_URL}/Cap/CapHome.aspx?module=Building',
                wait_until='networkidle'
            )
            await page.wait_for_timeout(3000)

            # ----------------------------------------------------------------
            # 2. Click Search Applications tab
            # ----------------------------------------------------------------
            log.info('Clicking Search Applications...')
            await page.get_by_role('link', name='Search Applications').click()
            await page.wait_for_load_state('networkidle')
            await page.wait_for_timeout(2000)

            # ----------------------------------------------------------------
            # 3. Click Building submenu
            # ----------------------------------------------------------------
            log.info('Clicking Building tab...')
            await page.get_by_role('link', name='Building').first.click()
            await page.wait_for_timeout(2000)

            # ----------------------------------------------------------------
            # 4. Wait for search form and inject dates
            # ----------------------------------------------------------------
            log.info('Waiting for search form...')
            await page.wait_for_selector(
                '[id*="txtGSStartDate"]',
                timeout=15000,
                state='visible'
            )

            log.info(f'Injecting dates: {start_date} to {end_date}')
            await page.evaluate(f"""
                () => {{
                    const s = document.querySelector('[id*="txtGSStartDate"]');
                    const e = document.querySelector('[id*="txtGSEndDate"]');
                    if (s) {{ s.value = '{start_date}'; s.dispatchEvent(new Event('change')); s.dispatchEvent(new Event('blur')); }}
                    if (e) {{ e.value = '{end_date}'; e.dispatchEvent(new Event('change')); e.dispatchEvent(new Event('blur')); }}
                }}
            """)
            log.info('Dates injected')

            # ----------------------------------------------------------------
            # 5. Select Record Type: Residential Solar Energy
            # ----------------------------------------------------------------
            log.info('Selecting record type...')
            record_type_sel = 'select[id*="ddlGSPermitType"], select[id*="selGSPermitType"], select[id*="ddlSearchType"]'
            await page.wait_for_selector(record_type_sel, timeout=10000)

            # Log options to confirm exact label
            options = await page.evaluate(f"""
                () => {{
                    const sel = document.querySelector('{record_type_sel.split(",")[0]}')
                          || document.querySelector('{record_type_sel.split(",")[1]}')
                          || document.querySelector('{record_type_sel.split(",")[2]}');
                    return sel ? Array.from(sel.options).map(o => o.text) : [];
                }}
            """)
            log.info(f'Record type options: {options}')

            await page.select_option(record_type_sel, label='Residential Solar Energy')
            log.info('Record type selected')
            await page.wait_for_timeout(1000)

            # ----------------------------------------------------------------
            # 6. Click Search
            # ----------------------------------------------------------------
            log.info('Clicking Search...')
            await page.evaluate('() => window.scrollTo(0, document.body.scrollHeight)')
            await page.wait_for_timeout(500)
            await page.click('a[id*="btnSearch"], input[id*="btnSearch"]')
            await page.wait_for_selector('tr.ACA_TabRow_Odd, tr.ACA_TabRow_Even', timeout=60000)
            log.info('Search results loaded')

            # ----------------------------------------------------------------
            # 7. Download CSV — gets ALL records, no pagination needed
            # ----------------------------------------------------------------
            log.info('Downloading CSV...')
            async with page.expect_download(timeout=30000) as download_info:
                await page.click('a[id*="lnkExport"], a[title*="Export"], a:text("Export"), a:text("Download")')
            download = await download_info.value
            csv_path = f'/app/chula_vista_permits.csv'
            await download.save_as(csv_path)
            log.info(f'CSV downloaded to {csv_path}')

            # ----------------------------------------------------------------
            # 8. Parse the downloaded CSV
            # ----------------------------------------------------------------
            leads = []
            with open(csv_path, 'r', encoding='utf-8-sig') as f:
                reader = csv.DictReader(f)
                for row in reader:
                    leads.append({
                        'date':              row.get('Date', '').strip(),
                        'permitNumber':      row.get('Permit #', '').strip(),
                        'permitType':        row.get('Permit Type', '').strip(),
                        'permitDescription': row.get('Permit Description', '').strip(),
                        'projectName':       row.get('Project Name', '').strip(),
                        'status':            row.get('Status', '').strip(),
                        'shortNotes':        row.get('Short Notes', '').strip(),
                    })

            log.info(f'Parsed {len(leads)} permits from CSV')

            # ----------------------------------------------------------------
            # 9. Visit each permit detail page
            # ----------------------------------------------------------------
            for i, lead in enumerate(leads):
                permit_num = lead['permitNumber']
                if not permit_num:
                    continue
                log.info(f'Getting details for {permit_num} ({i+1}/{len(leads)})...')

                detail_page = await context.new_page()
                try:
                    # Navigate directly to permit search by number
                    detail_url = f'{BASE_URL}/Cap/CapHome.aspx?module=Building'
                    await detail_page.goto(detail_url, wait_until='networkidle')
                    await detail_page.wait_for_timeout(2000)

                    # Click Building tab
                    await detail_page.get_by_role('link', name='Building').first.click()
                    await detail_page.wait_for_timeout(2000)

                    # Fill in permit number and search
                    await detail_page.wait_for_selector('[id*="txtGSPermitNumber"], [id*="txtPermitNo"]', timeout=10000)
                    await detail_page.fill('[id*="txtGSPermitNumber"], [id*="txtPermitNo"]', permit_num)
                    await detail_page.click('a[id*="btnSearch"], input[id*="btnSearch"]')
                    await detail_page.wait_for_selector('tr.ACA_TabRow_Odd, tr.ACA_TabRow_Even', timeout=30000)

                    # Click the permit number link
                    await detail_page.click('tr.ACA_TabRow_Odd a, tr.ACA_TabRow_Even a')
                    await detail_page.wait_for_load_state('networkidle')
                    await detail_page.wait_for_timeout(2000)

                    await _extract_detail(detail_page, lead)

                except Exception as e:
                    log.error(f'Detail failed {permit_num}: {e}')
                    _set_detail_defaults(lead)
                finally:
                    await detail_page.close()

            return leads

        finally:
            await context.close()
            await browser.close()
            videos = os.listdir(VIDEO_DIR) if os.path.exists(VIDEO_DIR) else []
            log.info(f'Videos saved: {videos}')


async def _extract_detail(detail_page, lead):
    """Extract all detail fields from a permit page."""

    # Click More Details
    await detail_page.evaluate("""
        () => {
            const links = Array.from(document.querySelectorAll('a'));
            const more = links.find(l => l.textContent.includes('More Details'));
            if (more) more.click();
        }
    """)
    await detail_page.wait_for_timeout(1500)

    # Click Additional Information
    await detail_page.evaluate("""
        () => {
            const links = Array.from(document.querySelectorAll('a, span'));
            const ai = links.find(l => l.textContent.trim() === 'Additional Information');
            if (ai) ai.click();
        }
    """)
    await detail_page.wait_for_timeout(1500)

    # Click Application Details / Application Information
    await detail_page.evaluate("""
        () => {
            const links = Array.from(document.querySelectorAll('a, span'));
            const ad = links.find(l =>
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
        """Find a label and return the value next to it."""
        for el in soup.find_all(['span', 'td', 'div', 'label', 'th']):
            text = el.get_text(strip=True)
            if text.lower().rstrip(':') == label.lower().rstrip(':'):
                # Try next sibling
                nxt = el.find_next_sibling()
                if nxt and nxt.get_text(strip=True):
                    return nxt.get_text(strip=True)
                # Try parent's next sibling
                parent = el.find_parent()
                if parent:
                    nxt2 = parent.find_next_sibling()
                    if nxt2 and nxt2.get_text(strip=True):
                        return nxt2.get_text(separator=' ', strip=True)
        return 'N/A'

    def get_block(label):
        """Get multi-line block after a label (for addresses/names)."""
        for el in soup.find_all(['span', 'td', 'div', 'th']):
            if label.lower() in el.get_text().lower():
                parent = el.find_parent(['tr', 'div', 'section'])
                if parent:
                    nxt = parent.find_next_sibling()
                    if nxt:
                        return nxt.get_text(separator=' ', strip=True)
        return 'N/A'

    # Work location
    lead['workLocation'] = get_block('Work Location')

    # Applicant
    lead['applicantName']  = get_block('Applicant')
    lead['applicantPhone'] = get_field('Phone')
    lead['applicantEmail'] = get_field('Email') if get_field('Email') != 'N/A' else 'N/A'

    # Licensed Professional
    lead['licensedProfessional'] = get_block('Licensed Professional')

    # Project
    lead['projectDescription'] = get_field('Project Description')
    lead['jobValue']            = get_field('Job Value($)')

    # Application Information
    lead['occupancyType']  = get_field('What is the occupancy type?')
    lead['subType']        = get_field('Sub Type')
    lead['numberOfPanels'] = get_field('Number of Panels')

    # GIS
    lead['zone']          = get_field('Zone')
    lead['historicSite']  = get_field('Historic Site')
    lead['climateZone']   = get_field('Climate Zone')
    lead['floodPlain']    = get_field('Flood Plain')
    lead['inspectorArea'] = get_field('Inspector Area')

    log.info(f'  panels={lead["numberOfPanels"]} | subType={lead["subType"]} | zone={lead["zone"]}')


def _set_detail_defaults(lead):
    for field in ['workLocation', 'applicantName', 'applicantPhone', 'applicantEmail',
                  'licensedProfessional', 'projectDescription', 'jobValue',
                  'occupancyType', 'subType', 'numberOfPanels',
                  'zone', 'historicSite', 'climateZone', 'floodPlain', 'inspectorArea']:
        lead.setdefault(field, 'N/A')


def scrape_chula_vista(start_date, end_date):
    return asyncio.run(scrape_chula_vista_async(start_date, end_date))
