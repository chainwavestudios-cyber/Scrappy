"""
Normalize scraped leads immediately before Base44 ingestSolarPermits.

City-specific *search* behavior stays in cities/*.py (CONFIGS). This module
applies universal rules: required-ish fields, address fallback order, email /
phoneNumber aliases, strip internal keys, optional nulls.
"""
from __future__ import annotations

import re
from typing import Any


def _single_line(s: str) -> str:
    return re.sub(r'\s+', ' ', (s or '').replace('\n', ' ')).strip()


def _address_from_project_description(text: str) -> str:
    """Best-effort: first line in project description that looks like a site address."""
    if not text:
        return ''
    for line in text.splitlines():
        ln = line.strip()
        if len(ln) < 8:
            continue
        if not re.search(r'\d', ln):
            continue
        if re.search(
            r'\b(ST|AVE|RD|DR|LN|CT|WAY|BLVD|CIR|HWY|PL|PKWY)\b', ln, re.I
        ) and (re.search(r'\b(CA|California)\b', ln, re.I) or re.search(r'\b\d{5}\b', ln)):
            return ln
    return ''


def _digits_phone(s: str) -> str:
    d = re.sub(r'\D', '', s or '')
    return d if len(d) >= 10 else ''


def prepare_leads_for_base44(leads: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """
    Returns new dicts safe for JSON POST (no underscore-prefixed internal keys).

    Address order: existing address/siteAddress (e.g. CSV/grid) → project
    description line → Owner on Application mailing (ownerMailingAddress).
    Maps homeownerEmail → email, homeownerPhone → phoneNumber (digits string)
    only when present; missing contact after parse rules is fine — omit aliases.
    Clears numberOfPanels unless scraper set _panels_from_app_info.
    Empty jobValue → None.
    """
    out: list[dict[str, Any]] = []
    for raw in leads or []:
        panels_ok = bool(raw.get('_panels_from_app_info'))
        d: dict[str, Any] = {
            k: v for k, v in raw.items() if not str(k).startswith('_')
        }

        addr = (d.get('address') or d.get('siteAddress') or '').strip()
        if not addr:
            addr = _address_from_project_description(
                d.get('projectDescription') or d.get('description') or ''
            )
        if not addr:
            addr = (d.get('ownerMailingAddress') or '').strip()
        addr = _single_line(addr)
        if addr:
            d['address'] = addr
            d['siteAddress'] = addr

        zm = re.search(r'\b(\d{5})(?:-\d{4})?\b', addr)
        if zm and not (d.get('zipCode') or '').strip():
            d['zipCode'] = zm.group(1)

        em = (d.get('homeownerEmail') or '').strip()
        if em:
            d['email'] = em

        ph_raw = (d.get('homeownerPhone') or '').strip()
        if ph_raw:
            digits = _digits_phone(ph_raw)
            if digits:
                d['phoneNumber'] = digits

        jv = d.get('jobValue')
        if jv is None or not str(jv).strip():
            d['jobValue'] = None
        else:
            jvs = str(jv).strip().lower().rstrip(':')
            if jvs in ('valuation', 'job value', 'job value($)', 'n/a', '-'):
                d['jobValue'] = None

        if not panels_ok or not (d.get('numberOfPanels') or '').strip():
            d.pop('numberOfPanels', None)

        out.append(d)
    return out
