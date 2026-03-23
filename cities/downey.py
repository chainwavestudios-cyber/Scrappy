"""Downey — Accela Citizen Access (Building).

General search: permit type *Residential Solar* + date range. All data comes from
the results grid only (no CSV export, no detail pages). Column 0 is the row
checkbox/lead-in; real fields start at index 1.

Search/detail keys: see cities/__init__.py (ACCELA_CITY_CONFIG_KEYS).
"""

CONFIGS = {
    'downey': {
        'name':        'Downey',
        'base_url':    'https://aca-prod.accela.com/DOWNEY',
        'module':      'Building',
        # Deep link to Building search (matches portal tab layout)
        'portal_url':  (
            'https://aca-prod.accela.com/DOWNEY/Cap/CapHome.aspx'
            '?module=Building&TabName=Building'
            '&TabList=Home%7C0%7CBuilding%7C1%7CBusiness%7C2%7CPlanning%7C3%7CFire%7C4%7CPublicWorks%7C5%7CCurrentTabIndex%7C1'
        ),
        'permit_type': 'Residential Solar',
        'source':      'downey_accela',
        'lead_category': 'residential',
        'skip_solar_description_filter': True,
        # Grid only — no export, no CapDetail navigation
        'skip_csv_download': True,
        'skip_detail_fetch': True,
        # Keep full address line (do not strip trailing digits / APN tail heuristic)
        'skip_address_apn_strip': True,
        # td indices: [0]=select, 1=Date, 2=Permit# (link), 3=Type, 4=Description, 5=Address, 6=Status, 7+=Action
        'col_date':          1,
        'col_permit_num':    2,
        'col_permit_type':   3,
        'col_description':   4,
        'col_address':       5,
        'col_status':        6,
        'col_project_name':  None,
    },
}
