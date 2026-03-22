# Base44 integration

**Copy-paste trigger code and full parameter table:** [`docs/PLATFORM_TRIGGER.md`](PLATFORM_TRIGGER.md) (platform owns scheduling; Scrappy only receives POST `/scrape/campaign`).

## PermitCampaign UI ↔ Scrappy (your template)

Your setup tab fields map to **Render (Scrappy)** like this:

| UI concept | Scrappy behavior |
|------------|------------------|
| **Cities** (checkboxes) | Must be **exact scraper keys** (e.g. `chula_vista`, `san_diego_residential`). Do **not** use a single `sandiego` token unless you intend **both** res + commercial in one job (heavy; risk timeouts). Prefer **one campaign per stream** for San Diego. |
| **Residential vs commercial** | For San Diego County: **two keys** — `san_diego_residential` and `san_diego_commercial` — usually **two campaigns** or two rows in `cities[]` if you accept one long job. |
| **Look back (days)** | `POST /scrape/campaign` body: `"days": N` (omit `startDate` / `endDate`). |
| **Custom range** | Same endpoint: `"startDate": "MM/DD/YYYY", "endDate": "MM/DD/YYYY"` (Accela format). |
| **Frequency (hours)** | Scrappy does **not** schedule this. Your **Base44** cron / scheduled function should call Render every *N* hours with the same `campaignId`, `cities`, and date mode. |
| **Campaign ID** | Pass Base44 `PermitCampaign` id as `"campaignId"` — it is copied onto each lead as `campaignId` and in the ingest root as `campaign_id`. |
| **Organization** | Pass `"organizationId": "<uuid>"` on **`/scrape/campaign`** (or set env **`BASE44_ORGANIZATION_ID`** on Render). Scrappy adds **`organization_id`** on **every lead** before calling `ingestSolarPermits`. |

### Syncing the city checklist from Render

`GET https://<your-render-service>/campaign/cities` returns:

```json
{ "cities": [ { "key": "chula_vista", "label": "Chula Vista", "leadCategory": null }, ... ] }
```

Use `key` in your stored `cities` string / array and in `POST /scrape/campaign` `cities`. You can persist `setting_key: available_cities` as a JSON array of **keys** only, then hydrate labels from this endpoint at build or admin time.

### Example: scheduled scrape → ingest shape

`POST https://<render>/scrape/campaign` (with `x-internal-secret` if you protect the service):

```json
{
  "campaignId": "<base44-permit-campaign-id>",
  "organizationId": "<base44-org-id>",
  "days": 3,
  "cities": ["chula_vista", "san_diego_residential"]
}
```

Scrappy runs Accela, then POSTs to **`ingestSolarPermits`** with body like:

```json
{
  "leads": [
    {
      "organization_id": "<same as organizationId>",
      "uniqueId": "chula_vista_<permitNumber>",
      "cityKey": "chula_vista",
      "city": "Chula Vista",
      "state": "CA",
      "campaignId": "<campaignId>",
      "enrichmentStage": "scraped",
      "scrapedAt": "<iso8601>",
      "...": "other permit fields from scraper"
    }
  ],
  "campaign_id": "<campaignId>"
}
```

### React `SetupTab` adjustments (conceptual)

1. **`CITIES` constant** — align `key` with `campaign/cities` from Render (or duplicate the list and keep in sync).
2. **Save payload** — when the user saves, store `organizationId` on the campaign entity (from `base44.auth.me()` / org context) and send it on every Render trigger.
3. **Trigger** — Base44 scheduler calls **`POST /scrape/campaign`** (not `/runscan/sync` unless you ingest leads yourself from the JSON response). `/runscan/sync` is mainly for **manual / test** exports without Base44 posting.

---

## San Diego: two campaigns / templates

San Diego County Accela is split into **two scraper configs**. In Base44, use **two separate PermitCampaign records** (or whatever your “template” maps to)—one per stream—so reporting, filters, and CTAs stay clean.

| Base44 campaign / template | Scrappy `city` key (use in API) | Lead category |
|----------------------------|----------------------------------|---------------|
| **San Diego — Residential** | `san_diego_residential` | residential (OTC / plan-check) |
| **San Diego — Commercial** | `san_diego_commercial` | commercial (`short_notes_filter` 8004) |

**Do not** use the legacy `san_diego` / `sandiego` keys for these Accela flows unless you intentionally mean the old `scraper.py` path.

### Example: `POST /scrape/campaign`

Residential campaign (use the Base44 `campaignId` for that template):

```json
{
  "campaignId": "<base44-residential-campaign-id>",
  "days": 3,
  "cities": ["san_diego_residential"]
}
```

Commercial campaign:

```json
{
  "campaignId": "<base44-commercial-campaign-id>",
  "days": 3,
  "cities": ["san_diego_commercial"]
}
```

Each lead gets `cityKey`, `campaignId` (when provided), and `uniqueId` shaped like `san_diego_residential_<permit>` so the two streams stay distinct in Base44.

---

## City limit per job (recommended: **≤ 5**)

Large multi-city jobs increase Playwright load, risk timeouts (especially on Render), and make failures harder to retry.

- **`POST /scrape/campaign`**: rejects requests with **more than 5** entries in `cities` (override with env if you must).
- **`POST /runscan/sync`**: rejects when **resolved** Accela city keys total **more than 5** (e.g. `sandiego` counts as **2** keys: residential + commercial).

**Split work** across multiple campaigns or sequential runscan calls instead of one huge batch.

### Environment variable

| Variable | Default | Meaning |
|----------|---------|---------|
| `MAX_CITIES_PER_JOB` | `5` | Max cities per `/scrape/campaign` request and per `/runscan/sync` (after alias expansion). Set higher only if your infra can handle it. |

---

## Ingest endpoint

Scrappy posts to your Base44 function `ingestSolarPermits` when `BASE44_ENABLED=true` and `INTERNAL_SECRET` matches. See `app.py` (`post_to_base44`).
