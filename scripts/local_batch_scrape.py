#!/usr/bin/env python3
"""
Run Accela scrapes for Chula, Oakland, San Diego (res + com) and save JSON per city.
Uses at most a 3-day inclusive date window (configurable via MAX_DAYS).

Usage (from repo root):
  cd /path/to/Scrappy-main
  python3 scripts/local_batch_scrape.py

Output: test_results/<city_key>_<end_date>_YYYYMMDD_HHMMSS.json
"""
from __future__ import annotations

import json
import os
import sys
import traceback
from datetime import datetime, timedelta

# Repo root = parent of scripts/
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

MAX_DAYS = min(3, int(os.environ.get('SCRAPE_MAX_DAYS', '3')))

# Chula + Oakland + San Diego: residential + commercial Accela configs
CITY_KEYS = [
    'chula_vista',
    'chula_vista_commercial',
    'oakland_solarapp',
    'oakland',
    'san_diego_residential',
    'san_diego_commercial',
]


def date_range_3day() -> tuple[str, str]:
    end = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    start = end - timedelta(days=MAX_DAYS - 1)
    fmt = '%m/%d/%Y'
    return start.strftime(fmt), end.strftime(fmt)


def main() -> int:
    os.chdir(ROOT)
    out_dir = os.path.join(ROOT, 'test_results')
    os.makedirs(out_dir, exist_ok=True)

    from scraper_accela import scrape_accela

    start_date, end_date = date_range_3day()
    stamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    summary_path = os.path.join(out_dir, f'_summary_{stamp}.json')
    summary: dict = {
        'start_date': start_date,
        'end_date': end_date,
        'max_days': MAX_DAYS,
        'runs': [],
    }

    print(f'ROOT={ROOT}', flush=True)
    print(f'Date range: {start_date} → {end_date} ({MAX_DAYS} days)', flush=True)

    for city_key in CITY_KEYS:
        file_base = f'{city_key}_{end_date.replace("/", "-")}_{stamp}'
        path = os.path.join(out_dir, f'{file_base}.json')
        run_meta = {'city_key': city_key, 'file': path, 'ok': False, 'error': None, 'count': 0}
        print(f'\n=== {city_key} ===', flush=True)
        try:
            leads = scrape_accela(city_key, start_date, end_date)
            run_meta['ok'] = True
            run_meta['count'] = len(leads)
            payload = {
                'success': True,
                'city_key': city_key,
                'start_date': start_date,
                'end_date': end_date,
                'count': len(leads),
                'leads': leads,
            }
            with open(path, 'w', encoding='utf-8') as f:
                json.dump(payload, f, indent=2, default=str)
            print(f'Wrote {len(leads)} leads → {path}', flush=True)
        except Exception as e:
            run_meta['error'] = str(e)
            run_meta['traceback'] = traceback.format_exc()
            err_payload = {
                'success': False,
                'city_key': city_key,
                'start_date': start_date,
                'end_date': end_date,
                'error': str(e),
                'traceback': run_meta['traceback'],
            }
            with open(path, 'w', encoding='utf-8') as f:
                json.dump(err_payload, f, indent=2)
            print(f'FAILED {city_key}: {e}', flush=True)

        summary['runs'].append(run_meta)

    with open(summary_path, 'w', encoding='utf-8') as f:
        json.dump(summary, f, indent=2)
    print(f'\nSummary → {summary_path}', flush=True)
    return 0 if all(r['ok'] for r in summary['runs']) else 1


if __name__ == '__main__':
    raise SystemExit(main())
