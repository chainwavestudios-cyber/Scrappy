"""
Playwright UI actions shared by Accela detail flows (no city-specific logic).
"""
from bs4 import BeautifulSoup

from accela_detail_primitives import parse_owner_contacts_soup


async def click_more_details_visible(detail_page):
    await detail_page.evaluate("""
        () => {
            const els = Array.from(document.querySelectorAll('a, button, span'));
            const more = els.find(l => (l.textContent || '').includes('More Details'));
            if (more) { more.click(); return true; }
            return false;
        }
    """)
    await detail_page.wait_for_timeout(1800)


async def pds_expand_record_more_details(detail_page) -> None:
    await detail_page.evaluate("""
        () => {
            const byId = document.getElementById('ctl00_PlaceHolderMain_PermitDetailList1_lblMoreDetail')
                || document.querySelector('[id$="PermitDetailList1_lblMoreDetail"]');
            if (byId) { byId.click(); return; }
            const links = Array.from(document.querySelectorAll('a, span, button'));
            const more = links.find(l => (l.textContent || '').trim() === 'More Details');
            if (more) more.click();
        }
    """)
    await detail_page.wait_for_timeout(1800)


async def pds_expand_contacts_heading(detail_page) -> None:
    await detail_page.evaluate("""
        () => {
            const heads = Array.from(document.querySelectorAll('h1, h2, [role="heading"]'));
            let h = heads.find(el => {
                const aria = (el.getAttribute('aria-label') || '').toLowerCase();
                const t = (el.textContent || '').trim();
                return aria.includes('expand contacts')
                    || (t === 'Contacts' && aria.includes('contact'));
            });
            if (!h) {
                h = heads.find(el => (el.textContent || '').trim() === 'Contacts');
            }
            if (h) { h.click(); return; }
            const links = Array.from(document.querySelectorAll('a'));
            const a = links.find(l => (l.textContent || '').trim() === 'Contacts');
            if (a) a.click();
        }
    """)
    await detail_page.wait_for_timeout(2200)


async def pds_expand_application_information_heading(detail_page) -> None:
    await detail_page.evaluate("""
        () => {
            const heads = Array.from(document.querySelectorAll('h1, h2, [role="heading"]'));
            let h = heads.find(el => {
                const aria = (el.getAttribute('aria-label') || '').toLowerCase();
                const t = (el.textContent || '').trim();
                return aria.includes('expand application information')
                    || (aria.includes('application information') && aria.includes('expand'));
            });
            if (!h) {
                h = heads.find(el => (el.textContent || '').trim() === 'Application Information');
            }
            if (h) { h.click(); return; }
            const byId = document.getElementById('ctl00_PlaceHolderMain_PermitDetailList1_lblASIList')
                || document.querySelector('[id$="PermitDetailList1_lblASIList"]');
            if (byId) byId.click();
        }
    """)
    await detail_page.wait_for_timeout(2500)


async def expand_accela_detail_sections(detail_page):
    await detail_page.evaluate("""
        () => {
            const links = Array.from(document.querySelectorAll('a'));
            const more = links.find(l => l.textContent.includes('More Details'));
            if (more) more.click();
        }
    """)
    await detail_page.wait_for_timeout(1500)
    await detail_page.evaluate("""
        () => {
            const els = Array.from(document.querySelectorAll('a, span'));
            const ai = els.find(l => l.textContent.trim() === 'Additional Information');
            if (ai) ai.click();
        }
    """)
    await detail_page.wait_for_timeout(1500)
    await detail_page.evaluate("""
        () => {
            const els = Array.from(document.querySelectorAll('a, span'));
            const ai = els.find(l => l.textContent.trim() === 'Application Information');
            if (ai) ai.click();
        }
    """)
    await detail_page.wait_for_timeout(1500)
    await detail_page.evaluate("""
        () => {
            const els = Array.from(document.querySelectorAll('a, span, button'));
            const ad = els.find(l => l.textContent.trim() === 'Application Details');
            if (ad) ad.click();
        }
    """)
    await detail_page.wait_for_timeout(1500)
    await detail_page.wait_for_timeout(1200)


async def click_record_details_tab(detail_page):
    await detail_page.evaluate("""
        () => {
            const links = Array.from(document.querySelectorAll('a, span'));
            const labels = ['Record Details', 'Record Information', 'Record Info'];
            for (const text of labels) {
                const el = links.find(l => l.textContent.trim() === text);
                if (el) { el.click(); return true; }
            }
            return false;
        }
    """)
    await detail_page.wait_for_timeout(2000)


async def try_parse_owner_from_contacts_tab(detail_page, lead: dict) -> None:
    await pds_expand_contacts_heading(detail_page)
    await click_more_details_visible(detail_page)
    html2 = await detail_page.content()
    soup2 = BeautifulSoup(html2, 'lxml')
    parse_owner_contacts_soup(soup2, lead)
