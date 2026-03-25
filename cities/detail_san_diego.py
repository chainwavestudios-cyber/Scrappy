"""
San Diego County PDS — permit detail page scrape.

Exact field spec:
  From CSV (already on lead before this runs):
    permitNumber, date, address, status

  From detail page main view (after More Details click):
    licensedProfessional  — full text block under "Licensed Professional"
    description           — full text block under "Project Description"

  From Contacts panel (after clicking Contacts expand + More Details):
    homeownerFirstName, homeownerLastName
    homeownerEmail  (null if not present)
    homeownerPhone  (null if not present)

  From Application Information panel (after clicking expand):
    jobInfo  — "kW: X | Electrical Service Upgrade: Y | Advanced Energy Storage: Z"
"""

import re
from bs4 import BeautifulSoup

from accela_detail_primitives import resolve_permit_url_from_href
from accela_detail_ui import (
    resolve_cap_detail_content_frame,
    wait_accela_detail_dom,
)


def _block_after_heading(soup, heading: str) -> str:
    """
    Find a heading/label whose text matches `heading` (case-insensitive) and
    return all the text in the container that follows it — as one clean string.
    """
    heading_lc = heading.lower().strip()
    for el in soup.find_all(['h1', 'h2', 'h3', 'h4', 'td', 'div', 'span', 'label', 'th']):
        if el.get_text(strip=True).lower().strip().rstrip(':') == heading_lc:
            # Try next sibling first
            nxt = el.find_next_sibling()
            if nxt and nxt.get_text(strip=True):
                return nxt.get_text(separator=' ', strip=True)
            # Try parent's next sibling (table row pattern)
            parent = el.find_parent(['tr', 'div', 'section', 'table', 'fieldset'])
            if parent:
                nxt2 = parent.find_next_sibling()
                if nxt2 and nxt2.get_text(strip=True):
                    return nxt2.get_text(separator=' ', strip=True)
    return ''


def _td_value_after_label(soup, label_lc: str) -> str:
    """Accela label/value <td> pair. Case-insensitive, strips colons, partial match allowed."""
    label_lc = label_lc.lower().strip().rstrip(':')
    for tr in soup.find_all('tr'):
        cells = tr.find_all(['td', 'th'])
        if len(cells) < 2:
            continue
        cell_text = cells[0].get_text(separator=' ', strip=True).lower().rstrip(':').strip()
        if cell_text == label_lc or label_lc in cell_text:
            val = cells[1].get_text(separator=' ', strip=True)
            if val:
                return val
    # Fallback: labeled element -> next sibling
    for el in soup.find_all(['td', 'div', 'span', 'label']):
        if el.get_text(separator=' ', strip=True).lower().rstrip(':').strip() == label_lc:
            nxt = el.find_next_sibling()
            if nxt:
                val = nxt.get_text(separator=' ', strip=True)
                if val:
                    return val
    return ''


def _parse_owner_block(soup) -> dict:
    """
    Find the 'Owner on Application' contact block and extract name, email, phone.
    Returns dict with keys: firstName, lastName, email, phone (all may be empty).
    """
    result = {'firstName': '', 'lastName': '', 'email': '', 'phone': ''}

    # Find the largest block of text that contains 'owner on application'
    best_blob = ''
    for el in soup.find_all(['div', 'table', 'td', 'fieldset', 'section', 'tbody']):
        t = el.get_text(separator='\n', strip=True)
        if 'owner on application' in t.lower() and len(t) > len(best_blob):
            best_blob = t

    if not best_blob:
        return result

    lines = [ln.strip() for ln in best_blob.splitlines() if ln.strip()]

    # Find "Owner on Application" line, then read the lines that follow
    owner_idx = None
    for i, ln in enumerate(lines):
        if 'owner on application' in ln.lower():
            owner_idx = i
            break

    if owner_idx is None:
        return result

    # Collect the data lines after the heading
    data_lines = []
    for ln in lines[owner_idx + 1:]:
        # Stop when we hit another section heading (all-caps multi-word or known labels)
        if ln.lower() in ('applicant', 'contractor', 'owner', 'licensed professional'):
            break
        if re.match(r'^[A-Z][A-Z\s]+:$', ln):  # e.g. "BUSINESS PHONE:"
            break
        data_lines.append(ln)
        if len(data_lines) >= 8:
            break

    # Name: first non-empty line after heading that looks like a name (no digits, no @)
    # SD portal sometimes renders full name as 'FIRST LAST' on one line
    name_line = ''
    for ln in data_lines:
        if not re.search(r'[\d@/\\]', ln) and len(ln.split()) >= 1 and len(ln) < 60:
            name_line = ln
            break

    if name_line:
        # Handle "LAST, FIRST" or "FIRST LAST"
        if ',' in name_line:
            parts = [p.strip() for p in name_line.split(',', 1)]
            result['lastName'] = parts[0].title()
            result['firstName'] = parts[1].title() if len(parts) > 1 else ''
        else:
            parts = name_line.split()
            result['firstName'] = parts[0].title()
            result['lastName'] = ' '.join(parts[1:]).title() if len(parts) > 1 else ''

    # Email: line containing @
    for ln in data_lines:
        if '@' in ln and '.' in ln:
            result['email'] = ln.strip()
            break

    # Phone: line that looks like a phone number
    for ln in data_lines:
        digits = re.sub(r'\D', '', ln)
        if len(digits) >= 10:
            result['phone'] = ln.strip()
            break

    return result


async def fetch_permit_detail(detail_page, base_url, module, permit_num, lead, cfg, log):
    """
    San Diego PDS detail scrape — exact field spec per product requirements.
    """
    resolve_permit_url_from_href(base_url, permit_num, module, lead)
    detail_url = lead['permitUrl']
    log.info(f'  → {detail_url}')

    await detail_page.goto(detail_url, wait_until='domcontentloaded', timeout=20000)
    try:
        await detail_page.wait_for_load_state('networkidle', timeout=18000)
    except Exception:
        pass

    # Wait for ACAFrame to have real content
    ctx = await wait_accela_detail_dom(detail_page, log)

    # ── Step 1: Click "More Details" to reveal Licensed Professional + Project Description ──
    await ctx.evaluate("""
        () => {
            const els = Array.from(document.querySelectorAll('a, span, button'));
            const more = els.find(e => e.textContent.trim() === 'More Details');
            if (more) more.click();
        }
    """)
    await detail_page.wait_for_timeout(1500)
    ctx = await resolve_cap_detail_content_frame(detail_page, log)
    html = await ctx.content()
    soup = BeautifulSoup(html, 'lxml')

    # Licensed Professional — full text block
    lp = _block_after_heading(soup, 'Licensed Professional')
    if not lp:
        # Fallback: find the label in any element and grab sibling/parent content
        for el in soup.find_all(['td', 'div', 'span']):
            if el.get_text(strip=True).lower().strip() == 'licensed professional':
                parent = el.find_parent(['tr', 'div', 'table'])
                if parent:
                    nxt = parent.find_next_sibling()
                    if nxt:
                        lp = nxt.get_text(separator=' ', strip=True)
                        break
    lead['licensedProfessional'] = lp

    # Project Description — full text block
    desc = _block_after_heading(soup, 'Project Description')
    if not desc:
        desc = _td_value_after_label(soup, 'project description')
    if desc:
        lead['description'] = desc
        lead['projectDescription'] = desc

    # ── Step 2: Click "Contacts" expand, then "More Details" inside it ──
    await ctx.evaluate("""
        () => {
            // Try title="Expand Contacts" first (most reliable)
            const byTitle = document.querySelector('[title="Expand Contacts"]');
            if (byTitle) { byTitle.click(); return; }
            // Fallback: heading with text "Contacts"
            const heads = Array.from(document.querySelectorAll('h1,h2,h3,a,span'));
            const h = heads.find(e => e.textContent.trim() === 'Contacts');
            if (h) h.click();
        }
    """)
    # Wait for "Owner on Application" to appear
    for _ in range(15):
        await detail_page.wait_for_timeout(400)
        ctx = await resolve_cap_detail_content_frame(detail_page, log)
        found = await ctx.evaluate("""
            () => document.body.innerText.toLowerCase().includes('owner on application')
        """)
        if found:
            break

    # Click "More Details" inside the contacts panel
    await ctx.evaluate("""
        () => {
            const els = Array.from(document.querySelectorAll('a, span, button'));
            const more = els.find(e => e.textContent.trim() === 'More Details');
            if (more) more.click();
        }
    """)
    await detail_page.wait_for_timeout(1200)
    ctx = await resolve_cap_detail_content_frame(detail_page, log)
    html2 = await ctx.content()
    soup2 = BeautifulSoup(html2, 'lxml')

    owner = _parse_owner_block(soup2)
    lead['homeownerFirstName'] = owner['firstName']
    lead['homeownerLastName'] = owner['lastName']
    lead['homeownerEmail'] = owner['email'] or None
    lead['homeownerPhone'] = owner['phone'] or None

    # ── Step 3: Click "Application Information" expand ──
    await ctx.evaluate("""
        () => {
            const byTitle = document.querySelector('[title="Expand Application Information"]');
            if (byTitle) { byTitle.click(); return; }
            const heads = Array.from(document.querySelectorAll('h1,h2,h3,a,span'));
            const h = heads.find(e => e.textContent.trim() === 'Application Information');
            if (h) h.click();
        }
    """)
    # Wait for kW field to appear
    for _ in range(15):
        await detail_page.wait_for_timeout(400)
        ctx = await resolve_cap_detail_content_frame(detail_page, log)
        found = await ctx.evaluate("""
            () => {
                const t = document.body.innerText.toLowerCase();
                return t.includes('kilowatt') || t.includes('electrical service upgrade');
            }
        """)
        if found:
            break

    ctx = await resolve_cap_detail_content_frame(detail_page, log)
    html3 = await ctx.content()
    soup3 = BeautifulSoup(html3, 'lxml')

    kw   = (_td_value_after_label(soup3, 'rounded kilowatts total system size')
            or _td_value_after_label(soup3, 'rounded kilowatts total')
            or _td_value_after_label(soup3, 'dc system size'))
    elec = _td_value_after_label(soup3, 'electrical service upgrade')
    ess  = _td_value_after_label(soup3, 'advanced energy storage system')

    # Build jobInfo as one string
    parts = []
    if kw:   parts.append(f'kW: {kw}')
    if elec: parts.append(f'Electrical Service Upgrade: {elec}')
    if ess:  parts.append(f'Advanced Energy Storage: {ess}')
    if parts:
        lead['jobInfo'] = ' | '.join(parts)

    log.info(
        f'  lp={bool(lp)} | desc={bool(desc)} | '
        f'owner={lead["homeownerFirstName"]} {lead["homeownerLastName"]} | '
        f'email={lead["homeownerEmail"]} | phone={lead["homeownerPhone"]} | '
        f'jobInfo={lead.get("jobInfo", "—")}'
    )
