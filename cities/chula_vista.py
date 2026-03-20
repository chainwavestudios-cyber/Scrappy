"""Chula Vista — Accela portal."""

CONFIGS = {
    'chula_vista': {
        'name':        'Chula Vista',
        'base_url':    'https://aca-prod.accela.com/CHULAVISTA',
        'module':      'Building',
        'permit_type': 'Residential Solar Energy',
        'source':      'chula_vista_accela',
    },
    'chula_vista_commercial': {
        'name':        'Chula Vista',
        'base_url':    'https://aca-prod.accela.com/CHULAVISTA',
        'module':      'Building',
        'permit_type': 'Commercial Solar Energy',
        'source':      'chula_vista_accela',
        'lead_category': 'commercial',
    },
    'chula_vista_solarapp': {
        'name':        'Chula Vista',
        'base_url':    'https://aca-prod.accela.com/CHULAVISTA',
        'module':      'Building',
        'permit_type': 'Solar Permit with SolarApp+',
        'source':      'chula_vista_accela',
        'lead_category': 'residential',
    },
}
