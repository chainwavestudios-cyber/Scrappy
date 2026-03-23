# Cursor session summary — Scrappy / Base44 / Render (2026-03-22)

> This file is a **hand-written summary** of this chat, not an automatic full transcript.  
> For a verbatim export, use Cursor’s chat UI (export/share if your build supports it).

## Where to find things

| What | Where |
|------|--------|
| **This summary** | Repo: `chathistory/2026-03-22-cursor-session-summary.md` |
| **Other notes you save** | Same folder: `Scrappy-main/chathistory/` |
| **Cursor’s own transcript data** | On your Mac, under Cursor’s app data (path varies by version). In-project metadata may live under `.cursor/` in the project or under `~/.cursor/projects/<project-hash>/` — look for “agent” or “transcript” files if you need raw logs. |

---

## Topics covered (chronological themes)

### San Diego & scraping
- San Diego runs on **Render** via `POST /runscan/sync` → `runscan_core` → `scraper_accela` (keys `san_diego_residential`, `san_diego_commercial`; aliases `sandiego`, `sd`, etc.).
- Local Playwright failed without `playwright install chromium`.
- **OTC / project name:** permit-type step was timing out on `networkidle`; project name used silent `fill` + `except`. **Fixed:** `_inject_search_project_name`, replaced `networkidle` with shorter waits, `use_project_name: 'OTC'`, iframe CSV `expect_download` uses parent `Page`.
- **Chula Vista** remote curl worked (5 days, 3 leads). **San Diego** combined run hit **502** (proxy timeout); split runs; residential 1d Sunday → empty grid / timeout on results rows.

### Repo review
- **`get_scraper('san_diego')`** pointed at missing `scrape_permits` — broken for legacy `/scrape*`; **`/runscan/sync`** path is correct for Accela SD.
- Duplicate **`scraper.py`** vs **`scraper_accela.py`** noted.

### Chathistory folder
- Created **`chathistory/`** for optional pasted exports; explained Cursor **rules** vs **memory** vs chat persistence.

### Base44 / platform integration
- **`post_to_base44`:** adds `organization_id` (request → env → hardcoded **`HARDCODED_BASE44_ORGANIZATION_ID`** = `69ac768167fa5ab007eb6ae8`), `campaignId`, `cityKey`, `uniqueId`, etc.; POST to `ingestSolarPermits` with `x-internal-secret` (`INTERNAL_SECRET`).
- **`/scrape/campaign`:** accepts `organizationId`, threads → later **sequential cities** + **`_PLAYWRIGHT_LOCK`** so concurrent campaigns don’t overlap Playwright.
- **`/scrape/campaign`** now uses **`_check_internal_secret()`** when `INTERNAL_SECRET` is set (same as `/runscan/sync`).
- **`GET /campaign/cities`** for UI key sync.
- **`docs/PLATFORM_TRIGGER.md`** rewritten: trigger, **immediate HTTP response** vs **async ingest**, dates `MM/DD/YYYY`, curl, Deno example, env table.
- **`docs/BASE44.md`** links and San Diego two-key guidance.

### Logs / concurrent campaigns
- Two campaign IDs hitting Chula Vista at once caused interleaved logs; **fix:** global lock + one background thread running cities sequentially per request.

### Git
- Pushed multiple commits (`3c08a25`, `56dec93`, `6748751`, `42195a1`, `2e8f7b0`, etc.) — confirm on `origin/main` for exact history.

### User-provided snippets (not stored verbatim here)
- Base44 **`ingestSolarPermits`** webhook spec (leads, `organization_id`, `campaign_id`, etc.).
- React **`SolarPermitCampaignModal`** / **`SetupTab`** — CITIES list, `runPermitCampaign` on save, `dateRangeMode` same_day vs custom.

---

## Quick reference — URLs & env

- **Trigger (prod):** `POST {SCRAPPY_URL}/scrape/campaign`
- **Test export:** `POST {SCRAPPY_URL}/runscan/sync`
- **City catalog:** `GET {SCRAPPY_URL}/campaign/cities`
- **Render example host (verify in dashboard):** `https://scrappy-au2o.onrender.com`
- **Render:** `BASE44_ENABLED`, `INTERNAL_SECRET`, optional `BASE44_ORGANIZATION_ID`
- **Base44 caller:** `SCRAPPY_URL`, `SCRAPPY_INTERNAL_SECRET` (match `INTERNAL_SECRET` when enforced)

---

*End of summary. Add more dated files under `chathistory/` anytime.*
