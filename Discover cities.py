"""
Accela City Discovery Tool
Loads each city portal and dumps:
  - Permit type dropdown options
  - Whether date filtering works
  - Sample results for solar keywords
"""
import asyncio
import json
from playwright.async_api import async_playwright

CITIES_TO_DISCOVER = {
    'sacramento': {
        'name': 'Sacramento',
        'base_url': 'https://aca-prod.accela.com/SACRAMENTO',
        'module': 'Building',
    },
    'oakland': {
        'name': 'Oakland',
        'base_url': 'https://aca-prod.accela.com/OAKLAND',
        'module': 'Building',
    },
    'anaheim': {
        'name': 'Anaheim',
        'base_url': 'https://aca-prod.accela.com/ANAHEIM',
        'module': 'Building',
    },
    'santa_ana': {
        'name': 'Santa Ana',
        'base_url': 'https://aca-prod.accela.com/SANTAANA',
        'module': 'Building',
    },
    'fontana': {
        'name': 'Fontana',
        'base_url': 'https://aca-prod.accela.com/FONTANA',
        'module': 'Building',
    },
    'palmdale': {
        'name': 'Palmdale',
        'base_url': 'https://aca-prod.accela.com/PALMDALE',
        'module': 'Building',
    },
    'concord': {
        'name': 'Concord',
        'base_url': 'https://aca-prod.accela.com/CONCORD',
        'module': 'Building',
    },
    'berkeley': {
        'name': 'Berkeley',
        'base_url': 'https://aca-prod.accela.com/BERKELEY',
        'module': 'Building',
    },
    'downey': {
        'name': 'Downey',
        'base_url': 'https://aca-prod.accela.com/DOWNEY',
        'module': 'Building',
    },
}

SOLAR_KEYWORDS = ['solar', 'pv', 'photovoltaic', 'energy storage', 'battery']


async def discover_city(city_key, config):
    base_url  = config['base_url']
    module    = config['module']
    city_name = config['name']

    result = {
        'city': city_name,
        'key': city_key,
        'portal_url': base_url,
        'status': 'unknown',
        'permit_type_options': [],
        'solar_options': [],
        'recommended_permit_type': None,
        'error': None,
    }

    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            context = await browser.new_context(viewport={'width': 1280, 'height': 800})
            page = await context.new_page()

            # Load search form directly
            search_url = (
                f'{base_url}/Cap/CapHome.aspx?module={module}'
                f'&TabName={module}&TabList=HOME%7C0%7C{module}%7C1%7CCurrentTabIndex%7C1'
            )

            try:
                await page.goto(search_url, wait_until='networkidle', timeout=30000)
                await page.wait_for_timeout(3000)
            except Exception as e:
                result['status'] = 'timeout'
                result['error'] = f'Portal load failed: {e}'
                await browser.close()
                return result

            # Wait for search form
            try:
                await page.wait_for_selector('[id*="txtGSStartDate"]', timeout=15000, state='visible')
                result['status'] = 'form_loaded'
            except Exception:
                result['status'] = 'no_search_form'
                result['error'] = 'Search form not found'
                await browser.close()
                return result

            # Get permit type options
            try:
                options = await page.evaluate("""
                    () => {
                        const candidates = [
                            'select[id*="ddlGSPermitType"]',
                            'select[id*="selGSPermitType"]',
                            'select[id*="ddlSearchType"]',
                            'select[id*="PermitType"]',
                        ];
                        for (const sel of candidates) {
                            const el = document.querySelector(sel);
                            if (el) return Array.from(el.options).map(o => o.text.trim());
                        }
                        return [];
                    }
                """)
                result['permit_type_options'] = options

                # Find solar-related options
                solar_opts = [o for o in options
                              if any(kw in o.lower() for kw in SOLAR_KEYWORDS)]
                result['solar_options'] = solar_opts

                # Pick the best solar option
                # Prefer "Residential Solar" type labels
                preferred = ['Residential Solar Energy', 'Solar Photovoltaic',
                             'Residential Photovoltaic', 'Solar PV', 'Solar Permit',
                             'Photovoltaic', 'Solar Energy', 'Solar']
                for pref in preferred:
                    match = next((o for o in solar_opts
                                  if pref.lower() in o.lower()), None)
                    if match:
                        result['recommended_permit_type'] = match
                        break

                if not result['recommended_permit_type'] and solar_opts:
                    result['recommended_permit_type'] = solar_opts[0]

            except Exception as e:
                result['error'] = f'Could not get permit types: {e}'

            await browser.close()

    except Exception as e:
        result['status'] = 'error'
        result['error'] = str(e)

    return result


async def discover_all():
    print('Starting city discovery...\n')
    results = {}

    for city_key, config in CITIES_TO_DISCOVER.items():
        print(f'Checking {config["name"]}...')
        result = await discover_city(city_key, config)
        results[city_key] = result

        print(f'  Status: {result["status"]}')
        if result['solar_options']:
            print(f'  Solar options: {result["solar_options"]}')
            print(f'  → Recommended: {result["recommended_permit_type"]}')
        elif result['permit_type_options']:
            print(f'  No solar options found. All options: {result["permit_type_options"][:5]}...')
        if result['error']:
            print(f'  Error: {result["error"]}')
        print()

    # Save results
    with open('discovery_results.json', 'w') as f:
        json.dump(results, f, indent=2)

    print('\n=== SUMMARY ===')
    print('City                  | Recommended Permit Type')
    print('-' * 60)
    for key, r in results.items():
        pt = r['recommended_permit_type'] or '❌ NOT FOUND'
        print(f'{r["city"]:<22} | {pt}')

    print(f'\nFull results saved to discovery_results.json')
    return results


if __name__ == '__main__':
    asyncio.run(discover_all())
