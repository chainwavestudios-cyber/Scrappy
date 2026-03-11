from flask import Flask, request, jsonify
import requests
import os
import threading
from bs4 import BeautifulSoup
from scraper import scrape_permits, BASE_URL

app = Flask(__name__)

BASE44_WEBHOOK = os.environ.get('BASE44_WEBHOOK_URL', '')

def run_scrape_and_post(start_date, end_date):
    try:
        leads = scrape_permits(start_date, end_date)
        if BASE44_WEBHOOK:
            res = requests.post(BASE44_WEBHOOK, json={
                'leads': leads,
                'startDate': start_date,
                'endDate': end_date,
                'source': 'san_diego_pds'
            })
            print(f'Posted {len(leads)} leads to Base44: {res.status_code}')
        return leads
    except Exception as e:
        print(f'Scrape failed: {e}')
        return []

@app.route('/scrape', methods=['POST'])
def scrape():
    data = request.json or {}
    start_date = data.get('startDate', '03/01/2026')
    end_date = data.get('endDate', '03/10/2026')
    thread = threading.Thread(target=run_scrape_and_post, args=(start_date, end_date))
    thread.start()
    return jsonify({'status': 'started', 'startDate': start_date, 'endDate': end_date})

@app.route('/scrape/sync', methods=['POST'])
def scrape_sync():
    data = request.json or {}
    start_date = data.get('startDate', '03/01/2026')
    end_date = data.get('endDate', '03/10/2026')
    leads = scrape_permits(start_date, end_date)
    return jsonify({'success': True, 'count': len(leads), 'leads': leads})

@app.route('/debug', methods=['POST'])
def debug():
    session = requests.Session()
    session.headers.update({'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'})

    r1 = session.get(f'{BASE_URL}/Default.aspx')
    soup1 = BeautifulSoup(r1.text, 'lxml')
    viewstate = get_viewstate(soup1)

    r2 = session.post(f'{BASE_URL}/Default.aspx', data={
        **viewstate,
        '__EVENTTARGET': 'ctl00$HeaderNavigation$hypModule_PDS',
    })
    soup2 = BeautifulSoup(r2.text, 'lxml')

    r3 = session.get(f'{BASE_URL}/Cap/CapHome.aspx?module=PDS&TabName=PDS')
    soup3 = BeautifulSoup(r3.text, 'lxml')

    return jsonify({
        'homepage_status': r1.status_code,
        'pds_tab_status': r2.status_code,
        'pds_tab_title': soup2.title.string if soup2.title else None,
        'search_page_status': r3.status_code,
        'search_page_title': soup3.title.string if soup3.title else None,
        'search_page_url': r3.url,
        'inputs_on_search_page': [{'id': i.get('id'), 'name': i.get('name')} for i in soup3.find_all('input') if i.get('id')],
        'selects_on_search_page': [{'id': s.get('id'), 'name': s.get('name')} for s in soup3.find_all('select') if s.get('id')],
    })

@app.route('/health', methods=['GET'])
def health():
    return jsonify({'status': 'ok'})

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
