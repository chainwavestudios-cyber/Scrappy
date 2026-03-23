# Scrappy ↔ Base44: trigger, HTTP response, and ingest

Scrappy on Render **does not schedule** jobs. Your Base44 app (cron, `runPermitCampaign`, etc.) **calls Scrappy**; Scrappy scrapes Accela, then **calls Base44** `ingestSolarPermits` with the lead payload.

---

## 1. Trigger (what your platform sends)

**Method & URL**

| | |
|--|--|
| Method | `POST` |
| URL | `{SCRAPPY_URL}/scrape/campaign` |
| Example `SCRAPPY_URL` | `https://scrappy-au2o.onrender.com` (confirm in Render; no trailing slash) |

**Headers**

| Header | Value |
|--------|--------|
| `Content-Type` | `application/json` |
| `x-internal-secret` | **Required** when Render env `INTERNAL_SECRET` is set — same string as Base44 uses for ingest. In Base44 env: `SCRAPPY_INTERNAL_SECRET`. |

**JSON body**

| Field | Required | Type | Notes |
|-------|----------|------|--------|
| `campaignId` | yes | string | Base44 `PermitCampaign` id → each lead gets `campaignId`; ingest body gets `campaign_id`. |
| `cities` | yes | string[] | Scraper keys only, e.g. `chula_vista`, `san_diego_residential`, `san_diego_commercial`. List: `GET {SCRAPPY_URL}/campaign/cities`. |
| `days` | no† | int | Rolling window ending **today**, inclusive (default `3`). |
| `startDate` | no† | string | **`MM/DD/YYYY`** only (e.g. `03/22/2026`). |
| `endDate` | no† | string | **`MM/DD/YYYY`**, with `startDate`. |
| `organizationId` | no | string | Per-lead `organization_id`. If omitted, Scrappy uses `BASE44_ORGANIZATION_ID` env or code default. |

† Use **`days`** *or* **`startDate` + `endDate`**. If both `startDate` and `endDate` are present, **custom dates win**; `days` is ignored for range calculation.

**Date rules for your UI**

- `<input type="date">` values are `YYYY-MM-DD`. Convert to **`MM/DD/YYYY`** before sending to Scrappy.
- Scrappy passes those strings straight into Accela search.

---

## 2. Immediate HTTP response (what Scrappy returns to the caller)

Status is usually **200** with JSON (Flask does not use 202 by default). The body **does not** contain leads.

**Example success body**

```json
{
  "status": "started",
  "campaignId": "69c0b80b78d6cc8c69af1ec9",
  "cities": ["chula_vista"],
  "startDate": "03/16/2026",
  "endDate": "03/22/2026",
  "days": 7,
  "organizationId": null,
  "base44": "enabled"
}
```

| Key | Meaning |
|-----|---------|
| `status` | `"started"` — work was queued on the server. |
| `cities` | Echo of requested keys (normalized to strings). |
| `startDate` / `endDate` | Actual window used (`MM/DD/YYYY`). |
| `days` | Echo of request `days` (range may still be from custom dates). |
| `organizationId` | Echo of body `organizationId` if sent. |
| `base44` | `"enabled"` if `BASE44_ENABLED=true` on Render (ingest will be attempted); `"disabled"` otherwise. |

**Error examples**

- `400` — missing `campaignId` / `cities`, or too many cities (`MAX_CITIES_PER_JOB`).
- `401` — `INTERNAL_SECRET` set on Render but `x-internal-secret` missing or wrong.

---

## 3. What happens after the response (async behavior)

1. One **background thread** runs **all `cities` in order** (not in parallel).
2. A **process-wide lock** allows only **one Playwright scrape** at a time. A second `/scrape/campaign` while the first is running **waits** (no overlapping browsers on the same worker).
3. For each city: scrape → then **`post_to_base44`** (if `BASE44_ENABLED=true` and secret set).

Failures during scrape are logged on Render; the original HTTP client does not get a retry or webhook from Scrappy.

---

## 4. Outbound ingest (Scrappy → Base44 “webhook”)

Scrappy **POSTs** to your Base44 function URL, e.g.  
`https://{domain}/api/apps/{appId}/functions/ingestSolarPermits`

**Headers**

- `Content-Type: application/json`
- `x-internal-secret: {INTERNAL_SECRET from Render}` (must match what the function expects)

**Body**

```json
{
  "leads": [ { "...": "permit fields + Scrappy additions" } ],
  "campaign_id": "<campaignId from trigger or empty string>"
}
```

**Fields Scrappy adds or normalizes on each lead** (among others from the scraper):

| Field | Source |
|-------|--------|
| `organization_id` | Request `organizationId` → env → hardcoded default in `app.py` |
| `cityKey` | Scraper city key (e.g. `chula_vista`) |
| `city` | Human label derived from key |
| `state` | `CA` |
| `uniqueId` | `{cityKey}_{permitNumber}` |
| `campaignId` | From trigger, if provided |
| `enrichmentStage` | `scraped` |
| `scrapedAt` | ISO timestamp |

Optional fields (`permitNumber`, `address`, `homeownerFirstName`, etc.) come from the scraper when available.

---

## 5. Reference: `curl`

```bash
export SCRAPPY_URL="https://scrappy-au2o.onrender.com"
export SCRAPPY_INTERNAL_SECRET="your-secret"

curl -sS -X POST "$SCRAPPY_URL/scrape/campaign" \
  -H "Content-Type: application/json" \
  -H "x-internal-secret: $SCRAPPY_INTERNAL_SECRET" \
  -d '{
    "campaignId": "PERMIT_CAMPAIGN_UUID",
    "organizationId": "69ac768167fa5ab007eb6ae8",
    "days": 3,
    "cities": ["chula_vista"]
  }'
```

Custom range:

```bash
curl -sS -X POST "$SCRAPPY_URL/scrape/campaign" \
  -H "Content-Type: application/json" \
  -H "x-internal-secret: $SCRAPPY_INTERNAL_SECRET" \
  -d '{
    "campaignId": "PERMIT_CAMPAIGN_UUID",
    "startDate": "03/15/2026",
    "endDate": "03/22/2026",
    "cities": ["chula_vista"]
  }'
```

---

## 6. Reference: Base44 / Deno-style caller

```javascript
export async function triggerScrappyCampaign(campaign) {
  const url = `${Deno.env.get('SCRAPPY_URL')}/scrape/campaign`;
  const body = {
    campaignId: campaign.id,
    cities: String(campaign.cities || '')
      .split(',')
      .map((s) => s.trim())
      .filter(Boolean),
    organizationId: campaign.organizationId || Deno.env.get('DEFAULT_ORG_ID'),
  };

  if (campaign.dateRangeMode === 'custom' && campaign.customStartDate && campaign.customEndDate) {
    body.startDate = toAccelaDate(campaign.customStartDate);
    body.endDate = toAccelaDate(campaign.customEndDate);
  } else {
    body.days = Number(campaign.days) || 3;
  }

  const headers = { 'Content-Type': 'application/json' };
  const secret = Deno.env.get('SCRAPPY_INTERNAL_SECRET');
  if (secret) headers['x-internal-secret'] = secret;

  const res = await fetch(url, { method: 'POST', headers, body: JSON.stringify(body) });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.error || `${res.status} ${res.statusText}`);
  return data;
}

/** "2026-03-15" -> "03/15/2026" */
function toAccelaDate(isoDate) {
  const [y, m, d] = isoDate.split('-');
  return `${m}/${d}/${y}`;
}
```

`runFrequencyHours` is **not** sent to Scrappy — use it only in your scheduler to decide how often to call this function.

---

## 7. Test-only: `POST /runscan/sync`

Returns a **single JSON payload** with `leads`, `runs`, `meta`, etc. Does **not** post to Base44.

- Requires `x-internal-secret` when `INTERNAL_SECRET` is set.
- Good for manual / QA exports; production ingest should use `/scrape/campaign`.

`GET {SCRAPPY_URL}/runscan` returns a short JSON help object.

---

## 8. Render environment

| Variable | Role |
|----------|------|
| `BASE44_ENABLED` | `true` → after each city scrape, POST `ingestSolarPermits`. |
| `INTERNAL_SECRET` | Outbound ingest auth; also **inbound** auth for `/scrape/campaign` and `/runscan/sync` when set. |
| `INTERNAL_SECRET` (Base44 function) | Must match — same secret for **trigger** and **ingest** if you use one key everywhere. |
| `BASE44_ORGANIZATION_ID` | Optional override for default `organization_id` on leads. |
| Code default | `HARDCODED_BASE44_ORGANIZATION_ID` in `app.py` if env / request omit org. |

---

## 9. UI / product notes

- **Avoid double fire:** saving the campaign twice or calling `runPermitCampaign` twice quickly creates **two** Scrappy jobs; they will **queue** (lock) but still run twice.
- **San Diego:** use keys `san_diego_residential` and `san_diego_commercial`, not a single generic `sandiego`, unless you intentionally want both streams in one job (heavier).
- **City list:** sync checkbox keys from `GET /campaign/cities` so labels and keys stay aligned with Scrappy.
