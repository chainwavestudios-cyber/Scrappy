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


async def _try_click_by_title(ctx: UiContext, *titles: str) -> bool:
    """Prefer real Accela expand controls (title=) over generic text scans."""
    for tit in titles:
        if not tit:
            continue
        try:
            loc = ctx.get_by_title(tit)
            if await loc.count() > 0:
                await loc.first.click(timeout=8000)
                await _sleep_ctx(ctx, 500)
                return True
        except Exception:
            continue
    return False


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


def _score_cap_detail_html(html: str) -> int:
    """Pick the frame that actually holds Accela CapDetail panels (may be nested under ACAFrame)."""
    if not html or len(html) < 3500:
        return -1
    low = html.lower()
    head = low[:14000]
    if 'type="password"' in head and 'login' in head:
        return -1
    s = 0
    if 'placeholdermain' in low:
        s += 18
    if 'capdetail' in low or 'permitdetaillist' in low:
        s += 28
    if 'permit detail' in low:
        s += 8
    if 'application information' in low:
        s += 14
    if 'expand application' in low:
        s += 6
    if 'expand contacts' in low:
        s += 6
    if 'rounded kilowatt' in low or 'kilowatts total' in low:
        s += 16
    if 'owner on application' in low:
        s += 14
    if 'electrical service upgrade' in low or 'advanced energy storage' in low:
        s += 10
    if 'licensed professional' in low:
        s += 6
    return s


async def resolve_cap_detail_content_frame(page: Page, log=None) -> UiContext:
    """
    Prefer the frame whose HTML looks like real CapDetail (nested iframe under ACAFrame wins
    over an outer shell that only has scripts).
    """
    best: Frame = page.main_frame
    try:
        main_h = await page.main_frame.content()
    except Exception:
        main_h = ''
    best_s = _score_cap_detail_html(main_h or '')
    for fr in list(page.frames):
        if fr == page.main_frame:
            continue
        try:
            h = await fr.content()
            sc = _score_cap_detail_html(h or '')
            if sc > best_s:
                best_s = sc
                best = fr
        except Exception:
            continue
    if log is not None and best_s >= 20:
        nm = (getattr(best, 'name', None) or '').strip() or '(no name)'
        log.info(f'  CapDetail frame score={best_s} name={nm!r} url={(best.url or "")[:88]}')
    if best_s >= 20:
        return best
    # Fallback: named ACAFrame if present
    for fr in list(page.frames):
        nm = (getattr(fr, 'name', None) or '').strip().lower()
        if nm == 'acaframe':
            try:
                h = await fr.content()
                if h and len(h) > 4000 and 'placeholdermain' in h.lower():
                    return fr
            except Exception:
                pass
    return await resolve_accela_ui_context(page, log)


async def wait_accela_detail_dom(page: Page, log=None, attempts: int = 30) -> UiContext:
    """Poll until Accela shell appears in main or child frame (async iframe load).

    SD PDS CapDetail pages load the outer shell instantly but ACAFrame content
    arrives via async XHR — can take 3-8 seconds. Poll up to 30x500ms = 15s.
    """
    ctx: Optional[Frame] = None
    for i in range(attempts):
        # San Diego PDS: CapDetail lives in iframe[name="ACAFrame"] — prefer it over a fat shell.
        for fr in list(page.frames):
            nm = (getattr(fr, 'name', None) or '').strip().lower()
            if nm == 'acaframe':
                try:
                    h = await fr.content()
                    if h and len(h) > 5500 and 'placeholdermain' in h.lower():
                        if log is not None:
                            log.info(f'  CapDetail: using iframe[name=ACAFrame] (attempt {i+1})')
                        return fr
                except Exception:
                    pass

        ctx = await resolve_accela_ui_context(page, log if i == attempts - 1 else None)
        try:
            h = await ctx.content()
            if h and len(h) > 5500 and 'placeholdermain' in h.lower():
                return ctx
        except Exception:
            pass
        await page.wait_for_timeout(500)

    if log is not None:
        log.warning(f'  wait_accela_detail_dom: content frame not found after {attempts} attempts')
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
    try:
        more = ctx.get_by_text('More Details', exact=True)
        if await more.count() > 0:
            await more.first.click(timeout=8000)
            await _sleep_ctx(ctx, 1800)
            return
    except Exception:
        pass
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
    if await _try_click_by_title(ctx, 'Expand Contacts'):
        await _sleep_ctx(ctx, 1700)
        return
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
    if await _try_click_by_title(ctx, 'Expand Application Information'):
        await _sleep_ctx(ctx, 2000)
        return
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
