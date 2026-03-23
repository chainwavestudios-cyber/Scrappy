"""Palmdale — Accela portal.

Config keys: see cities/__init__.py (ACCELA_CITY_CONFIG_KEYS).
"""

CONFIGS = {
    'palmdale': {
        'name':        'Palmdale',
        'base_url':    'https://aca-prod.accela.com/PALMDALE',
        'module':      'Building',
        'permit_type': 'Solar Permit (Commercial, Ground Mount, ESS 400lbs or Higher, or Adding to Existing System)',
        'source':      'palmdale_accela',
    },
}
