#!/usr/bin/env python3
"""
Local Accela scrape → JSON file only (no Base44, no database, no Render).

Use this to validate new city configs before deploying.

  python test_city_local.py downey
  python test_city_local.py downey --days 14
  python test_city_local.py downey --range 03/01/2026 03/23/2026
  python test_city_local.py downey -o ./tmp/downey.json
  python test_city_local.py chula_vista oakland --compact

Requires: Playwright + Chromium (from repo root: pip install -r requirements.txt
          && playwright install chromium).

City tokens use the same aliases as runscan.py (e.g. sandiego, chula, downey).
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone


def _repo_root() -> str:
    return os.path.dirname(os.path.abspath(__file__))


def _ensure_path() -> None:
    root = _repo_root()
    if root not in sys.path:
        sys.path.insert(0, root)


def build_payload(
    city_tokens: list[str],
    start_date: str,
    end_date: str,
    *,
    strip_accela_csv: bool,
) -> dict:
    _ensure_path()
    from scraper_accela import CITY_CONFIGS, scrape_accela
    from runscan_core import resolve_city_keys

    valid = set(CITY_CONFIGS.keys())
    keys, warnings = resolve_city_keys(city_tokens, valid)
    if not keys:
        raise SystemExit(
            f'No valid city keys for {city_tokens!r}. '
            f'Available: {", ".join(sorted(valid))}'
        )

    all_leads: list[dict] = []
    runs: list[dict] = []

    for key in keys:
        try:
            leads = scrape_accela(key, start_date, end_date)
        except Exception as e:
            runs.append({'city_key': key, 'ok': False, 'error': str(e), 'lead_count': 0})
            continue
        for lead in leads:
            d = dict(lead)
            if strip_accela_csv:
                d.pop('accelaCsv', None)
            d['scrapeCityKey'] = key
            all_leads.append(d)
        runs.append({'city_key': key, 'ok': True, 'error': None, 'lead_count': len(leads)})

    ok_runs = sum(1 for r in runs if r.get('ok'))
    return {
        'success': ok_runs == len(runs) and len(runs) > 0,
        'meta': {
            'start_date': start_date,
            'end_date': end_date,
            'generated_at': datetime.now(timezone.utc).isoformat(),
            'cities_requested': city_tokens,
            'city_keys_run': keys,
            'local_file_only': True,
            'no_database': True,
        },
        'runs': runs,
        'leads': all_leads,
        'warnings': warnings,
        'summary': {
            'total_leads': len(all_leads),
            'runs_ok': ok_runs,
            'runs_total': len(runs),
        },
    }


def main() -> int:
    p = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument(
        'city',
        nargs='+',
        help='City token(s): config key or runscan alias (e.g. downey, sandiego)',
    )
    g = p.add_mutually_exclusive_group()
    g.add_argument(
        '--days',
        type=int,
        default=None,
        metavar='N',
        help='Inclusive calendar days ending today (default: 7 if no --range)',
    )
    g.add_argument(
        '--range',
        nargs=2,
        metavar=('START', 'END'),
        help='Fixed Accela date range mm/dd/yyyy mm/dd/yyyy',
    )
    p.add_argument(
        '-o',
        '--output',
        help='Output JSON path (default: ./output/scrape_<city>_<timestamp>.json)',
    )
    p.add_argument(
        '--compact',
        action='store_true',
        help='Remove accelaCsv from each lead (smaller file)',
    )
    args = p.parse_args()

    _ensure_path()
    from runscan_core import date_range_for_days

    if args.range:
        start_date, end_date = args.range[0], args.range[1]
    elif args.days is not None:
        start_date, end_date = date_range_for_days(args.days)
    else:
        start_date, end_date = date_range_for_days(7)

    payload = build_payload(
        args.city,
        start_date,
        end_date,
        strip_accela_csv=args.compact,
    )

    out = args.output
    if not out:
        os.makedirs(os.path.join(_repo_root(), 'output'), exist_ok=True)
        stamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        safe = args.city[0].lower().replace('/', '-').replace(' ', '_')
        out = os.path.join(_repo_root(), 'output', f'scrape_{safe}_{stamp}.json')

    out_abs = os.path.abspath(out)
    parent = os.path.dirname(out_abs)
    if parent:
        os.makedirs(parent, exist_ok=True)
    with open(out_abs, 'w', encoding='utf-8') as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)
        f.write('\n')

    s = payload['summary']
    print(
        f'Local-only scrape: {s["total_leads"]} leads → {out_abs}',
        file=sys.stderr,
    )
    for w in payload.get('warnings') or []:
        print(f'Warning: {w}', file=sys.stderr)
    for r in payload.get('runs') or []:
        if not r.get('ok'):
            print(f'Run failed {r.get("city_key")}: {r.get("error")}', file=sys.stderr)

    if s['runs_total'] == 0:
        return 1
    if s['runs_ok'] != s['runs_total']:
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
