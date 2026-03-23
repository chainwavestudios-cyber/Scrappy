"""Downey — Accela Citizen Access (Building).

Search: Permit type *Residential Solar*, date range. All useful fields are on the
result grid; the record detail view does not add solar-specific fields.
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
        'skip_detail_fetch': True,
        # Columns: Date | Permit Number | Permit Type | Description | Address | Record Status | Action
        'col_date':          0,
        'col_permit_num':    1,
        'col_permit_type':   2,
        'col_description':   3,
        'col_address':       4,
        'col_status':        5,
        'col_project_name':  None,
    },
}
