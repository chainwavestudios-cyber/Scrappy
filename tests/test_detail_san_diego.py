"""Parser-level tests for San Diego / PDS-style Accela HTML (no Playwright)."""
from bs4 import BeautifulSoup

from accela_detail_primitives import accela_table_row_labeled, build_job_info_text
from cities.detail_registry import get_detail_fetcher
import cities.detail_san_diego as detail_san_diego


def test_accela_table_row_labeled_multiline_cell():
    html = """
    <table>
      <tr><td>Licensed Professional</td><td>ACME SOLAR INC
      123 MAIN ST, SAN DIEGO CA</td></tr>
    </table>
    """
    soup = BeautifulSoup(html, 'lxml')
    val = accela_table_row_labeled(soup, 'licensed professional')
    assert 'ACME' in val
    assert 'SAN DIEGO' in val


def test_build_job_info_text_formats_application_block():
    text = build_job_info_text('10.2', 'No', 'Yes')
    assert 'Rounded Kilowatts Total System Size: 10.2' in text
    assert 'Electrical Service Upgrade: No' in text
    assert 'Advanced Energy Storage System: Yes' in text


def test_registry_maps_san_diego_keys_to_dedicated_module():
    assert get_detail_fetcher('san_diego_residential') is detail_san_diego.fetch_permit_detail
    assert get_detail_fetcher('san_diego_commercial') is detail_san_diego.fetch_permit_detail
