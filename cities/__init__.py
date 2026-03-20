"""
City configs for Accela scrapers — one file per city (or city group).
Add new cities by creating cities/<city_name>.py with a CONFIGS dict.
A syntax error in one file won't break the others.
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
