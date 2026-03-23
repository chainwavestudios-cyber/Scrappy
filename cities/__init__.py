"""
City configs for Accela scrapers — one file per city (or city group).
Add new cities by creating cities/<city_name>.py with a CONFIGS dict.
A syntax error in one file won't break the others.

ACCELA_CITY_CONFIG_KEYS (read by scraper_accela.scrape_accela_async)
--------------------------------------------------------------------
Portal / search
  name, base_url, module          — Accela agency + module= query param
  portal_url                      — Deep link if CapHome URL is non-default
  permit_type                     — Exact ddlGSPermitType option text (optional)
  use_project_name                — General search “Project Name” filter (e.g. OTC)
  portal_pds_iframe               — True: Default.aspx + PDS entry + iframe scan
  pds_entry_link_names            — Labels for PDS tile click (default ['PDS'])

CSV / grid
  skip_csv_download               — True: HTML grid only (no export)
  skip_detail_fetch               — True: no CapDetail navigation
  col_date, col_permit_num, …     — HTML <td> indices (0 = row checkbox when present)
  skip_address_apn_strip          — True: keep full address string from grid
  short_notes_filter              — CSV/grid Short Notes must contain substring (solar gate)
  skip_solar_description_filter   — True: skip description keyword solar filter

Detail / enrich
  owner_from_contacts             — True: San Diego-style Record→Contacts→expand→kW
  parse_owner_on_application      — True: Contacts→More Details→Owner on Application
  require_primary_scope_contains  — Optional list of substrings (rare; mostly unused)

Source / ingest prep
  source, lead_category             — Lead metadata
  daily_only, issued_filter_days  — Row filters (see _accela_row_passes_filters)

Base44 normalization (app.py → base44_prepare.prepare_leads_for_base44) runs after
scrape; it does not duplicate these keys but uses scraped address / owner fields.
"""
import importlib
import logging
import pkgutil

log = logging.getLogger(__name__)

# Cache of merged configs
_CITY_CONFIGS = None


def _load_all_configs():
    """Discover and merge configs from all city modules. Skips broken modules."""
    global _CITY_CONFIGS
    if _CITY_CONFIGS is not None:
        return _CITY_CONFIGS

    merged = {}
    package = __import__(__name__)

    for importer, modname, ispkg in pkgutil.iter_modules(package.__path__):
        if modname.startswith('_'):
            continue
        try:
            module = importlib.import_module(f'{__name__}.{modname}')
            configs = getattr(module, 'CONFIGS', None)
            if configs and isinstance(configs, dict):
                for key, cfg in configs.items():
                    if key in merged:
                        log.warning(f'[cities] Duplicate key {key} — overwriting from {modname}')
                    merged[key] = cfg
                log.debug(f'[cities] Loaded {len(configs)} config(s) from {modname}')
        except Exception as e:
            log.warning(f'[cities] Skipping {modname} (failed to load): {e}')

    _CITY_CONFIGS = merged
    return merged


def get_city_configs():
    """Return the merged dict of all city configs. Safe to call repeatedly."""
    return _load_all_configs().copy()


def get_config(city_key: str):
    """Get a single city config by key, or None if not found."""
    return _load_all_configs().get(city_key)
