#!/usr/bin/env python3
"""
Run multi-city Accela scans and write JSON output.

Local (Playwright on this machine):
  python runscan.py <days> <city1> [city2 ...] <output_file>

Remote (Playwright on Render — recommended to match production):
  python runscan.py --remote https://your-service.onrender.com <days> <city1> ... <output_file>
  Set INTERNAL_SECRET in env if your service requires x-internal-secret.

Examples:
  python runscan.py 4 sandiego chulavista scanoutput.txt
  python runscan.py --remote https://scrappy.onrender.com 4 sandiego chulavista scanoutput.txt

Date range: `days` calendar days inclusive ending today.
"""
from __future__ import annotations

import json
import os
import sys


def _repo_root() -> str:
    return os.path.dirname(os.path.abspath(__file__))


def _ensure_path():
    root = _repo_root()
    if root not in sys.path:
        sys.path.insert(0, root)


def _write_payload(path: str, payload: dict) -> None:
    out_path = os.path.abspath(path)
    os.makedirs(os.path.dirname(out_path) or '.', exist_ok=True)
    with open(out_path, 'w', encoding='utf-8') as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)
        f.write('\n')


def _run_remote_remote(base_url: str, days: int, city_tokens: list[str], outfile: str, secret: str) -> int:
    import requests

    base = base_url.rstrip('/')
    url = f'{base}/runscan/sync'
    headers = {'Content-Type': 'application/json'}
    if secret:
        headers['x-internal-secret'] = secret
    print(f'POST {url}', file=sys.stderr)
    print(f'Payload: days={days}, cities={city_tokens}', file=sys.stderr)
    try:
        r = requests.post(
            url,
            json={'days': days, 'cities': city_tokens},
            headers=headers,
            timeout=600,
        )
    except requests.RequestException as e:
        print(f'Request failed: {e}', file=sys.stderr)
        return 1
    if r.status_code == 401:
        print('Unauthorized — set INTERNAL_SECRET or pass --secret to match Render env.', file=sys.stderr)
        return 1
    if r.status_code == 400:
        try:
            print(r.json(), file=sys.stderr)
        except Exception:
            print(r.text, file=sys.stderr)
        return 1
    r.raise_for_status()
    try:
        payload = r.json()
    except Exception as e:
        print(f'Invalid JSON response: {e}', file=sys.stderr)
        print(r.text[:2000], file=sys.stderr)
        return 1
    if not payload.get('success'):
        print(f'Scan failed: {payload}', file=sys.stderr)
        return 1
    _write_payload(outfile, payload)
    n = payload.get('summary', {}).get('total_leads', len(payload.get('leads', [])))
    print(f'Done (remote). {n} leads → {os.path.abspath(outfile)}', file=sys.stderr)
    return 0


def _parse_flags(args: list[str]) -> tuple[str, str, list[str]]:
    """Pull --remote / --secret from any position; return (base_url, secret, rest)."""
    base_url = os.environ.get('RENDER_SERVICE_URL', '').strip()
    secret = os.environ.get('INTERNAL_SECRET', '').strip()
    rest: list[str] = []
    i = 0
    while i < len(args):
        if args[i] == '--remote' and i + 1 < len(args):
            base_url = args[i + 1].strip()
            i += 2
            continue
        if args[i] == '--secret' and i + 1 < len(args):
            secret = args[i + 1].strip()
            i += 2
            continue
        rest.append(args[i])
        i += 1
    return base_url, secret, rest


def main() -> int:
    argv = sys.argv[1:]
    if not argv:
        print(__doc__, file=sys.stderr)
        return 2

    base_url, secret, argv = _parse_flags(argv)

    if len(argv) < 3:
        print(__doc__, file=sys.stderr)
        print('Error: need <days> <city> ... <output_file>', file=sys.stderr)
        return 2

    try:
        days = int(argv[0])
    except ValueError:
        print(f'Error: first argument must be integer (days), got {argv[0]!r}', file=sys.stderr)
        return 2

    outfile = argv[-1]
    city_tokens = argv[1:-1]
    if not city_tokens:
        print('Error: provide at least one city before the output filename.', file=sys.stderr)
        return 2

    if base_url:
        return _run_remote_remote(base_url, days, city_tokens, outfile, secret)

    _ensure_path()
    from runscan_core import execute_runscan

    try:
        payload = execute_runscan(days, city_tokens)
    except ValueError as e:
        print(e, file=sys.stderr)
        return 1

    for w in payload.get('warnings') or []:
        print(w, file=sys.stderr)

    payload['meta']['output_file'] = os.path.abspath(outfile)

    _write_payload(outfile, payload)
    s = payload.get('summary', {})
    print(
        f'Done (local). {s.get("total_leads", 0)} leads → {os.path.abspath(outfile)}',
        file=sys.stderr,
    )
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
