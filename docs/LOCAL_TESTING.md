# Local scraping (Playwright)

## Why runs fail in some environments

1. **Sandbox / restricted agent terminal** — Playwright cannot download browsers or launch Chromium → `Executable doesn't exist` or command **Aborted**.
2. **Fix:** run commands with **full permissions** (in Cursor: approve “all” / disable sandbox for the terminal). Your own Terminal.app / iTerm does not have this issue.

## One-time setup

```bash
cd /path/to/Scrappy-main
python3 -m playwright install chromium
```

## Batch test (≤3 days, writes JSON)

```bash
python3 scripts/local_batch_scrape.py
```

Outputs under `test_results/` (gitignored). Override window (still capped in script):

```bash
SCRAPE_MAX_DAYS=3 python3 scripts/local_batch_scrape.py
```

## Single city smoke test

```bash
python3 -c "
from datetime import datetime, timedelta
from scraper_accela import scrape_accela
end = datetime.now().replace(hour=0,minute=0,second=0,microsecond=0)
start = end - timedelta(days=2)
fmt = '%m/%d/%Y'
leads = scrape_accela('chula_vista', start.strftime(fmt), end.strftime(fmt))
print(len(leads), 'leads')
"
```

Use the same `cd` and permission model as above.
