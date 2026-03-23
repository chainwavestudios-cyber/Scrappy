"""Chula Vista — Accela portal.

All Accela search / detail flags for this jurisdiction live in CONFIGS below.
See cities/__init__.py (ACCELA_CITY_CONFIG_KEYS) for key meanings.
"""

CONFIGS = {
    'chula_vista': {
        # --- Portal / search (used by scraper_accela scrape_accela_async) ---
        'name':        'Chula Vista — Residential Solar',
        'base_url':    'https://aca-prod.accela.com/CHULAVISTA',
        'module':      'Building',
        'permit_type': 'Residential Solar Energy',
        'source':      'chula_vista_accela',
        # --- Detail page (optional) ---
        'parse_owner_on_application': True,
    },
    'chula_vista_commercial': {
        'name':        'Chula Vista — Commercial Solar',
        'base_url':    'https://aca-prod.accela.com/CHULAVISTA',
        'module':      'Building',
        'permit_type': 'Commercial Solar Energy',
        'source':      'chula_vista_accela',
        'lead_category': 'commercial',
        'parse_owner_on_application': True,
    },
    'chula_vista_solarapp': {
        'name':        'Chula Vista — SolarApp+',
        'base_url':    'https://aca-prod.accela.com/CHULAVISTA',
        'module':      'Building',
        'permit_type': 'Solar Permit with SolarApp+',
        'source':      'chula_vista_accela',
        'lead_category': 'residential',
        'parse_owner_on_application': True,
    },
}
