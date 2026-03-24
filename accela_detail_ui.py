"""
Playwright UI actions shared by Accela detail flows (no city-specific logic).

PDS sites (e.g. San Diego) often host Citizen Access inside a child iframe; the
main document is a thin wrapper. Callers should use wait_accela_detail_dom()
after navigation and pass that frame (or page main_frame) into the helpers below.
"""
from __future__ import annotations

from typing import Optional, Union

from bs4 import BeautifulSoup
from playwright.async_api import Frame, Page

from accela_detail_primitives import parse_owner_contacts_soup

UiContext = Union[Page, Frame]


async def _sleep_ctx(ctx: UiContext, ms: int) -> None:
    if isinstance(ctx, Page):
        await ctx.wait_for_timeout(ms)
    else:
        await ctx.page.wait_for_timeout(ms)


async def resolve_accela_ui_context(page: Page, log=None) -> UiContext:
    """
    Return the frame whose DOM actually contains Accela Cap (PlaceHolderMain).
    Falls back to main_frame if no child scores higher.
    """
    candidates: list[Frame] = [page.main_frame] + [
        f for f in page.frames if f != page.main_frame
    ]
    best: Frame = page.main_frame
    best_score = -1
    for fr in candidates:
        try:
            raw = await fr.content()
            html = raw or ''
            low = html.lower()
            if len(html) < 2500:
                continue
            head = low[:8000]
            if 'type="password"' in head and 'login' in head:
                continue
            score = 0
            if 'placeholdermain' in low:
                score += 30
            if 'permitdetaillist' in low or 'permit detail' in low:
                score += 20
            if 'capdetail' in (fr.url or '').lower():
                score += 10
            if 'citizenaccess' in (fr.url or '').lower():
                score += 5
            if score > best_score:
                best_score = score
                best = fr
        except Exception:
            continue
    if log is not None and best != page.main_frame and best_score > 0:
        log.info(
            f'  accela UI in iframe (score={best_score}) '
            f'{(best.url or "")[:95]}'
        )
    return best


async def wait_accela_detail_dom(page: Page, log=None, attempts: int = 18) -> UiContext:
    """Poll until Accela shell appears in main or child frame (async iframe load)."""
    ctx: Optional[Frame] = None
    for i in range(attempts):
        ctx = await resolve_accela_ui_context(page, log if i == attempts - 1 else None)
        try:
            h = await ctx.content()
            if h and len(h) > 5500 and 'placeholdermain' in h.lower():
                return ctx
        except Exception:
            pass
        await page.wait_for_timeout(500)
    return ctx or page.main_frame


async def click_more_details_visible(ctx: UiContext):
    await ctx.evaluate("""
        () => {
            const els = Array.from(document.querySelectorAll('a, button, span'));
            const more = els.find(l => (l.textContent || '').includes('More Details'));
            if (more) { more.click(); return true; }
            return false;
        }
    """)
    await _sleep_ctx(ctx, 1800)


async def pds_expand_record_more_details(ctx: UiContext) -> None:
    await ctx.evaluate("""
        () => {
            const byId = document.getElementById('ctl00_PlaceHolderMain_PermitDetailList1_lblMoreDetail')
                || document.querySelector('[id$="PermitDetailList1_lblMoreDetail"]');
            if (byId) { byId.click(); return; }
            const links = Array.from(document.querySelectorAll('a, span, button'));
            const more = links.find(l => (l.textContent || '').trim() === 'More Details');
            if (more) more.click();
        }
    """)
    await _sleep_ctx(ctx, 1800)


async def pds_expand_contacts_heading(ctx: UiContext) -> None:
    await ctx.evaluate("""
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
    await _sleep_ctx(ctx, 2200)


async def pds_expand_application_information_heading(ctx: UiContext) -> None:
    await ctx.evaluate("""
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
    await _sleep_ctx(ctx, 2500)


async def expand_accela_detail_sections(ctx: UiContext):
    await ctx.evaluate("""
        () => {
            const links = Array.from(document.querySelectorAll('a'));
            const more = links.find(l => l.textContent.includes('More Details'));
            if (more) more.click();
        }
    """)
    await _sleep_ctx(ctx, 1500)
    await ctx.evaluate("""
        () => {
            const els = Array.from(document.querySelectorAll('a, span'));
            const ai = els.find(l => l.textContent.trim() === 'Additional Information');
            if (ai) ai.click();
        }
    """)
    await _sleep_ctx(ctx, 1500)
    await ctx.evaluate("""
        () => {
            const els = Array.from(document.querySelectorAll('a, span'));
            const ai = els.find(l => l.textContent.trim() === 'Application Information');
            if (ai) ai.click();
        }
    """)
    await _sleep_ctx(ctx, 1500)
    await ctx.evaluate("""
        () => {
            const els = Array.from(document.querySelectorAll('a, span, button'));
            const ad = els.find(l => l.textContent.trim() === 'Application Details');
            if (ad) ad.click();
        }
    """)
    await _sleep_ctx(ctx, 1500)
    await _sleep_ctx(ctx, 1200)


async def click_record_details_tab(ctx: UiContext):
    await ctx.evaluate("""
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
    await _sleep_ctx(ctx, 2000)


async def try_parse_owner_from_contacts_tab(detail_page: Page, lead: dict) -> None:
    ctx = await wait_accela_detail_dom(detail_page, log=None)
    await pds_expand_contacts_heading(ctx)
    await click_more_details_visible(ctx)
    ctx2 = await resolve_accela_ui_context(detail_page, log=None)
    html2 = await ctx2.content()
    soup2 = BeautifulSoup(html2, 'lxml')
    parse_owner_contacts_soup(soup2, lead)
