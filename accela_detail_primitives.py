"""
Reusable Accela detail-page parsers (BeautifulSoup + lead dict).
City-specific flows live in cities/detail_*.py; this module stays generic.
"""
from __future__ import annotations

import re
from urllib.parse import urljoin, urlparse

from accela_name_utils import extract_homeowner_name


def get_field_from_soup(soup, label):
    """Label/value pairs on Accela detail HTML (table or sibling layout)."""
    lbl = label.lower().rstrip(':')
    for el in soup.find_all(['span', 'td', 'div', 'label', 'th']):
        raw = el.get_text(strip=True)
        tl = raw.lower().rstrip(':')
        if tl == lbl:
            nxt = el.find_next_sibling()
            if nxt and nxt.get_text(strip=True):
                return nxt.get_text(strip=True)
            parent = el.find_parent()
            if parent:
                nxt2 = parent.find_next_sibling()
                if nxt2 and nxt2.get_text(strip=True):
                    return nxt2.get_text(separator=' ', strip=True)
            continue
        if lbl in ('job value($)', 'job value') and 'job value' in tl and ':' in raw:
            parts = raw.split(':', 1)
            if len(parts) == 2 and parts[1].strip():
                return parts[1].strip()
        if tl.startswith(lbl + ':') or tl.startswith(lbl + ' :'):
            parts = raw.split(':', 1)
            if len(parts) == 2 and parts[1].strip():
                return parts[1].strip()
    return ''


def accela_field_first_nonempty(soup, *labels: str) -> str:
    for lab in labels:
        v = get_field_from_soup(soup, lab)
        if (v or '').strip():
            return v.strip()
    return ''


def extract_labeled_multiline(soup, label: str) -> str:
    lbl_low = label.lower().strip()
    for el in soup.find_all(['td', 'div', 'span', 'label']):
        txt = el.get_text(separator='\n', strip=True)
        if not txt or len(txt) < 8:
            continue
        lines = [x.strip() for x in txt.splitlines() if x.strip()]
        if not lines:
            continue
        top = lines[0]
        tl = top.lower().rstrip(':').strip()
        if tl == lbl_low and len(lines) > 1:
            return '\n'.join(lines[1:]).strip()
        if tl.startswith(lbl_low + ':'):
            rest = top.split(':', 1)[1].strip()
            body = ([rest] if rest else []) + lines[1:]
            if body:
                return '\n'.join(body).strip()
    return ''


def _job_value_money_from_page_text(blob: str) -> str:
    if not blob:
        return ''
    patterns = [
        r'Job\s*Value\s*\(\s*\$\s*\)\s*:?\s*(\$[\d,]+(?:\.\d{2})?)',
        r'Job\s*Value\s*\(\s*\$\s*\)\s*:?\s*([\d,]+(?:\.\d{2})?)\s*(?:USD)?',
        r'Job\s*Value\s*:?\s*(\$[\d,]+(?:\.\d{2})?)',
        r'Valuation\s*:?\s*(\$[\d,]+(?:\.\d{2})?)',
        r'Valuation\s*:?\s*([\d,]+(?:\.\d{2})?)\b',
    ]
    for pat in patterns:
        m = re.search(pat, blob, re.I)
        if m:
            s = m.group(1).strip()
            if s and re.search(r'\d', s):
                return s if s.startswith('$') else f'${s}'
    return ''


def clean_accela_job_value(val: str) -> str:
    if not val:
        return ''
    s = val.strip()
    low = s.lower().rstrip(':').strip()
    if low in ('valuation', 'job value', 'job value($)', 'n/a', '-', ''):
        return ''
    if low.startswith('valuation') and not re.search(r'\d', s):
        return ''
    if low.startswith('job value') and not re.search(r'\d', s) and '$' not in s:
        return ''
    return s


def _clean_el_text(el) -> str:
    """
    Return visible text of a BS4 element with all <script> and <style>
    tags removed first.  Accela search forms embed inline JS (e.g.
    shWorkLocation searchWaterMark) directly inside value <td> cells;
    get_text() on the raw element returns the JS blob as part of the
    address string.
    """
    import copy as _copy
    el2 = _copy.copy(el)
    for tag in el2.find_all(['script', 'style']):
        tag.decompose()
    return el2.get_text(separator=' ', strip=True)


def extract_work_location_accela(soup):
    w = get_field_from_soup(soup, 'Work Location')
    if w:
        return w

    for el in soup.find_all(['td', 'div', 'span']):
        txt = _clean_el_text(el)
        if not txt:
            continue
        first = txt.split('\n')[0].strip().lower().rstrip(':')
        if first == 'work location' and '\n' in txt:
            lines = [ln.strip() for ln in txt.split('\n') if ln.strip()]
            if len(lines) >= 2:
                return '\n'.join(lines[1:])

    for el in soup.find_all(['span', 'td', 'div', 'th', 'label', 'strong']):
        raw = _clean_el_text(el)
        low = raw.lower().rstrip(':').strip()
        if low != 'work location':
            continue
        nxt = el.find_next_sibling()
        if nxt and getattr(nxt, 'get_text', None):
            val = _clean_el_text(nxt)
            if val:
                return val
        tr = el.find_parent('tr')
        if tr:
            ntr = tr.find_next_sibling('tr')
            if ntr:
                val = _clean_el_text(ntr)
                if val:
                    return val
            tds = tr.find_all('td')
            for i, td in enumerate(tds):
                if 'work location' in td.get_text().lower() and i + 1 < len(tds):
                    val2 = _clean_el_text(tds[i + 1])
                    if val2 and 'work location' not in val2.lower():
                        return val2
        par = el.find_parent('div')
        if par:
            for sib in el.find_next_siblings():
                if getattr(sib, 'get_text', None):
                    val = _clean_el_text(sib)
                    if val:
                        return val
    return ''


def accela_table_row_labeled(soup, label_lc: str) -> str:
    label_lc = (label_lc or '').lower().strip()
    if not label_lc:
        return ''
    for tr in soup.find_all('tr'):
        cells = tr.find_all(['td', 'th'])
        if len(cells) < 2:
            continue
        lab = cells[0].get_text(separator=' ', strip=True).lower().rstrip(':').strip()
        if lab == label_lc or (lab.startswith(label_lc) and len(lab) <= len(label_lc) + 4):
            val = cells[1].get_text(separator='\n', strip=True)
            val = re.sub(r'\n{3,}', '\n\n', val).strip()
            if val and val.lower() != label_lc:
                return val
    return ''


def accela_td_value_after_label_contains(soup, needle: str) -> str:
    """
    First <tr> whose first cell contains `needle` (case-insensitive) → second cell text.
    San Diego PDS uses long labels like 'Rounded Kilowatts Total' / 'Electrical Service Upgrade:'.
    """
    n = (needle or '').lower().strip()
    if not n:
        return ''
    for tr in soup.find_all('tr'):
        cells = tr.find_all(['td', 'th'])
        if len(cells) < 2:
            continue
        lab = cells[0].get_text(separator=' ', strip=True).lower().rstrip(':').strip()
        if n in lab:
            val = cells[1].get_text(separator=' ', strip=True).strip()
            if val and val.lower() != lab and not val.lower().startswith('select'):
                return val
    return ''


def build_job_info_text(kwh: str, elec: str, ess: str) -> str:
    lines = []
    kk = (kwh or '').strip()
    if kk:
        lines.append(f'Rounded Kilowatts Total System Size: {kk}')
    ee = (elec or '').strip()
    if ee:
        lines.append(f'Electrical Service Upgrade: {ee}')
    ss = (ess or '').strip()
    if ss:
        lines.append(f'Advanced Energy Storage System: {ss}')
    return '\n'.join(lines)


def infer_pds_fields_from_narrative(lead: dict) -> None:
    blob = f"{lead.get('projectDescription') or ''}\n{lead.get('description') or ''}"
    if not blob.strip():
        return
    if not (lead.get('crossStreet') or '').strip():
        m = re.search(
            r'CROSS\s+STREET\s*:?\s*([^\n]+?)(?:\s+Description\s+of\s+Work|\s*$)',
            blob,
            re.I,
        )
        if m:
            lead['crossStreet'] = m.group(1).strip()
    if not (lead.get('electricalServiceUpgrade') or '').strip():
        if re.search(r'\(?\s*no\s+meter\s+upgrade\s*\)?', blob, re.I):
            lead['electricalServiceUpgrade'] = 'No'


def extract_job_value_accela(soup):
    blob = soup.get_text('\n', strip=True)
    blob_sp = soup.get_text(' ', strip=True)
    v = _job_value_money_from_page_text(blob) or _job_value_money_from_page_text(blob_sp)
    if v:
        return v

    for lbl in ('Job Value($)', 'Job Value', 'Valuation'):
        raw = get_field_from_soup(soup, lbl)
        c = clean_accela_job_value(raw)
        if c and len(c) < 200:
            return c

    for el in soup.find_all(['span', 'td', 'div', 'label', 'th']):
        t = el.get_text(strip=True)
        tl = t.lower()
        if 'job value' not in tl or len(t) > 120:
            continue
        if ':' in t:
            parts = t.split(':', 1)
            if len(parts) == 2 and parts[1].strip():
                c = clean_accela_job_value(parts[1].strip())
                if c:
                    return c
        nxt = el.find_next_sibling()
        if nxt and getattr(nxt, 'get_text', None):
            val = nxt.get_text(strip=True)
            c = clean_accela_job_value(val)
            if c:
                return c
        tr = el.find_parent('tr')
        if tr:
            tds = tr.find_all('td')
            for i, td in enumerate(tds):
                if 'job value' in td.get_text().lower() and i + 1 < len(tds):
                    val2 = tds[i + 1].get_text(strip=True)
                    c = clean_accela_job_value(val2)
                    if c:
                        return c
    return ''


def extract_job_value_with_valuation_fallback(soup):
    """Extended job value extraction (valuation siblings) used by standard detail flow."""
    job_value = extract_job_value_accela(soup)
    if not job_value:
        for el in soup.find_all(string=lambda t: t and 'valuation' in t.lower()):
            parent = el.parent
            if not parent:
                continue
            for sibling in parent.next_siblings:
                text = sibling.get_text(strip=True) if hasattr(sibling, 'get_text') else str(sibling).strip()
                if text and text.replace(',', '').replace('.', '').replace('$', '').strip().isdigit():
                    job_value = clean_accela_job_value(text)
                    break
                elif text:
                    job_value = clean_accela_job_value(text)
                    if job_value:
                        break
            if job_value:
                break

    if not job_value:
        for el in soup.find_all(['span', 'td', 'div', 'label', 'th']):
            text = el.get_text(strip=True).lower().rstrip(':')
            if text == 'valuation':
                nxt = el.find_next_sibling()
                if nxt:
                    val = nxt.get_text(strip=True)
                    job_value = clean_accela_job_value(val)
                    if job_value:
                        break
                parent = el.find_parent()
                if parent:
                    nxt2 = parent.find_next_sibling()
                    if nxt2:
                        val2 = nxt2.get_text(separator=' ', strip=True)
                        job_value = clean_accela_job_value(val2)
                        if job_value:
                            break

    JS_INDICATORS = ['function', 'CDATA', 'document.', 'var ', 'ACADialog']
    if any(ind in str(job_value) for ind in JS_INDICATORS):
        job_value = ''
    return clean_accela_job_value(job_value or '')


def zip_from_address_line(address: str) -> str:
    """
    Prefer explicit CA + ZIP (avoid 5-digit street numbers as zipCode).
    Fallback: 5 digits at end of line.
    """
    if not address:
        return ''
    s = address.strip()
    m = re.search(r'(?:,\s*)?(?:CA|California)\s+(\d{5})(?:-\d{4})?\b', s, re.I)
    if m:
        return m.group(1)
    m2 = re.search(r'\b(\d{5})(?:-\d{4})?\s*$', s)
    if m2:
        return m2.group(1)
    return ''


def sync_address_zip_for_ingest(lead):
    loc = (lead.get('siteAddress') or lead.get('address') or '').strip()
    if not loc:
        return
    single = re.sub(r'\s+', ' ', loc.replace('\n', ' ')).strip()
    lead['siteAddress'] = single
    lead['address'] = single
    z = lead.get('zipCode') or ''
    if not (str(z).strip()):
        zc = zip_from_address_line(single)
        if zc:
            lead['zipCode'] = zc


def resolve_permit_url_from_href(base_url: str, permit_num: str, module: str, lead: dict) -> None:
    href = lead.get('detailHref')
    if href and str(href).strip() and not str(href).lower().startswith('javascript'):
        h = str(href).strip()
        if h.startswith('http'):
            lead['permitUrl'] = h
            return
        bu = (base_url or '').strip()
        parsed = urlparse(bu)
        origin = f'{parsed.scheme}://{parsed.netloc}' if parsed.scheme else ''
        path_segs = [s for s in (parsed.path or '').split('/') if s]
        agency = path_segs[-1] if path_segs else ''
        if h.startswith('/'):
            if origin:
                lead['permitUrl'] = urljoin(origin, h)
            else:
                lead['permitUrl'] = urljoin(bu.rstrip('/') + '/', h.lstrip('/'))
            return
        h_rel = h.lstrip('/')
        if origin and agency and h_rel.upper().startswith(agency.upper() + '/'):
            lead['permitUrl'] = urljoin(origin + '/', h_rel)
        else:
            base = bu.rstrip('/')
            lead['permitUrl'] = urljoin(base + '/', h_rel)
        return
    lead['permitUrl'] = f'{base_url}/Cap/CapDetail.aspx?altId={permit_num}&module={module}'


def primary_scope_allowed(soup, cfg: dict) -> bool:
    reqs = cfg.get('require_primary_scope_contains')
    if not reqs:
        return True
    if isinstance(reqs, str):
        reqs = [reqs]
    scope_line = (
        get_field_from_soup(soup, 'Primary Scope Code')
        or get_field_from_soup(soup, 'Primary Scope')
        or ''
    )
    blob = soup.get_text(' ', strip=True)
    combined = f'{scope_line} {blob}'.lower()
    return all(str(r).lower() in combined for r in reqs)


def parse_owner_contacts_soup(soup2, lead: dict) -> None:
    blob = ''
    best_len = 0
    for el in soup2.find_all(['div', 'table', 'td', 'fieldset', 'section', 'tbody']):
        t = el.get_text(separator='\n', strip=True)
        tl = t.lower()
        if 'owner on application' not in tl:
            continue
        if len(t) > best_len:
            blob = t
            best_len = len(t)
    if not blob:
        for el in soup2.find_all(string=re.compile(r'owner\s+on\s+application', re.I)):
            p = el.find_parent(['div', 'table', 'td', 'tr'])
            if p:
                t = p.get_text(separator='\n', strip=True)
                if len(t) > 30:
                    blob = t
                    break
    if not blob:
        return

    lead['ownerOnApplication'] = re.sub(r'\s+', ' ', blob.replace('\n', ' | ')).strip()

    em = re.search(
        r'E-?mail\s*:?\s*([\w.\-+]+@[\w.\-]+\.[a-zA-Z]{2,})',
        blob,
        re.I,
    )
    if em:
        lead['homeownerEmail'] = em.group(1).strip()

    zm = re.search(r'\b(\d{5})(?:-\d{4})?\b', blob)
    if zm:
        lead['zipCode'] = zm.group(1)

    addr_line = None
    for line in blob.split('\n'):
        ln = line.strip()
        if not ln:
            continue
        if re.search(r'\b(CA|California)\b', ln, re.I) and re.search(r'\d{5}', ln):
            addr_line = re.sub(r'\s+', ' ', ln)
            break
        if re.search(r'\b(ST|AVE|RD|DR|LN|CT|WAY|BLVD|CIR)\b', ln, re.I) and re.search(r'\d', ln):
            addr_line = re.sub(r'\s+', ' ', ln)

    if addr_line and not (lead.get('siteAddress') or lead.get('address') or '').strip():
        lead['siteAddress'] = addr_line
        lead['address'] = addr_line
    elif addr_line:
        lead['ownerMailingAddress'] = addr_line

    pm = (
        re.search(r'Primary\s+Phone\s*:?\s*([\d\s\-\(\)\.]+)', blob, re.I)
        or re.search(r'Business\s+Phone\s*:?\s*([\d\s\-\(\)\.]+)', blob, re.I)
        or re.search(r'(?:Cell|Mobile)\s+Phone\s*:?\s*([\d\s\-\(\)\.]+)', blob, re.I)
        or re.search(r'Phone\s*:?\s*([\d\s\-\(\)\.]{10,})', blob, re.I)
    )
    if pm:
        lead['homeownerPhone'] = re.sub(r'\s+', ' ', pm.group(1)).strip()

    lines = [x.strip() for x in blob.split('\n') if x.strip()]
    name_line = None
    for i, ln in enumerate(lines):
        if 'owner on application' in ln.lower():
            for j in range(i + 1, min(i + 5, len(lines))):
                cand = lines[j]
                if '@' in cand or re.search(r'\d{5}', cand):
                    continue
                if re.search(r'\b(st|ave|rd|dr|ln|ct|way|blvd|cir|hwy)\b', cand, re.I):
                    continue
                parts = cand.split()
                if len(parts) >= 2 and len(cand) < 120:
                    name_line = cand
                    break
            break
    if not name_line:
        for ln in lines:
            if '@' in ln or re.search(r'\d{5}', ln):
                continue
            if re.search(r'\b(st|ave|rd|dr|ln|ct|way|blvd|cir)\b', ln, re.I):
                continue
            parts = ln.split()
            if len(parts) >= 2 and len(ln) < 100 and re.match(r'^[A-Za-z]', ln):
                name_line = ln
                break
    if name_line:
        parts = name_line.split()
        lead['homeownerFirstName'] = parts[0]
        lead['homeownerLastName'] = ' '.join(parts[1:]) if len(parts) > 1 else ''
        return

    if blob:
        stripped = re.sub(r'(?i)owner\s+on\s+application\s*:?', ' ', blob)
        for line in re.split(r'[\n|]+', stripped):
            ln = line.strip()
            if len(ln) < 4 or '@' in ln or re.search(r'\b\d{5}\b', ln):
                continue
            if re.search(r'\b(st|ave|rd|dr|ln|ct|way|blvd|cir|hwy|pl)\b', ln, re.I):
                continue
            first, last = extract_homeowner_name(ln, '')
            if first:
                lead['homeownerFirstName'] = first
                lead['homeownerLastName'] = last
                break
