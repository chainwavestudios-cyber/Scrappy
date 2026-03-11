import requests
from bs4 import BeautifulSoup
import logging

logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)

BASE_URL = 'https://publicservices.sandiegocounty.gov/CitizenAccess'

def get_viewstate(soup):
    return {
        '__VIEWSTATE': soup.find('input', {'id': '__VIEWSTATE'})['value'] if soup.find('input', {'id': '__VIEWSTATE'}) else '',
        '__VIEWSTATEGENERATOR': soup.find('input', {'id': '__VIEWSTATEGENERATOR'})['value'] if soup.find('input', {'id': '__VIEWSTATEGENERATOR'}) else '',
        '__EVENTVALIDATION': soup.find('input', {'id': '__EVENTVALIDATION'})['value'] if soup.find('input', {'id': '__EVENTVALIDATION'}) else '',
        '__EVENTTARGET': '',
        '__EVENTARGUMENT': '',
        'ACA_CS_FIELD': soup.find('input', {'id': 'ACA_CS_FIELD'})['value'] if soup.find('input', {'id': 'ACA_CS_FIELD'}) else '',
    }

def scrape_permits(start_date, end_date):
    session = requests.Session()
    session.headers.update({
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
        'Accept-Language': 'en-US,en;q=0.5',
    })

    # Step 1 — Load homepage
    log.info('Loading homepage...')
    r = session.get(f'{BASE_URL}/Default.aspx')
    soup = BeautifulSoup(r.text, 'lxml')
    viewstate = get_viewstate(soup)
    log.info(f'Homepage status: {r.status_code}, title: {soup.title.string if soup.title else "none"}')

    # Step 2 — Navigate to PDS tab
    log.info('Navigating to PDS...')
    r = session.post(f'{BASE_URL}/Default.aspx', data={
        **viewstate,
        '__EVENTTARGET': 'ctl00$HeaderNavigation$hypModule_PDS',
    })
    soup = BeautifulSoup(r.text, 'lxml')
    viewstate = get_viewstate(soup)
    log.info(f'PDS tab status: {r.status_code}, title: {soup.title.string if soup.title else "none"}')

    # Step 3 — Navigate to Search Records
    log.info('Going to Search Records...')
    r = session.get(f'{BASE_URL}/Cap/CapHome.aspx?module=PDS&TabName=PDS')
    soup = BeautifulSoup(r.text, 'lxml')
    viewstate = get_viewstate(soup)
    log.info(f'Search page status: {r.status_code}, title: {soup.title.string if soup.title else "none"}')
    log.info(f'All input IDs: {[i.get("id") for i in soup.find_all("input") if i.get("id")]}')
    log.info(f'All select IDs: {[s.get("id") for s in soup.find_all("select") if s.get("id")]}')

    # Step 4 — Submit search form
    log.info(f'Searching from {start_date} to {end_date}...')
    search_data = {
        **viewstate,
        'ctl00$PlaceHolderMain$generalSearchForm$txtGSStartDate': start_date,
        'ctl00$PlaceHolderMain$generalSearchForm$txtGSEndDate': end_date,
        'ctl00$PlaceHolderMain$generalSearchForm$ddlSecondaryScopeCode1': '8002',
        'ctl00$PlaceHolderMain$btnSearch': 'Search',
    }
    r = session.post(f'{BASE_URL}/Cap/CapHome.aspx?module=PDS&TabName=PDS', data=search_data)
    soup = BeautifulSoup(r.text, 'lxml')

    log.info(f'Search response status: {r.status_code}')
    log.info(f'Search response URL: {r.url}')
    log.info(f'Page title after search: {soup.title.string if soup.title else "no title"}')

    error = soup.select_one('.ErrorMessage, .error, #ctl00_PlaceHolderMain_ErrorMsg')
    if error:
        log.info(f'Error message: {error.get_text(strip=True)}')

    rows = soup.select('tr.gdvPermitList_Row')
    log.info(f'Rows found: {len(rows)}')

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
            'detailUrl': f"{BASE_URL}/{href}" if href else None,
        }
        leads.append(lead)

    # Step 6 — Deep dive each record
    for i, lead in enumerate(leads):
        if not lead['detailUrl']:
            continue

        log.info(f'Getting details for {lead["recordId"]} ({i+1}/{len(leads)})...')
        try:
            r = session.get(lead['detailUrl'])
            soup = BeautifulSoup(r.text, 'lxml')

            def get_field(label):
                spans = soup.find_all('span')
                for span in spans:
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
            log.error(f'Detail fetch failed for {lead["recordId"]}: {e}')
            lead['primaryScopeCode'] = 'N/A'
            lead['kwSystemSize'] = 'N/A'
            lead['electricalUpgrade'] = 'N/A'
            lead['energyStorage'] = 'N/A'

    return leads
