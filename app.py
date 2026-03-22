from flask import Flask, request, jsonify, send_file
from backup import backup_bp
import requests
import os
import glob
import threading
import logging
from datetime import datetime, timedelta

log = logging.getLogger(__name__)

app = Flask(__name__)
app.register_blueprint(backup_bp)

# ---------------------------------------------------------------------------
# Hourly backup scheduler
# ---------------------------------------------------------------------------
try:
    from apscheduler.schedulers.background import BackgroundScheduler
    from backup import run_backup as _run_backup

    def _scheduled_backup():
        try:
            result = _run_backup()
            print(f'[scheduler] Hourly backup complete: {result.get("timestamp")} '
                  f'({result.get("size_bytes", 0):,} bytes)')
        except Exception as e:
            print(f'[scheduler] Hourly backup failed: {e}')

    _scheduler = BackgroundScheduler()
    _scheduler.add_job(_scheduled_backup, 'cron', minute=0)
    _scheduler.start()
    print('[scheduler] Hourly backup scheduler started')
except ImportError:
    print('[scheduler] apscheduler not installed — add to requirements.txt to enable hourly backups')
except Exception as e:
    print(f'[scheduler] Could not start backup scheduler: {e}')

# ---------------------------------------------------------------------------
# Base44 config
# ---------------------------------------------------------------------------
BASE44_APP_ID     = os.environ.get('BASE44_APP_ID', '69ac768167fa5ab007eb6ae7')
BASE44_DOMAIN     = os.environ.get('BASE44_DOMAIN', 'agentbmanscraper.base44.app')
BASE44_SECRET     = os.environ.get('INTERNAL_SECRET', '')
BASE44_BASE_URL   = os.environ.get('BASE44_BASE_URL',
                      f'https://{BASE44_DOMAIN}/api/apps/{BASE44_APP_ID}/functions')
BASE44_INGEST_URL = f'{BASE44_BASE_URL}/ingestSolarPermits'

# Set BASE44_ENABLED=true in Render env when ready to push data
BASE44_ENABLED = os.environ.get('BASE44_ENABLED', 'false').lower() == 'true'

# Cap cities per campaign / runscan (Playwright + timeout safety). Override if needed.
MAX_CITIES_PER_JOB = max(1, int(os.environ.get('MAX_CITIES_PER_JOB', '5')))


def post_to_base44(leads, city, start_date, end_date, campaign_id=None):
    if not BASE44_ENABLED:
        log.info('[Base44] DISABLED — set BASE44_ENABLED=true in Render env to enable')
        print(f'[Base44] DISABLED — would have posted {len(leads)} leads from {city}')
        return

    if not BASE44_SECRET:
        log.warning('INTERNAL_SECRET not set — skipping Base44 post')
        return

    city_label = city.replace('_', ' ').title()
    scraped_at = datetime.utcnow().isoformat() + 'Z'

    for lead in leads:
        lead['cityKey']         = city
        lead['city']            = city_label
        lead['state']           = 'CA'
        lead['uniqueId']        = f"{city}_{lead.get('permitNumber', '')}"
        lead['enrichmentStage'] = 'scraped'
        lead['scrapedAt']       = scraped_at
        if campaign_id:
            lead['campaignId'] = campaign_id

    try:
        res = requests.post(
            BASE44_INGEST_URL,
            headers={
                'x-internal-secret': BASE44_SECRET,
                'Content-Type':      'application/json',
            },
            json={'leads': leads, 'campaign_id': campaign_id or ''},
            timeout=60
        )
        result = res.json()
        log.info(f'[Base44] {city_label}: {result}')
        print(f'Base44 ingest [{city_label}]: total={result.get("total")} '
              f'created={result.get("created")} updated={result.get("updated")} '
              f'errors={result.get("errors")}')
    except Exception as e:
        log.error(f'[Base44] Post failed: {e}')
        print(f'Base44 post failed: {e}')


# ---------------------------------------------------------------------------
# Disable gzip
# ---------------------------------------------------------------------------
@app.after_request
def disable_compression(response):
    response.headers['Content-Encoding'] = 'identity'
    return response


# ---------------------------------------------------------------------------
# Lazy scraper loader
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


def run_and_post(city, start_date, end_date, campaign_id=None):
    try:
        scrape_fn, kwargs = get_scraper(city)
        leads = scrape_fn(start_date=start_date, end_date=end_date, **kwargs) \
                if kwargs else scrape_fn(start_date, end_date)
        print(f'Scraped {len(leads)} leads from {city}')
        post_to_base44(leads, city, start_date, end_date, campaign_id)
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
        'status':           'ok',
        'service':          'scrappy',
        'base44_enabled':   BASE44_ENABLED,
        'available_cities': ['san_diego', 'los_angeles'] + list(CITY_CONFIGS.keys()),
        'runscan':          'GET /runscan — multi-city test scan on server (POST /runscan/sync)',
    })


@app.route('/scrape/campaign', methods=['POST'])
def scrape_campaign():
    """Campaign scrape — multiple cities, linked to a PermitCampaign ID."""
    data        = request.json or {}
    campaign_id = data.get('campaignId')
    cities      = data.get('cities', [])
    days        = int(data.get('days', 3))

    if not campaign_id:
        return jsonify({'success': False, 'error': 'campaignId is required'}), 400
    if not cities:
        return jsonify({'success': False, 'error': 'cities array is required'}), 400
    if len(cities) > MAX_CITIES_PER_JOB:
        return jsonify({
            'success': False,
            'error': f'At most {MAX_CITIES_PER_JOB} cities per campaign (got {len(cities)}). '
                     'Split into multiple jobs or set MAX_CITIES_PER_JOB.',
        }), 400

    if data.get('startDate') and data.get('endDate'):
        start_date = data['startDate']
        end_date   = data['endDate']
    else:
        today      = datetime.now()
        start      = today - timedelta(days=days)
        start_date = start.strftime('%m/%d/%Y')
        end_date   = today.strftime('%m/%d/%Y')

    for city in cities:
        thread = threading.Thread(
            target=run_and_post,
            args=(city, start_date, end_date, campaign_id)
        )
        thread.daemon = True
        thread.start()

    log.info(f'Campaign {campaign_id} started: {cities} {start_date} → {end_date}')
    return jsonify({
        'status':     'started',
        'campaignId': campaign_id,
        'cities':     cities,
        'startDate':  start_date,
        'endDate':    end_date,
        'days':       days,
        'base44':     'enabled' if BASE44_ENABLED else 'disabled',
    })


@app.route('/scrape/daily', methods=['POST'])
def scrape_daily():
    """Daily cron endpoint — auto date range, single city."""
    data       = request.json or {}
    city       = data.get('city', 'chula_vista')
    days       = int(data.get('days', 3))
    today      = datetime.now()
    start      = today - timedelta(days=days)
    start_date = start.strftime('%m/%d/%Y')
    end_date   = today.strftime('%m/%d/%Y')
    thread = threading.Thread(target=run_and_post, args=(city, start_date, end_date))
    thread.daemon = True
    thread.start()
    log.info(f'Daily scrape started: {city} {start_date} → {end_date}')
    return jsonify({
        'status':    'started',
        'city':      city,
        'startDate': start_date,
        'endDate':   end_date,
        'days':      days,
        'base44':    'enabled' if BASE44_ENABLED else 'disabled',
    })


@app.route('/scrape', methods=['POST'])
def scrape():
    """Async — returns immediately, runs in background."""
    data       = request.json or {}
    city       = data.get('city', 'san_diego')
    start_date = data.get('startDate', '03/01/2026')
    end_date   = data.get('endDate', '03/15/2026')
    thread = threading.Thread(target=run_and_post, args=(city, start_date, end_date))
    thread.daemon = True
    thread.start()
    return jsonify({
        'status':    'started',
        'city':      city,
        'startDate': start_date,
        'endDate':   end_date,
        'base44':    'enabled' if BASE44_ENABLED else 'disabled',
    })


@app.route('/scrape/sync', methods=['POST'])
def scrape_sync():
    """Sync — runs and returns results directly. For testing only."""
    data       = request.json or {}
    city       = data.get('city', 'san_diego')
    start_date = data.get('startDate', '03/01/2026')
    end_date   = data.get('endDate', '03/15/2026')
    try:
        scrape_fn, kwargs = get_scraper(city)
        leads = scrape_fn(start_date=start_date, end_date=end_date, **kwargs) \
                if kwargs else scrape_fn(start_date, end_date)

        city_label = city.replace('_', ' ').title()
        for lead in leads:
            lead['city']            = city_label
            lead['uniqueId']        = f"{city}_{lead.get('permitNumber', '')}"
            lead['enrichmentStage'] = 'scraped'

            # Flag non-"In Review" permits as recent
            status = lead.get('status', '')
            if status and status.lower() != 'in review':
                lead['status'] = f'{status} < 7 days'

            # Remove internal fields from sync output
            for field in ['cityKey', 'state', 'scrapedAt', 'detailHref',
                          'action', 'shortNotes', 'source']:
                lead.pop(field, None)

        return jsonify({'success': True, 'city': city,
                        'count': len(leads), 'leads': leads})
    except NotImplementedError as e:
        return jsonify({'success': False, 'error': str(e)}), 501
    except ValueError as e:
        return jsonify({'success': False, 'error': str(e)}), 400


def _check_internal_secret():
    """If INTERNAL_SECRET is set in env, require matching x-internal-secret header."""
    secret = os.environ.get('INTERNAL_SECRET', '')
    if secret and request.headers.get('x-internal-secret') != secret:
        return jsonify({'success': False, 'error': 'Unauthorized'}), 401
    return None


@app.route('/runscan', methods=['GET'])
def runscan_help():
    """Docs for POST /runscan/sync — multi-city scan on this server (Playwright on Render)."""
    return jsonify({
        'endpoint':       'POST /runscan/sync',
        'content_type':   'application/json',
        'body':           {'days': 4, 'cities': ['sandiego', 'chulavista']},
        'header_optional': 'x-internal-secret: <INTERNAL_SECRET> (required if set on server)',
        'note':           'Runs Accela scraper on this host. Use runscan.py --remote <url> from your laptop.',
        'timeout':        'Long requests may hit Render/proxy limits — shorten days/cities if needed.',
        'max_cities':     MAX_CITIES_PER_JOB,
        'note_cities':    f'POST /runscan/sync allows at most {MAX_CITIES_PER_JOB} resolved Accela cities per request (env MAX_CITIES_PER_JOB).',
    })


@app.route('/runscan/sync', methods=['POST'])
def runscan_sync():
    """
    Multi-city Accela scan — executes on Render (same Playwright env as production).
    JSON body: {"days": 4, "cities": ["sandiego", "chulavista"]}
    """
    err = _check_internal_secret()
    if err:
        return err
    data = request.json or {}
    try:
        days = int(data.get('days', 3))
    except (TypeError, ValueError):
        return jsonify({'success': False, 'error': 'days must be an integer'}), 400
    cities = data.get('cities', [])
    if not cities or not isinstance(cities, list):
        return jsonify({'success': False, 'error': 'cities must be a non-empty array of strings'}), 400
    cities = [str(c) for c in cities]

    try:
        from runscan_core import execute_runscan, count_resolved_cities
        n = count_resolved_cities(cities)
        if n > MAX_CITIES_PER_JOB:
            return jsonify({
                'success': False,
                'error': f'At most {MAX_CITIES_PER_JOB} resolved cities per runscan (got {n}). '
                         'Use fewer tokens (e.g. san_diego_res only) or split requests. '
                         'Override: MAX_CITIES_PER_JOB.',
            }), 400
        payload = execute_runscan(days, cities)
    except ValueError as e:
        return jsonify({'success': False, 'error': str(e)}), 400
    except Exception as e:
        log.exception('runscan_sync failed')
        return jsonify({'success': False, 'error': str(e)}), 500

    return jsonify(payload)


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


@app.route('/health')
def health():
    return jsonify({
        'status':         'ok',
        'base44_enabled': BASE44_ENABLED,
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


# ---------------------------------------------------------------------------
# City discovery — find correct permit type labels
# ---------------------------------------------------------------------------

SOLAR_KEYWORDS = ['solar', 'pv', 'photovoltaic', 'energy storage', 'battery']
SOLAR_PREFERRED = ['Residential Solar Energy', 'Solar Photovoltaic', 'Residential Photovoltaic',
                   'Solar PV', 'Solar Permit', 'Photovoltaic', 'Solar Energy', 'Solar']


async def _discover_city(city_key, config):
    import asyncio
    from playwright.async_api import async_playwright
    result = {'city': config['name'], 'key': city_key, 'status': 'unknown',
              'solar_options': [], 'recommended': None, 'all_options': [], 'error': None}
    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            page    = await (await browser.new_context()).new_page()
            base_url   = config['base_url']
            module     = config['module']
            search_url = (
                f'{base_url}/Cap/CapHome.aspx?module={module}'
                f'&TabName={module}&TabList=HOME%7C0%7C{module}%7C1%7CCurrentTabIndex%7C1'
            )
            try:
                await page.goto(search_url, wait_until='networkidle', timeout=30000)
                await page.wait_for_selector('[id*="txtGSStartDate"]', timeout=15000, state='visible')
                result['status'] = 'ok'
            except Exception as e:
                result['status'] = 'failed'
                result['error']  = str(e)
                await browser.close()
                return result

            options = await page.evaluate("""
                () => {
                    for (const sel of ['select[id*="ddlGSPermitType"]', 'select[id*="PermitType"]']) {
                        const el = document.querySelector(sel);
                        if (el) return Array.from(el.options).map(o => o.text.trim());
                    }
                    return [];
                }
            """)
            result['all_options'] = options
            solar = [o for o in options if any(k in o.lower() for k in SOLAR_KEYWORDS)]
            result['solar_options'] = solar
            for pref in SOLAR_PREFERRED:
                match = next((o for o in solar if pref.lower() in o.lower()), None)
                if match:
                    result['recommended'] = match
                    break
            if not result['recommended'] and solar:
                result['recommended'] = solar[0]
            await browser.close()
    except Exception as e:
        result['status'] = 'error'
        result['error']  = str(e)
    return result


@app.route('/discover/<city_key>', methods=['GET'])
def discover_one(city_key):
    """Discover permit type options for one city. Usage: GET /discover/sacramento"""
    import asyncio
    from scraper_accela import CITY_CONFIGS

    if city_key not in CITY_CONFIGS:
        return jsonify({'error': f'Unknown city: {city_key}',
                        'available': list(CITY_CONFIGS.keys())}), 404

    result = asyncio.run(_discover_city(city_key, CITY_CONFIGS[city_key]))
    return jsonify(result)


@app.route('/discover', methods=['GET'])
def discover():
    """Run discovery for ALL cities in background.
    Returns immediately — check results at GET /discover/results in ~3 min.
    """
    import asyncio
    import json
    from scraper_accela import CITY_CONFIGS

    def run_discovery():
        async def run_all():
            results = {}
            for city_key, config in CITY_CONFIGS.items():
                print(f'Discovering {config["name"]}...')
                result = await _discover_city(city_key, config)
                results[city_key] = result
                print(f'  {config["name"]}: {result["recommended"] or result["error"]}')
            with open('/app/discovery_results.json', 'w') as f:
                json.dump(results, f, indent=2)
            print('Discovery complete — saved to /app/discovery_results.json')
        asyncio.run(run_all())

    thread = threading.Thread(target=run_discovery)
    thread.daemon = True
    thread.start()
    return jsonify({'status': 'started', 'message': 'Check /discover/results in ~3 minutes'})


@app.route('/discover/results', methods=['GET'])
def discover_results():
    """Get discovery results after running /discover"""
    import json
    try:
        with open('/app/discovery_results.json') as f:
            return jsonify(json.load(f))
    except FileNotFoundError:
        return jsonify({'error': 'No results yet — run GET /discover first'}), 404


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
