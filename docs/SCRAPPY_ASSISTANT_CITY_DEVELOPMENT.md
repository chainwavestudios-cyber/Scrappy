# Scrappy — Assistant guide: new Accela cities (staging / no production DB)

This document is for a **contractor or assistant** who mirrors the **Scrappy** GitHub repo, uses **Cursor**, and deploys to a **dedicated Render service** for testing.  
**Goal:** produce `cities/<name>.py` configs that are nearly production-ready, without touching **production Base44** or any production database.

**Staging Render base URL (assistant):** `https://scrapy1.onrender.com`  
**Production** uses a different URL — never point staging at production secrets.

---

## 1. What you are building

| Deliverable | Where |
|-------------|--------|
| New city module | `cities/<city_key>.py` — one or more entries in `CONFIGS = { ... }` |
| Short test notes | Portal URL, permit type string (exact), date-range search works Y/N, column indices if not default |
| Optional | Screenshot or pasted HTML snippet of result grid headers (for column mapping) |

**You do not** merge to production yourself unless asked. You hand off the final `cities/*.py` file(s) for the lead to copy into the production repo.

---

## 2. Repo and sync

1. Clone the same **Scrappy** repository the team uses (fork or direct clone).
2. Keep **`main`** aligned with upstream before starting a city: `git pull origin main`.
3. Work in a **branch**: `git checkout -b city/riverside` (example).

---

## 3. No database / no Base44 from staging

### 3.1 How Scrappy talks to Base44 (production concern)

- **`scraper_accela.py`** only returns **Python lists of dicts** (leads). It **does not** call HTTP APIs or databases.
- **`app.py`** sends leads to Base44 only inside **`post_to_base44()`**, which runs when:
  - `BASE44_ENABLED` is **`true`** in the Render environment, **and**
  - the async routes **`/scrape`**, **`/scrape/daily`**, or **`/scrape/campaign`** run **`run_and_post()`** (which calls `post_to_base44`).

### 3.2 Safe endpoints for testing (JSON only, no ingest)

These paths **run the scraper** and return **JSON in the HTTP response**. They **do not** call `post_to_base44`:

| Method | Path | Purpose |
|--------|------|---------|
| `POST` | `/scrape/sync` | Single city, fixed `startDate` / `endDate` — full lead array in response |
| `POST` | `/runscan/sync` | Multi-city, `days` + `cities[]` — payload includes `leads` |

**Prefer these** for validating a new city on Render.

### 3.3 Render environment — **mandatory** for `scrapy1.onrender.com`

Set (or verify):

```bash
BASE44_ENABLED=false
```

Leave **`INTERNAL_SECRET`** either **unset** or use a **staging-only** random string (not the production secret).  
If `INTERNAL_SECRET` is set, protected routes require header `x-internal-secret: <same value>`.

Confirm after deploy:

```bash
curl -sS https://scrapy1.onrender.com/health
```

Expect: `"base44_enabled": false`.

---

## 4. Optional “belt and suspenders” patches (assistant fork only)

Use these **only on the assistant’s clone** if you want code-level guarantees even if someone toggles env vars wrong.

### 4.1 `app.py` — force-disable Base44

**Location:** near the existing line:

```python
BASE44_ENABLED = os.environ.get('BASE44_ENABLED', 'false').lower() == 'true'
```

**Replace with:**

```python
# STAGING / ASSISTANT INSTANCE — never enable Base44 ingest from this service.
BASE44_ENABLED = False
```

(Optional: use an env override only on production by keeping two branches; on staging branch hard-code `False`.)

### 4.2 `app.py` — skip `post_to_base44` inside `run_and_post`

**Location:** function `run_and_post` — after `print(f'Scraped {len(leads)} leads from {city}')`.

**Insert before** `post_to_base44(...)`:

```python
        # When SCRAPPY_LOCAL_ONLY=true, skip Base44 (use on scrapy1 only)
        if os.environ.get('SCRAPPY_LOCAL_ONLY', 'false').lower() == 'true':
            return leads
```

On **scrapy1**, set:

```bash
SCRAPPY_LOCAL_ONLY=true
```

On **production**, **omit** this variable or set:

```bash
SCRAPPY_LOCAL_ONLY=false
```

Default is `false`, so a mistaken merge of this snippet alone will **not** disable production ingest unless env is set.

### 4.3 `scraper_accela.py`

**No change is required** for “local-only output”: the module already only returns data to its caller.  
Optional: add a comment at the top of the file in your branch:

```python
# Assistant/staging note: this file does not call Base44; app.py controls ingest via BASE44_ENABLED / run_and_post.
```

---

## 5. Creating a city config

### 5.1 Start from the template

Copy in the Scrappy repo:

```text
cities/_template.py.example  →  cities/<your_city>.py
```

Remove the `.example` suffix; use a **snake_case** filename (e.g. `riverside.py`).

### 5.2 Required fields (minimum)

```python
CONFIGS = {
    'riverside': {   # city_key — used in APIs and uniqueId; snake_case
        'name':        'Riverside',   # human label
        'base_url':    'https://aca-prod.accela.com/RIVERSIDE',
        'module':      'Building',
        'permit_type': 'Residential Solar',  # must match portal dropdown EXACTLY, or None
        'source':      'riverside_accela', # stable id for uniqueId / analytics
    },
}
```

### 5.3 Common optional fields

| Key | When to set |
|-----|-------------|
| `portal_url` | Entry URL is not default `Cap/CapHome` (e.g. county `Default.aspx` — see `cities/san_diego.py`) |
| `skip_csv_download` | `True` if CSV export breaks; force HTML grid |
| `skip_detail_fetch` | `True` if all fields are on the search grid (see `cities/downey.py`) |
| `owner_from_contacts` | `True` if owner/email come from Contacts tab (San Diego–style) |
| `require_primary_scope_contains` | List of substrings to filter non-solar permits on detail page |
| `col_date`, `col_permit_num`, `col_permit_type`, `col_description`, `col_address`, `col_status`, `col_project_name` | When grid column order differs from scraper defaults |
| `short_notes_filter` | Substring that must appear in Short Notes column (pre-filter) |
| `lead_category` | `'residential'` or `'commercial'` |

Read **`cities/README.md`** in the repo for the full list and behavior.

### 5.4 Discover permit type labels (existing cities)

For a city **already** in `CITY_CONFIGS`, the Flask app exposes:

```text
GET https://scrapy1.onrender.com/discover/<city_key>
```

Returns dropdown options and a suggested solar-related label.

---

## 6. Local testing (laptop, no Render)

From repo root, with Python + Playwright + Chromium installed:

```bash
pip install -r requirements.txt
playwright install chromium

# Smoke-test one city, last 7 days → ./output/scrape_<city>_<timestamp>.json
python3 test_city_local.py riverside

# Fixed date range
python3 test_city_local.py riverside --range 03/01/2026 03/20/2026 -o /tmp/riverside.json
```

**`test_city_local.py`** never calls Base44; it only writes a JSON file.

### Permit portal recon (optional)

```bash
python3 permit_recon_spider.py --census 50 --list-only --targets-out targets.json
```

Helps build a wide list of candidate URLs; **AccelaGuess** URLs are often wrong — verify in browser.

---

## 7. Testing on Render (`scrapy1.onrender.com`)

### 7.1 Health

```bash
curl -sS https://scrapy1.onrender.com/health
```

### 7.2 List registered city keys (after your deploy)

```bash
curl -sS https://scrapy1.onrender.com/campaign/cities
```

### 7.3 Single city sync scrape (best for new city QA)

```bash
curl -sS -X POST https://scrapy1.onrender.com/scrape/sync \
  -H "Content-Type: application/json" \
  -d '{
    "city": "riverside",
    "startDate": "03/01/2026",
    "endDate": "03/20/2026"
  }' | jq '.count, .success'
```

If `INTERNAL_SECRET` is set on the service, add:

`-H "x-internal-secret: YOUR_STAGING_SECRET"`

### 7.4 Multi-city runscan (alias tokens)

```bash
curl -sS -X POST https://scrapy1.onrender.com/runscan/sync \
  -H "Content-Type: application/json" \
  -H "x-internal-secret: YOUR_STAGING_SECRET" \
  -d '{"days": 3, "cities": ["riverside"]}'
```

**Note:** `MAX_CITIES_PER_JOB` on Render may cap how many cities per request (default often `5`).

---

## 8. Cursor — prompt you can paste (rules for the AI)

Copy everything inside the fence into a **Cursor rule**, **project `AGENTS.md`**, or the chat when starting work:

```markdown
You are helping implement new Accela Citizen Access city configs for the Scrappy Python repo.

Constraints:
- Only add or edit files under `cities/` unless explicitly asked to change shared scraper logic.
- Match existing style in `cities/chula_vista.py`, `cities/downey.py`, `cities/san_diego.py`.
- `permit_type` must match the portal dropdown label exactly (copy from UI).
- `source` must be stable and unique (e.g. `riverside_accela`).
- Prefer `test_city_local.py <city_key>` for validation; do not add Base44 or external API calls.
- If the grid has non-default column order, set `col_*` indices and document them in a comment.
- If detail pages add no value, consider `skip_detail_fetch: True` like Downey.
- Never commit production `INTERNAL_SECRET` or enable `BASE44_ENABLED` on staging.

When done, output the full contents of the new `cities/<file>.py` for handoff.
```

---

## 9. Handoff checklist (to production team)

- [ ] `cities/<name>.py` committed on a branch; no accidental edits to `app.py` / `scraper_accela.py` unless agreed  
- [ ] `GET /campaign/cities` on staging shows the new `key`  
- [ ] `POST /scrape/sync` returns `success: true` and plausible `leads` for a known date window  
- [ ] `/health` shows `base44_enabled: false` on **scrapy1**  
- [ ] Short note: permit type string, any `portal_url`, and column overrides  
- [ ] Production merge: ensure **`BASE44_ENABLED`** and **`SCRAPPY_LOCAL_ONLY`** (if used) are correct on **production** Render only  

---

## 10. Quick reference — files

| File | Role |
|------|------|
| `cities/*.py` | City configs — **primary deliverable** |
| `scraper_accela.py` | Shared Accela scraper (avoid casual edits) |
| `app.py` | HTTP API, Base44 gate |
| `test_city_local.py` | Local JSON-only scrape |
| `runscan.py` / `runscan_core.py` | Multi-city scan logic |
| `permit_recon_spider.py` | Optional portal discovery at scale |
| `cities/README.md` | Config field documentation |

---

## 11. Support

Questions about **production** ingest, Base44 entity fields, or **Scraper-Audited** UI go to the project lead.  
This guide is scoped to **Scrappy city configs + staging Render safety**.
