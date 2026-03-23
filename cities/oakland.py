"""Oakland — Accela portal.

Two Building record types to scrape (must match <option> text exactly):
  - oakland:         Solar Permit (…SolarApp+… exclusions…)
  - oakland_solarapp: SolarApp+ (…38.4kw… SolarApp+- contractor use)

Config keys: see cities/__init__.py (ACCELA_CITY_CONFIG_KEYS).
"""

CONFIGS = {
    'oakland': {
        'name':        'Oakland',
        'base_url':    'https://aca-prod.accela.com/OAKLAND',
        'module':      'Building',
        # Screenshot / portal dropdown — exact string
        'permit_type': 'Solar Permit (For commercial projects, residential projects not eligible for SolarApp+, or owner/builder or contractor use)',
        'source':      'oakland_accela',
        'col_date':         1,
        'col_permit_num':   3,
        'col_permit_type':  4,
        'col_description':  6,
        'col_project_name': None,
        'col_status':       2,
        'col_action':       None,
        'col_short_notes':  None,
        'col_address':      5,
    },
    'oakland_solarapp': {
        'name':        'Oakland',
        'base_url':    'https://aca-prod.accela.com/OAKLAND',
        'module':      'Building',
        # Screenshot / portal dropdown — exact string (note SolarApp+- before "contractor")
        'permit_type': 'SolarApp+ (For roof mounted residential solar projects not exceeding 38.4kw total done with SolarApp+- contractor use)',
        'source':      'oakland_accela',
        'lead_category': 'residential',
        'col_date':         1,
        'col_permit_num':   3,
        'col_permit_type':  4,
        'col_description':  6,
        'col_project_name': None,
        'col_status':       2,
        'col_action':       None,
        'col_short_notes':  None,
        'col_address':      5,
    },
}
