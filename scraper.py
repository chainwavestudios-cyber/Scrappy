import requests
from bs4 import BeautifulSoup
import logging

logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)

BASE_URL = 'https://publicservices.sandiegocounty.gov/CitizenAccess'

def get_viewstate(soup):
    data = {}
    for field in ['__VIEWSTATE', '__VIEWSTATEGENERATOR', '__EVENTVALIDATION', '__VIEWSTATEENCRYPTED']:
        el = soup.find('input', {'id': field})
        data[field] = el['value'] if el and el.get('value') else ''
    data['__EVENTTARGET'] = ''
    data['__EVENTARGUMENT'] = ''
    el = soup.find('input', {'id': 'ACA_CS_FIELD'})
    data['ACA_CS_FIELD'] = el['value'] if el and el.get('value') else ''
    return data

def scrape_permits(start_date, end_date):
    session = requests.Session()
    session.headers.update({
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
        'Accept-Language': 'en-US,en;q=0.9',
        'Accept-Encoding': 'gzip, deflate, br',
        'Connection': 'keep-alive',
        'Upgrade-Insecure-Requests': '1',
    })

    # Step 1 — Load homepage
    log.info('Loading homepage...')
    r = session.get(f'{BASE_URL}/Default.aspx')
    soup = BeautifulSoup(r.text, 'lxml')
    log.info(f'Homepage: {r.status_code}')

    # Step 2 — Click PDS tab via POST with correct event target
    log.info('Clicking PDS tab...')
    viewstate = get_viewstate(soup)
    r = session.post(f'{BASE_URL}/Default.aspx', data={
        **viewstate,
        '__EVENTTARGET': 'ctl00$HeaderNavigation$hypModule_PDS',
        '__EVENTARGUMENT': '',
    }, headers={'Referer': f'{BASE_URL}/Default.aspx'})
    soup = BeautifulSoup(r.text, 'lxml')
    log.info(f'After PDS click: {r.status_code}, url: {r.url}')

    # Step 3 — Now navigate to search within the PDS module
    log.info('Loading PDS search page...')
    r = session.get(
        f'{BASE_URL}/Cap/CapHome.aspx',
        params={'module': 'PDS', 'TabName': 'PDS'},
        headers={'Referer': f'{BASE_URL}/Default.aspx'}
    )
    soup = BeautifulSoup(r.text, 'lxml')
    log.info(f'Search page: {r.status_code}, url: {r.url}')
    log.info(f'Title: {soup.title.string.strip() if soup.title else "none"}')

    input_ids = [i.get('id') for i in soup.find_all('input') if i.get('id')]
    select_ids = [s.get('id') for s in soup.find_all('select') if s.get('id')]
    log.info(f'Inputs: {input_ids}')
    log.info(f'Selects: {select_ids}')

    # Check if we have the search form
    has_form = any('txtGS' in str(id) for id in input_ids)
    log.info(f'Has search form: {has_form}')

    if not has_form:
        # Try clicking Search Records link
        log.info('Search form not found, trying Search Records link...')
        search_link = soup.find('a', string=lambda t: t and 'Search' in t)
        if search_link:
            href = search_link.get('href', '')
            log.info(f'Found search link: {href}')
            r = session.get(f'{BASE_URL}/{href}', headers={'Referer': r.url})
            soup = BeautifulSoup(r.text, 'lxml')
            log.info(f'After search link: {r.status_code}, url: {r.url}')
            input_ids = [i.get('id') for i in soup.find_all('input') if i.get('id')]
            log.info(f'Inputs after nav: {input_ids}')

    viewstate = get_viewstate(soup)

    # Step 4 — Submit search
    log.info(f'Submitting search: {start_date} to {end_date}')

    # Find the actual button name
    btn = soup.find('input', {'type': 'submit'}) or soup.find('a', {'id': lambda x: x and 'btn' in str(x).lower()})
    log.info(f'Search button: {btn}')

    search_data = {
        **viewstate,
        'ctl00$PlaceHolderMain$generalSearchForm$txtGSStartDate': start_date,
        'ctl00$PlaceHolderMain$generalSearchForm$txtGSEndDate': end_date,
        'ctl00$PlaceHolderMain$generalSearchForm$ddlSecondaryScopeCode1': '8002',
        'ctl00$PlaceHolderMain$btnSearch': 'Search',
    }

    r = session.post(
        f'{BASE_URL}/Cap/CapHome.aspx?module=PDS&TabName=PDS',
        data=search_data,
        headers={'Referer': r.url}
    )
    soup = BeautifulSoup(r.text, 'lxml')

    log.info(f'Search result: {r.status_code}, url: {r.url}')
    log.info(f'Title: {soup.title.string.strip() if soup.title else "none"}')

    error = soup.select_one('.ErrorMessage, .error, #ctl00_PlaceHolderMain_ErrorMsg')
    if error:
        log.warning(f'Error on page: {error.get_text(strip=True)}')

    rows = soup.select('tr.gdvPermitList_Row')
    log.info(f'Result rows: {len(rows)}')

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

    # Step 5 — Deep dive each record
    for i, lead in enumerate(leads):
        if not lead['detailUrl']:
            continue
        log.info(f'Getting details {lead["recordId"]} ({i+1}/{len(leads)})...')
        try:
            r = session.get(lead['detailUrl'])
            soup = BeautifulSoup(r.text, 'lxml')

            def get_field(label):
                for span in soup.find_all('span'):
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

    return leads
