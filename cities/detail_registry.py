"""
Resolve Accela detail fetcher by city_key. One implementation per city when needed;
default is standard Accela CapDetail flow.
"""
from . import detail_san_diego, detail_standard

_DETAIL_BY_CITY = {
    'san_diego_residential': detail_san_diego.fetch_permit_detail,
    'san_diego_commercial': detail_san_diego.fetch_permit_detail,
}


def get_detail_fetcher(city_key: str):
    return _DETAIL_BY_CITY.get(city_key, detail_standard.fetch_permit_detail)
