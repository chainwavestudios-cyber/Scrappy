"""
Shared text helpers for Accela CSV/grid/detail (no BeautifulSoup / Playwright).
"""
import re

_NOT_NAME_WORDS = {
    'install', 'new', 'roof', 'solar', 'remove', 'energy', 'pv', 'photovoltaic',
    'this', 'residential', 'commercial', 'battery', 'upgrade', 'addition',
    'replacement', 'ess', 'lift', 'uninstall', 'reinstall', 'removal', 'level',
    'existing', 'mount', 'mounted', 'system', 'panel', 'panels', 'module',
    'modules', 'inverter', 'storage', 'electric', 'electrical', 'circuit',
    'charger', 'garage', 'tesla', 'powerwall', 'expansion', 'backup', 'back',
    'main', 'service', 'permit', 'building', 'construction', 'project',
    'unit', 'phase', 'model', 'sunrun', 'sunpower', 'vivint', 'sunnova',
    'otc', 'ac', 'dc', 'mpu', 'buss', 'breaker', 'reroof', 'installation',
    'correction', 'corrections', 'review', 'applied', 'issued', 'finaled',
    'repair', 'replace', 'replacement', 'dedicated', 'existing',
    'st', 'ave', 'av', 'blvd', 'dr', 'ln', 'rd', 'ct', 'pl', 'way', 'ter',
    'cir', 'loop', 'pkwy', 'hwy', 'fwy', 'expy', 'north', 'south', 'east', 'west',
}


def _looks_like_name_word(word):
    if not word or len(word) < 2:
        return False
    if word.lower() in _NOT_NAME_WORDS:
        return False
    if not word[0].isupper():
        return False
    if any(c.isdigit() for c in word):
        return False
    if re.match(r'^[A-Z]{2,}$', word) and len(word) > 3:
        return False
    return True


def extract_homeowner_name(description='', project_name=''):
    if project_name and project_name.strip():
        pn = project_name.strip()
        m = re.match(r'^([A-Z][a-zA-Z\'-]+),\s*([A-Z][a-zA-Z\'-]+)', pn)
        if m:
            last, first = m.group(1), m.group(2)
            if _looks_like_name_word(first) and _looks_like_name_word(last):
                return first, last
        words = re.split(r'[\s_]+', pn)
        name_words = [w for w in words[:3] if _looks_like_name_word(w)]
        non_name = [w for w in words[:len(name_words) + 1]
                    if not _looks_like_name_word(w) and w not in (',', '-', '_')]
        if len(name_words) >= 2 and len(non_name) == 0:
            return name_words[0], ' '.join(name_words[1:])
        if len(words) >= 3 and not _looks_like_name_word(words[0]):
            rest = [w for w in words[1:3] if _looks_like_name_word(w)]
            if len(rest) >= 2:
                return rest[0], ' '.join(rest[1:])

    if description and description.strip():
        desc = description.strip()
        words = desc.split()
        if not words or not _looks_like_name_word(words[0]):
            return '', ''
        name_words = []
        for word in words:
            clean = re.sub(r'[^a-zA-Z\-\' ]', '', word).strip()
            if _looks_like_name_word(clean):
                name_words.append(clean)
            else:
                break
            if len(name_words) == 3:
                break
        if len(name_words) >= 2:
            return name_words[0], ' '.join(name_words[1:])

    return '', ''


def parse_system_size(text, max_kw: float = 8000.0):
    if not text:
        return ''
    for m in re.finditer(
        r'(\d+\.?\d*)\s*(kwp|kwh|kw|kip)\b', text, re.IGNORECASE
    ):
        try:
            val = float(m.group(1))
        except ValueError:
            continue
        if val <= 0 or val > max_kw:
            continue
        unit = m.group(2).lower()
        if unit == 'kwp':
            unit = 'kW'
        elif unit == 'kwh':
            unit = 'kWh'
        elif unit == 'kip':
            unit = 'kW'
        else:
            unit = 'kW'
        return f'{m.group(1)} {unit}'
    return ''
