# Base44 integration

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
