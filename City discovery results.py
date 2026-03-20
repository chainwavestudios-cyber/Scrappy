# City Discovery Results
# Run: curl https://scrappy-au2o.onrender.com/discover/<city_key>
# Update CITY_CONFIGS in scraper_accela.py only after verifying each city works

DISCOVERY_RESULTS = {

    # ✅ WORKING — confirmed permit type found
    'chula_vista': {
        'permit_type': 'Residential Solar Energy',
        'status': 'working',
        'notes': 'Fully tested and working',
    },
    'oakland': {
        'permit_type': 'Solar Permit (For commercial projects, residential projects not eligible for SolarApp+, or owner/builder or contractor use)',
        'status': 'discovered',
        'notes': 'Permit type found — needs scrape test to confirm',
    },
    'palmdale': {
        'permit_type': 'Solar Permit (Commercial, Ground Mount, ESS 400lbs or Higher, or Adding to Existing System)',
        'status': 'discovered',
        'notes': 'Also has Solar App+ for residential — may want to scrape both',
    },
    'downey': {
        'permit_type': 'Residential Solar',
        'status': 'discovered',
        'notes': 'Also has Commercial Solar option',
    },

    # ❓ NEEDS INVESTIGATION — portal loaded but dropdown empty (different selector ID)
    'sacramento': {
        'permit_type': None,
        'status': 'needs_investigation',
        'notes': 'Portal loads but permit type dropdown not found by auto-discovery. Try manually visiting https://aca-prod.accela.com/SACRAMENTO/Cap/CapHome.aspx?module=Building',
    },
    'santa_ana': {
        'permit_type': None,
        'status': 'needs_investigation',
        'notes': 'Portal loads but permit type dropdown not found. Try https://aca-prod.accela.com/SANTAANA/Cap/CapHome.aspx?module=Building',
    },
    'fontana': {
        'permit_type': None,
        'status': 'needs_investigation',
        'notes': 'Portal loads but permit type dropdown not found. Try https://aca-prod.accela.com/FONTANA/Cap/CapHome.aspx?module=Building',
    },
    'concord': {
        'permit_type': None,
        'status': 'needs_investigation',
        'notes': 'Portal loads but permit type dropdown not found. Try https://aca-prod.accela.com/CONCORD/Cap/CapHome.aspx?module=Building',
    },
    'berkeley': {
        'permit_type': None,
        'status': 'needs_investigation',
        'notes': 'Portal loads but permit type dropdown not found. Try https://aca-prod.accela.com/BERKELEY/Cap/CapHome.aspx?module=Building',
    },

    # ❌ BROKEN — portal did not load
    'anaheim': {
        'permit_type': None,
        'status': 'timeout',
        'notes': 'Portal timed out — may use a different Accela URL or custom system. Check https://www.anaheim.net/355/Building-Permits',
    },
}

# Next steps:
# 1. Test oakland, palmdale, downey with a scrape to confirm they work
# 2. Visit the "needs_investigation" portals manually and find the permit type dropdown label
# 3. Look up Anaheim's actual permit portal URL
# 4. Once confirmed, update CITY_CONFIGS in scraper_accela.py
