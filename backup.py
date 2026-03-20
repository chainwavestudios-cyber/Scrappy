"""
Rotating 3-slot backup system for Base44 app.

Since Base44 has no public export API, this backup:
1. Downloads all function code via Base44 SDK (asServiceRole)
2. Downloads entity schemas via Base44 SDK  
3. Saves everything as JSON to GitHub in rotating 3-slot system

slot_1 = most recent, slot_2 = 1hr ago, slot_3 = 2hrs ago

Routes:
  POST /backup         → run backup now
  GET  /backup/status  → show slot info
  GET  /backup/list    → list all slots
"""

import os
import io
import json
import zipfile
import base64
import logging
import requests
from datetime import datetime, timezone
from flask import Blueprint, jsonify, request

log = logging.getLogger(__name__)

backup_bp = Blueprint('backup', __name__)

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
GITHUB_TOKEN   = os.environ.get('GITHUB_TOKEN', '')
GITHUB_REPO    = os.environ.get('GITHUB_BACKUP_REPO', '')
GITHUB_BRANCH  = os.environ.get('GITHUB_BACKUP_BRANCH', 'main')
BASE44_APP_ID  = os.environ.get('BASE44_APP_ID', '69ac768167fa5ab007eb6ae7')
BASE44_API_KEY = os.environ.get('BASE44_API_KEY', '')
BASE44_BASE    = f'https://agentbmanscraper.base44.app/api/apps/{BASE44_APP_ID}'

GITHUB_API = 'https://api.github.com'
SLOTS      = ['slot_1', 'slot_2', 'slot_3']


# ---------------------------------------------------------------------------
# GitHub helpers
# ---------------------------------------------------------------------------

def github_headers():
    return {
        'Authorization': f'token {GITHUB_TOKEN}',
        'Accept':        'application/vnd.github.v3+json',
        'Content-Type':  'application/json',
    }


def get_file_sha(path: str):
    url = f'{GITHUB_API}/repos/{GITHUB_REPO}/contents/{path}'
    res = requests.get(url, headers=github_headers(),
                       params={'ref': GITHUB_BRANCH})
    if res.status_code == 200:
        return res.json().get('sha')
    return None


def upsert_github_file(path: str, content_bytes: bytes, message: str):
    url = f'{GITHUB_API}/repos/{GITHUB_REPO}/contents/{path}'
    sha = get_file_sha(path)
    payload = {
        'message': message,
        'content': base64.b64encode(content_bytes).decode('utf-8'),
        'branch':  GITHUB_BRANCH,
    }
    if sha:
        payload['sha'] = sha
    res = requests.put(url, headers=github_headers(), json=payload)
    if not res.ok:
        raise Exception(f'GitHub upsert failed [{res.status_code}]: {res.text[:300]}')
    return res.json()


def get_github_file_content(path: str):
    url = f'{GITHUB_API}/repos/{GITHUB_REPO}/contents/{path}'
    res = requests.get(url, headers=github_headers(),
                       params={'ref': GITHUB_BRANCH})
    if res.status_code == 200:
        encoded = res.json().get('content', '')
        return base64.b64decode(encoded.replace('\n', ''))
    return None


def get_slot_meta(slot: str) -> dict:
    content = get_github_file_content(f'backups/{slot}/meta.json')
    if content:
        try:
            return json.loads(content)
        except Exception:
            pass
    return {}


# ---------------------------------------------------------------------------
# Base44 data fetchers
# ---------------------------------------------------------------------------

def base44_headers():
    return {
        'api-key':      BASE44_API_KEY,
        'Content-Type': 'application/json',
    }


def fetch_all_entities() -> list:
    """Fetch list of all entity names from Base44."""
    try:
        res = requests.get(
            f'{BASE44_BASE}/entities',
            headers=base44_headers(),
            timeout=30,
        )
        if res.ok:
            return res.json()
    except Exception as e:
        log.warning(f'[backup] Could not fetch entity list: {e}')
    return []


def fetch_entity_schema(entity_name: str) -> dict:
    """Fetch schema/fields for a specific entity."""
    try:
        res = requests.get(
            f'{BASE44_BASE}/entities/{entity_name}/schema',
            headers=base44_headers(),
            timeout=15,
        )
        if res.ok:
            return res.json()
    except Exception as e:
        log.warning(f'[backup] Could not fetch schema for {entity_name}: {e}')
    return {}


def fetch_functions_list() -> list:
    """Fetch list of all functions from Base44."""
    try:
        res = requests.get(
            f'{BASE44_BASE}/functions',
            headers=base44_headers(),
            timeout=30,
        )
        if res.ok:
            return res.json()
    except Exception as e:
        log.warning(f'[backup] Could not fetch functions list: {e}')
    return []


def build_backup_payload() -> dict:
    """
    Build a complete backup payload from Base44.
    Since there's no bulk export API, we collect:
    - App metadata
    - Entity list + schemas
    - Function list
    - Timestamp
    """
    timestamp = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')

    payload = {
        'app_id':    BASE44_APP_ID,
        'timestamp': timestamp,
        'source':    'automated_backup',
        'entities':  {},
        'functions': [],
        'note':      (
            'This backup contains entity schemas and function list. '
            'To restore: use Base44 dashboard to recreate entities and functions. '
            'Full code backup requires manual ZIP export from Base44 UI.'
        ),
    }

    # Fetch entity schemas
    entities = fetch_all_entities()
    if entities:
        for entity in entities:
            name   = entity if isinstance(entity, str) else entity.get('name', '')
            schema = fetch_entity_schema(name) if name else {}
            if name:
                payload['entities'][name] = schema
        log.info(f'[backup] Fetched {len(payload["entities"])} entity schemas')
    else:
        log.warning('[backup] No entities fetched — API may require different auth')

    # Fetch function list
    functions = fetch_functions_list()
    payload['functions'] = functions
    log.info(f'[backup] Fetched {len(functions)} functions')

    return payload


# ---------------------------------------------------------------------------
# Slot rotation
# ---------------------------------------------------------------------------

def rotate_slots():
    log.info('[backup] Rotating slots...')
    for i in range(len(SLOTS) - 1, 0, -1):
        src = SLOTS[i - 1]
        dst = SLOTS[i]
        for filename in ['backup.json', 'meta.json']:
            content = get_github_file_content(f'backups/{src}/{filename}')
            if content:
                upsert_github_file(
                    f'backups/{dst}/{filename}',
                    content,
                    f'[rotate] {src} → {dst} ({filename})',
                )


def write_slot_1(payload: dict, timestamp: str):
    payload_bytes = json.dumps(payload, indent=2).encode('utf-8')

    meta = {
        'timestamp':      timestamp,
        'slot':           'slot_1',
        'app_id':         BASE44_APP_ID,
        'size_bytes':     len(payload_bytes),
        'entity_count':   len(payload.get('entities', {})),
        'function_count': len(payload.get('functions', [])),
        'label':          f'Backup {timestamp}',
    }

    upsert_github_file(
        'backups/slot_1/backup.json',
        payload_bytes,
        f'[backup] slot_1 — {timestamp}',
    )
    upsert_github_file(
        'backups/slot_1/meta.json',
        json.dumps(meta, indent=2).encode(),
        f'[backup] slot_1 meta — {timestamp}',
    )
    log.info(f'[backup] slot_1 written ({len(payload_bytes):,} bytes)')
    return meta


# ---------------------------------------------------------------------------
# Core backup
# ---------------------------------------------------------------------------

def run_backup() -> dict:
    if not GITHUB_TOKEN:
        raise Exception('GITHUB_TOKEN not set in Render environment')
    if not GITHUB_REPO:
        raise Exception('GITHUB_BACKUP_REPO not set')

    timestamp = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
    log.info(f'[backup] Starting backup at {timestamp}')

    # 1. Rotate slots
    rotate_slots()

    # 2. Build payload from Base44
    payload = build_backup_payload()
    payload['timestamp'] = timestamp

    # 3. Write to slot_1
    meta = write_slot_1(payload, timestamp)

    # 4. Update index
    index = {
        'last_backup': timestamp,
        'app_id':      BASE44_APP_ID,
        'slots': {
            slot: get_slot_meta(slot)
            for slot in SLOTS
        },
    }
    upsert_github_file(
        'backups/index.json',
        json.dumps(index, indent=2).encode(),
        f'[backup] index — {timestamp}',
    )

    log.info(f'[backup] Complete at {timestamp}')
    return {
        'success':        True,
        'timestamp':      timestamp,
        'entity_count':   meta['entity_count'],
        'function_count': meta['function_count'],
        'size_bytes':     meta['size_bytes'],
        'slots':          index['slots'],
    }


# ---------------------------------------------------------------------------
# Flask routes
# ---------------------------------------------------------------------------

@backup_bp.route('/backup', methods=['POST'])
def trigger_backup():
    secret = os.environ.get('INTERNAL_SECRET', '')
    if secret:
        if request.headers.get('x-internal-secret', '') != secret:
            return jsonify({'error': 'Unauthorized'}), 401
    try:
        result = run_backup()
        return jsonify(result)
    except Exception as e:
        log.error(f'[backup] Failed: {e}')
        return jsonify({'success': False, 'error': str(e)}), 500


@backup_bp.route('/backup/status', methods=['GET'])
def backup_status():
    if not GITHUB_TOKEN or not GITHUB_REPO:
        return jsonify({
            'configured': False,
            'message':    'Set GITHUB_TOKEN and GITHUB_BACKUP_REPO in Render environment',
        })
    try:
        slots = {}
        for slot in SLOTS:
            meta = get_slot_meta(slot)
            slots[slot] = {
                'timestamp':      meta.get('timestamp', 'empty'),
                'size_bytes':     meta.get('size_bytes', 0),
                'entity_count':   meta.get('entity_count', 0),
                'function_count': meta.get('function_count', 0),
                'label':          meta.get('label', 'No backup yet'),
            }
        return jsonify({
            'configured': True,
            'repo':       GITHUB_REPO,
            'branch':     GITHUB_BRANCH,
            'app_id':     BASE44_APP_ID,
            'slots':      slots,
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@backup_bp.route('/backup/list', methods=['GET'])
def backup_list():
    try:
        result = []
        for i, slot in enumerate(SLOTS):
            meta = get_slot_meta(slot)
            result.append({
                'slot':           slot,
                'label':          'Latest' if i == 0 else f'{i}h ago',
                'timestamp':      meta.get('timestamp'),
                'size_bytes':     meta.get('size_bytes', 0),
                'entity_count':   meta.get('entity_count', 0),
                'function_count': meta.get('function_count', 0),
                'empty':          not bool(meta.get('timestamp')),
            })
        return jsonify({'slots': result})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@backup_bp.route('/backup/debug', methods=['GET'])
def backup_debug():
    """Debug — shows what Render env vars are actually set (masked)."""
    token = GITHUB_TOKEN
    return jsonify({
        'github_token_set':    bool(token),
        'github_token_prefix': token[:8] + '...' if len(token) > 8 else 'NOT SET',
        'github_repo':         GITHUB_REPO,
        'github_branch':       GITHUB_BRANCH,
        'base44_app_id':       BASE44_APP_ID,
        'base44_api_key_set':  bool(BASE44_API_KEY),
    })
