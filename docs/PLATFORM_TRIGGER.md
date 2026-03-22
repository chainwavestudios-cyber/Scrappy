# Calling Scrappy from your platform (scheduling stays on Base44)

Scrappy does **not** run a cron. Your platform’s scheduler (hourly, every N hours, etc.) should call the HTTP endpoint below with values taken from the user’s **PermitCampaign** (or equivalent) record.

---

## Production path: scrape + Base44 ingest

**Endpoint**

`POST https://<YOUR_RENDER_SERVICE>/scrape/campaign`

**Content-Type:** `application/json`

**Body (JSON)** — all fields the user / campaign can control:

| Field | Required | Type | Description |
|-------|----------|------|-------------|
| `campaignId` | **yes** | string | Base44 `PermitCampaign` id — attached to each lead as `campaignId` and sent to ingest as `campaign_id`. |
| `cities` | **yes** | string[] | Scraper keys, e.g. `chula_vista`, `san_diego_residential`, `san_diego_commercial`. Exact list: `GET https://<render>/campaign/cities`. |
| `days` | no* | int | Lookback: inclusive window ending **today** (default `3`). Ignored if `startDate` + `endDate` are set. |
| `startDate` | no* | string | With `endDate`: fixed range, format **`MM/DD/YYYY`** (Accela). |
| `endDate` | no* | string | Same. |
| `organizationId` | no | string | Per-lead `organization_id` for `ingestSolarPermits`. If omitted, Scrappy uses env default / `BASE44_ORGANIZATION_ID`. |

\* Provide either **`days`** (rolling lookback) **or** **`startDate` + `endDate`** (custom). If both styles are sent, **custom dates win** when both `startDate` and `endDate` are present.

**Response (immediate):** `202`-style “started” JSON — scrapes run in **background threads**; ingest happens when each city finishes. This is **not** a synchronous list of leads.

**Auth:** `/scrape/campaign` does **not** currently validate `x-internal-secret` (unlike `/runscan/sync`). Lock it down with a private URL, allowlist, or add a header check in `app.py` if the service is exposed.

---

## Example: Base44 server function (JavaScript)

Replace env vars with your Render URL and optional shared secret if you add auth in front of Scrappy.

```javascript
/**
 * Call from a scheduled Base44 function. Parameters map 1:1 from your campaign entity.
 */
export async function triggerScrappyCampaign(campaign) {
  const url = `${process.env.SCRAPPY_URL}/scrape/campaign`;
  const body = {
    campaignId: campaign.id,
    cities: campaign.cities.split(',').map((s) => s.trim()).filter(Boolean),
    organizationId: campaign.organizationId || process.env.DEFAULT_ORG_ID,
  };

  if (campaign.dateRangeMode === 'custom' && campaign.customStartDate && campaign.customEndDate) {
    body.startDate = formatToAccelaDate(campaign.customStartDate); // YYYY-MM-DD -> MM/DD/YYYY
    body.endDate = formatToAccelaDate(campaign.customEndDate);
  } else {
    body.days = Number(campaign.days) || 3;
  }

  const headers = { 'Content-Type': 'application/json' };
  if (process.env.SCRAPPY_INTERNAL_SECRET) {
    headers['x-internal-secret'] = process.env.SCRAPPY_INTERNAL_SECRET;
  }

  const res = await fetch(url, { method: 'POST', headers, body: JSON.stringify(body) });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.error || res.statusText);
  return data;
}

/** Input: "2026-03-15" (date input) -> "03/15/2026" */
function formatToAccelaDate(isoDate) {
  const [y, m, d] = isoDate.split('-');
  return `${m}/${d}/${y}`;
}
```

`runFrequencyHours` on the campaign is **only** used on the platform side to decide **how often** to invoke the function above — it is **not** sent to Scrappy.

---

## Example: `curl`

```bash
curl -sS -X POST "https://YOUR_RENDER.onrender.com/scrape/campaign" \
  -H "Content-Type: application/json" \
  -d '{
    "campaignId": "PERMIT_CAMPAIGN_UUID",
    "organizationId": "69ac768167fa5ab007eb6ae8",
    "days": 3,
    "cities": ["chula_vista", "san_diego_residential"]
  }'
```

Custom dates:

```bash
-d '{
  "campaignId": "PERMIT_CAMPAIGN_UUID",
  "startDate": "03/15/2026",
  "endDate": "03/22/2026",
  "cities": ["chula_vista"]
}'
```

---

## Test-only: JSON export, no Base44 ingest

`POST https://<render>/runscan/sync` — returns `leads` in the response. Requires **`x-internal-secret`** when `INTERNAL_SECRET` is set on Render. Use for debugging, not for production ingest unless you post leads yourself.

See `GET https://<render>/runscan` for a short JSON help payload.

---

## Render environment (ingest)

| Variable | Purpose |
|----------|---------|
| `BASE44_ENABLED` | `true` to POST leads to `ingestSolarPermits`. |
| `INTERNAL_SECRET` | Sent as `x-internal-secret` to Base44 ingest (not automatically checked on `/scrape/campaign` today). |
| `BASE44_ORGANIZATION_ID` | Optional override; if unset, Scrappy uses hardcoded default `69ac768167fa5ab007eb6ae8` in `app.py` (`HARDCODED_BASE44_ORGANIZATION_ID`). |
