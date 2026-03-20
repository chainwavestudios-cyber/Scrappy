# City configs

One file per city (or city group). Adding a new city = add a new file here. A syntax error in one file won't break the others.

## Adding a new city

1. Copy `_template.py.example` to `cities/<city_name>.py`
2. Fill in the config dict (base_url, permit_type, etc.)
3. Run your scraper — the new city is auto-discovered

## Config structure

Each file must define `CONFIGS = {...}`. Keys are city identifiers (e.g. `chula_vista`, `oakland_solarapp`).

Required fields: `name`, `base_url`, `module`, `source`

Optional: `permit_type`, `portal_url` (entry page when it’s not the standard `Cap/CapHome` URL — e.g. San Diego County), `col_date`, `col_permit_num`, `lead_category`, etc. See existing city files for examples.

## Run multi-city scan on Render (production Playwright)

From your laptop (writes JSON locally):

```bash
python runscan.py --remote https://YOUR-SERVICE.onrender.com 4 sandiego chulavista scanoutput.txt
# If INTERNAL_SECRET is set on Render:
export INTERNAL_SECRET=your_secret
```

Or `curl`:

```bash
curl -sS -X POST https://YOUR-SERVICE.onrender.com/runscan/sync \
  -H "Content-Type: application/json" \
  -H "x-internal-secret: YOUR_SECRET" \
  -d '{"days":4,"cities":["sandiego","chulavista"]}' > scanoutput.txt
```
