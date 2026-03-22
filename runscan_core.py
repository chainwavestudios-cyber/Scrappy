"""
Shared run-scan logic — used by runscan.py (CLI) and app.py (Render).
Always uses scraper_accela.scrape_accela (Accela paths in cities/).
"""
from __future__ import annotations

import os
import re
from datetime import datetime, timedelta, timezone
from typing import Any


def alias_map() -> dict[str, list[str]]:
    """City name tokens → list of CITY_CONFIGS keys."""
    return {
        'san_diego': ['san_diego_residential', 'san_diego_commercial'],
        'sandiego': ['san_diego_residential', 'san_diego_commercial'],
        'sd': ['san_diego_residential', 'san_diego_commercial'],
        'san_diego_res': ['san_diego_residential'],
        'san_diego_com': ['san_diego_commercial'],
        'san_diego_residential': ['san_diego_residential'],
        'san_diego_commercial': ['san_diego_commercial'],
        'chula_vista': ['chula_vista'],
        'chulavista': ['chula_vista'],
        'chulavisa': ['chula_vista'],
        'chula': ['chula_vista'],
        'oakland': ['oakland'],
        'oakland_solarapp': ['oakland_solarapp'],
        'oakland_solar': ['oakland_solarapp'],
    }


def normalize_token(token: str) -> str:
    t = token.strip().lower()
    t = re.sub(r'[\s\-]+', '_', t)
    t = re.sub(r'_+', '_', t).strip('_')
    return t


def resolve_city_keys(
    tokens: list[str],
    valid_keys: set[str],
) -> tuple[list[str], list[str]]:
    """Returns (ordered_city_keys, warnings)."""
    alias = alias_map()
    keys: list[str] = []
    seen: set[str] = set()
    warnings: list[str] = []

    for raw in tokens:
        n = normalize_token(raw)
        if not n:
            continue
        expanded = alias.get(n)
        if expanded is None:
            if n in valid_keys:
                expanded = [n]
            else:
                warnings.append(f'Unknown city name "{raw}" — skipped.')
                continue
        for k in expanded:
            if k in valid_keys and k not in seen:
                seen.add(k)
                keys.append(k)
            elif k not in valid_keys:
                warnings.append(f'Config missing for "{k}" — skipped.')

    return keys, warnings


def count_resolved_cities(city_tokens: list[str]) -> int:
    """How many Accela city keys `city_tokens` expand to (for job-size limits)."""
    from scraper_accela import CITY_CONFIGS

    valid_keys = set(CITY_CONFIGS.keys())
    city_keys, _ = resolve_city_keys(city_tokens, valid_keys)
    return len(city_keys)


def date_range_for_days(days: int) -> tuple[str, str]:
    """Inclusive range: `days` calendar days ending today."""
    if days < 1:
        raise ValueError('days must be >= 1')
    end = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    start = end - timedelta(days=days - 1)
    fmt = '%m/%d/%Y'
    return start.strftime(fmt), end.strftime(fmt)


def execute_runscan(days: int, city_tokens: list[str]) -> dict[str, Any]:
    """
    Run Accela scrapes for resolved city keys. Returns payload dict.
    Raises ValueError if nothing to scan.
    """
    from scraper_accela import CITY_CONFIGS, scrape_accela

    valid_keys = set(CITY_CONFIGS.keys())
    city_keys, warnings = resolve_city_keys(city_tokens, valid_keys)
    if not city_keys:
        raise ValueError(
            'No valid cities to scan. '
            f'Available: {", ".join(sorted(valid_keys))}'
        )

    start_date, end_date = date_range_for_days(days)
    meta = {
        'days': days,
        'start_date': start_date,
        'end_date': end_date,
        'generated_at': datetime.now(timezone.utc).isoformat(),
        'cities_requested': city_tokens,
        'city_keys_run': city_keys,
        'environment': 'render' if os.environ.get('RENDER') else 'local',
    }

    all_leads: list[dict] = []
    runs: list[dict] = []

    for key in city_keys:
        try:
            leads = scrape_accela(key, start_date, end_date)
        except Exception as e:
            runs.append({'city_key': key, 'ok': False, 'error': str(e), 'lead_count': 0})
            continue
        for lead in leads:
            lead = dict(lead)
            lead['scrapeCityKey'] = key
            all_leads.append(lead)
        runs.append({'city_key': key, 'ok': True, 'error': None, 'lead_count': len(leads)})

    ok_runs = sum(1 for r in runs if r.get('ok'))
    return {
        'success': True,
        'meta': meta,
        'runs': runs,
        'leads': all_leads,
        'warnings': warnings,
        'summary': {
            'total_leads': len(all_leads),
            'runs_ok': ok_runs,
            'runs_total': len(runs),
        },
    }


