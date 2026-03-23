"""San Diego County — different portal, same Accela engine.

Search/detail keys: see cities/__init__.py (ACCELA_CITY_CONFIG_KEYS).
"""

CONFIGS = {
    'san_diego_residential': {
        'name':               'San Diego — Residential',
        'base_url':           'https://publicservices.sandiegocounty.gov/CitizenAccess',
        'portal_url':         'https://publicservices.sandiegocounty.gov/CitizenAccess/Default.aspx',
        # Default.aspx: click PDS entry, then use iframe (or main) where Accela form lives
        'portal_pds_iframe':  True,
        'pds_entry_link_names': ['PDS'],
        'module':             'Building',
        # Dropdown label must match portal option text (see ddlGSPermitType)
        'permit_type':        'Residential Alteration or Addition - Plan Check-Permit',
        # Always narrow Accela search to OTC project name
        'use_project_name':   'OTC',
        # CSV / grid Short Notes must contain 8002 — solar vs non-solar for this permit type
        'short_notes_filter': '8002',
        # OTC rows often say "OTC" / "PV" in text, not the word "solar" — skip description keyword gate
        'skip_solar_description_filter': True,
        'source':             'san_diego_accela',
        'lead_category':      'residential',
        'daily_only':         True,
        'owner_from_contacts': True,
        'col_date':           1,
        'col_permit_num':     None,
        'col_permit_type':    3,
        'col_description':    4,
        'col_project_name':   5,
        'col_status':         6,
        'col_short_notes':    8,
        'col_address':        9,
    },
    'san_diego_commercial': {
        'name':               'San Diego — Commercial',
        'base_url':           'https://publicservices.sandiegocounty.gov/CitizenAccess',
        'portal_url':         'https://publicservices.sandiegocounty.gov/CitizenAccess/Default.aspx',
        'portal_pds_iframe':  True,
        'pds_entry_link_names': ['PDS'],
        'module':             'Building',
        # Must match ddl option text (portal uses Plan Check-Permit, not "- PI")
        'permit_type':        'Commercial Alteration or Addition - Plan Check-Permit',
        'use_project_name':   None,
        'source':             'san_diego_accela',
        'lead_category':      'commercial',
        'daily_only':         True,
        'short_notes_filter': '8004',
        'owner_from_contacts': True,
        'col_date':           1,
        'col_permit_num':     None,
        'col_permit_type':    3,
        'col_description':    4,
        'col_project_name':   5,
        'col_status':         6,
        'col_short_notes':    8,
        'col_address':        9,
    },
}
