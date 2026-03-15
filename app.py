from flask import Flask, request, jsonify, send_file
import requests
import os
import glob
import threading
from bs4 import BeautifulSoup

app = Flask(__name__)
BASE44_WEBHOOK = os.environ.get('BASE44_WEBHOOK_URL', '')

# Disable gzip compression — responses are small, no need
@app.after_request
def disable_compression(response):
    response.headers['Content-Encoding'] = 'identity'
    return response

# ---------------------------------------------------------------------------
# Lazy scraper loader — only imports a scraper when that city is called
# ---------------------------------------------------------------------------

def get_scraper(city: str):
    city = city.lower().replace(' ', '_').replace('-', '_')

    if city in ('san_diego', 'sandiego'):
        from scraper import scrape_permits
        return scrape_permits, {}

    if city in ('los_angeles', 'la', 'losangeles'):
        raise NotImplementedError('Los Angeles scraper not yet built')

    from scraper_accela import scrape_accela, CITY_CONFIGS
    if city in CITY_CONFIGS:
        return scrape_accela, {'city_key': city}

    raise ValueError(f'Unknown city: {city}. '
                     f'Available: san_diego, los_angeles, '
                     f'{", ".join(CITY_CONFIGS.keys())}')


def run_and_post(city, start_date, end_date):
    try:
        scrape_fn, kwargs = get_scraper(city)
        leads = scrape_fn(start_date=start_date, end_date=end_date, **kwargs) if kwargs else scrape_fn(start_date, end_date)
        if BASE44_WEBHOOK:
            res = requests.post(BASE44_WEBHOOK, json={
                'leads': leads, 'startDate': start_date,
                'endDate': end_date, 'source': city,
            })
            print(f'Posted {len(leads)} leads to Base44: {res.status_code}')
        return leads
    except Exception as e:
        print(f'Scrape failed [{city}]: {e}')
        return []


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.route('/')
def index():
    from scraper_accela import CITY_CONFIGS
    return jsonify({
        'status': 'ok',
        'service': 'scrappy',
        'available_cities': ['san_diego', 'los_angeles'] + list(CITY_CONFIGS.keys()),
    })


@app.route('/scrape', methods=['POST'])
def scrape():
    data = request.json or {}
    city = data.get('city', 'san_diego')
    start_date = data.get('startDate', '03/01/2026')
    end_date = data.get('endDate', '03/15/2026')
    thread = threading.Thread(target=run_and_post, args=(city, start_date, end_date))
    thread.start()
    return jsonify({'status': 'started', 'city': city,
                    'startDate': start_date, 'endDate': end_date})


@app.route('/scrape/sync', methods=['POST'])
def scrape_sync():
    data = request.json or {}
    city = data.get('city', 'san_diego')
    start_date = data.get('startDate', '03/01/2026')
    end_date = data.get('endDate', '03/15/2026')
    try:
        scrape_fn, kwargs = get_scraper(city)
        leads = scrape_fn(start_date=start_date, end_date=end_date, **kwargs) if kwargs else scrape_fn(start_date, end_date)
        return jsonify({'success': True, 'city': city,
                        'count': len(leads), 'leads': leads})
    except NotImplementedError as e:
        return jsonify({'success': False, 'error': str(e)}), 501
    except ValueError as e:
        return jsonify({'success': False, 'error': str(e)}), 400


@app.route('/cities')
def list_cities():
    from scraper_accela import CITY_CONFIGS
    return jsonify({
        'cities': {
            'san_diego':   {'platform': 'Custom PDS', 'status': 'active'},
            'los_angeles': {'platform': 'Custom',     'status': 'todo'},
            **{k: {'platform': 'Accela', 'status': 'active'}
               for k in CITY_CONFIGS.keys()}
        }
    })


@app.route('/video')
def get_video():
    files = glob.glob('/app/videos/*.webm')
    if not files:
        return jsonify({'error': 'No video yet — run a scrape first'}), 404
    latest = max(files, key=os.path.getctime)
    return send_file(latest, mimetype='video/webm')


@app.route('/videos')
def list_videos():
    files = glob.glob('/app/videos/*.webm')
    return jsonify({'videos': [os.path.basename(f) for f in files],
                    'count': len(files)})


@app.route('/health')
def health():
    return jsonify({'status': 'ok'})


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
