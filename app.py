from flask import Flask, request, jsonify
import requests
import os
import threading
from scraper import scrape_permits

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

    return jsonify({
        'status': 'started',
        'startDate': start_date,
        'endDate': end_date,
        'message': f'Scraping {start_date} to {end_date} — results will post to Base44 webhook when done'
    })

@app.route('/scrape/sync', methods=['POST'])
def scrape_sync():
    """Synchronous version — returns results directly, use for testing"""
    data = request.json or {}
    start_date = data.get('startDate', '03/01/2026')
    end_date = data.get('endDate', '03/10/2026')

    leads = scrape_permits(start_date, end_date)
    return jsonify({
        'success': True,
        'count': len(leads),
        'leads': leads
    })

@app.route('/health', methods=['GET'])
def health():
    return jsonify({'status': 'ok'})

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 5000)))
