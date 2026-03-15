"""
Permit Portal Recon Spider
==========================
Uses Playwright to navigate city building permit portals, detect search capabilities,
and log the exact navigation path for later use in production scrapers.

Usage:
    python permit_recon_spider.py

Output:
    permit_recon_results.json  — classification + full navigation log per city
    permit_recon_results.csv   — summary table
"""

import asyncio
import json
import csv
import re
import logging
from datetime import datetime
from dataclasses import dataclass, field, asdict
from typing import Optional
from playwright.async_api import async_playwright, Page, Frame, Locator

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Top 50 California cities with known or likely portal URLs
# ---------------------------------------------------------------------------

CITIES = [
    {"city": "Los Angeles",     "state": "CA", "url": "https://ladbsservices2.lacity.org/OnlineServices/", "platform": "Custom"},
    {"city": "San Diego",       "state": "CA", "url": "https://aca-prod.accela.com/SANDIEGO/Cap/CapHome.aspx?module=Building", "platform": "Accela"},
    {"city": "San Jose",        "state": "CA", "url": "https://permits.sanjoseca.gov/search/", "platform": "Custom"},
    {"city": "San Francisco",   "state": "CA", "url": "https://aca-prod.accela.com/SANFRANCISCO/Cap/CapHome.aspx?module=Building", "platform": "Accela"},
    {"city": "Fresno",          "state": "CA", "url": "https://aca-prod.accela.com/FRESNO/Cap/CapHome.aspx?module=Building", "platform": "Accela"},
    {"city": "Sacramento",      "state": "CA", "url": "https://aca-prod.accela.com/SACRAMENTO/Cap/CapHome.aspx?module=Building", "platform": "Accela"},
    {"city": "Long Beach",      "state": "CA", "url": "https://www.lbds.info/citrixapps/eservices/", "platform": "Custom"},
    {"city": "Oakland",         "state": "CA", "url": "https://aca-prod.accela.com/OAKLAND/Cap/CapHome.aspx?module=Building", "platform": "Accela"},
    {"city": "Bakersfield",     "state": "CA", "url": "https://aca-prod.accela.com/BAKERSFIELD/Cap/CapHome.aspx?module=Building", "platform": "Accela"},
    {"city": "Anaheim",         "state": "CA", "url": "https://aca-prod.accela.com/ANAHEIM/Cap/CapHome.aspx?module=Building", "platform": "Accela"},
    {"city": "Santa Ana",       "state": "CA", "url": "https://aca-prod.accela.com/SANTAANA/Cap/CapHome.aspx?module=Building", "platform": "Accela"},
    {"city": "Riverside",       "state": "CA", "url": "https://aca-prod.accela.com/RIVERSIDE/Cap/CapHome.aspx?module=Building", "platform": "Accela"},
    {"city": "Stockton",        "state": "CA", "url": "https://aca-prod.accela.com/STOCKTON/Cap/CapHome.aspx?module=Building", "platform": "Accela"},
    {"city": "Chula Vista",     "state": "CA", "url": "https://aca-prod.accela.com/CHULAVISTA/Cap/CapHome.aspx?module=Building", "platform": "Accela"},
    {"city": "Irvine",          "state": "CA", "url": "https://aca-prod.accela.com/IRVINE/Cap/CapHome.aspx?module=Building", "platform": "Accela"},
    {"city": "Fremont",         "state": "CA", "url": "https://aca-prod.accela.com/FREMONT/Cap/CapHome.aspx?module=Building", "platform": "Accela"},
    {"city": "San Bernardino",  "state": "CA", "url": "https://aca-prod.accela.com/SANBERNARDINOCD/Cap/CapHome.aspx?module=Building", "platform": "Accela"},
    {"city": "Modesto",         "state": "CA", "url": "https://aca-prod.accela.com/MODESTO/Cap/CapHome.aspx?module=Building", "platform": "Accela"},
    {"city": "Fontana",         "state": "CA", "url": "https://aca-prod.accela.com/FONTANA/Cap/CapHome.aspx?module=Building", "platform": "Accela"},
    {"city": "Moreno Valley",   "state": "CA", "url": "https://aca-prod.accela.com/MORENOVALLEY/Cap/CapHome.aspx?module=Building", "platform": "Accela"},
    {"city": "Glendale",        "state": "CA", "url": "https://aca-prod.accela.com/GLENDALE/Cap/CapHome.aspx?module=Building", "platform": "Accela"},
    {"city": "Huntington Beach","state": "CA", "url": "https://aca-prod.accela.com/HUNTINGTONBEACH/Cap/CapHome.aspx?module=Building", "platform": "Accela"},
    {"city": "Santa Clarita",   "state": "CA", "url": "https://aca-prod.accela.com/SANTACLARITA/Cap/CapHome.aspx?module=Building", "platform": "Accela"},
    {"city": "Garden Grove",    "state": "CA", "url": "https://aca-prod.accela.com/GARDENGROVE/Cap/CapHome.aspx?module=Building", "platform": "Accela"},
    {"city": "Oceanside",       "state": "CA", "url": "https://aca-prod.accela.com/OCEANSIDE/Cap/CapHome.aspx?module=Building", "platform": "Accela"},
    {"city": "Rancho Cucamonga","state": "CA", "url": "https://aca-prod.accela.com/RANCHOCUCAMONGA/Cap/CapHome.aspx?module=Building", "platform": "Accela"},
    {"city": "Santa Rosa",      "state": "CA", "url": "https://aca-prod.accela.com/SANTAROSA/Cap/CapHome.aspx?module=Building", "platform": "Accela"},
    {"city": "Ontario",         "state": "CA", "url": "https://aca-prod.accela.com/ONTARIO/Cap/CapHome.aspx?module=Building", "platform": "Accela"},
    {"city": "Lancaster",       "state": "CA", "url": "https://aca-prod.accela.com/LANCASTER/Cap/CapHome.aspx?module=Building", "platform": "Accela"},
    {"city": "Elk Grove",       "state": "CA", "url": "https://energov.elkgrovecity.org/EnerGov_Prod/SelfService", "platform": "EnerGov"},
    {"city": "Corona",          "state": "CA", "url": "https://aca-prod.accela.com/CORONA/Cap/CapHome.aspx?module=Building", "platform": "Accela"},
    {"city": "Palmdale",        "state": "CA", "url": "https://aca-prod.accela.com/PALMDALE/Cap/CapHome.aspx?module=Building", "platform": "Accela"},
    {"city": "Salinas",         "state": "CA", "url": "https://aca-prod.accela.com/SALINAS/Cap/CapHome.aspx?module=Building", "platform": "Accela"},
    {"city": "Pomona",          "state": "CA", "url": "https://aca-prod.accela.com/POMONA/Cap/CapHome.aspx?module=Building", "platform": "Accela"},
    {"city": "Torrance",        "state": "CA", "url": "https://aca-prod.accela.com/TORRANCE/Cap/CapHome.aspx?module=Building", "platform": "Accela"},
    {"city": "Escondido",       "state": "CA", "url": "https://citizenaccess.escondido.org/CitizenAccess/Cap/CapHome.aspx?module=Building", "platform": "Accela"},
    {"city": "Sunnyvale",       "state": "CA", "url": "https://sunnyvale.ca.gov/services/permits", "platform": "Custom"},
    {"city": "Pasadena",        "state": "CA", "url": "https://permits.cityofpasadena.net/", "platform": "OpenGov"},
    {"city": "Orange",          "state": "CA", "url": "https://aca-prod.accela.com/ORANGE/Cap/CapHome.aspx?module=Building", "platform": "Accela"},
    {"city": "Fullerton",       "state": "CA", "url": "https://aca-prod.accela.com/FULLERTON/Cap/CapHome.aspx?module=Building", "platform": "Accela"},
    {"city": "Roseville",       "state": "CA", "url": "https://etrakit.roseville.ca.us/etrakit3/", "platform": "eTRAKiT"},
    {"city": "Visalia",         "state": "CA", "url": "https://aca-prod.accela.com/VISALIA/Cap/CapHome.aspx?module=Building", "platform": "Accela"},
    {"city": "Concord",         "state": "CA", "url": "https://aca-prod.accela.com/CONCORD/Cap/CapHome.aspx?module=Building", "platform": "Accela"},
    {"city": "Thousand Oaks",   "state": "CA", "url": "https://aca-prod.accela.com/THOUSANDOAKS/Cap/CapHome.aspx?module=Building", "platform": "Accela"},
    {"city": "Simi Valley",     "state": "CA", "url": "https://aca-prod.accela.com/SIMIVALLEY/Cap/CapHome.aspx?module=Building", "platform": "Accela"},
    {"city": "Victorville",     "state": "CA", "url": "https://aca-prod.accela.com/VICTORVILLE/Cap/CapHome.aspx?module=Building", "platform": "Accela"},
    {"city": "Santa Clara",     "state": "CA", "url": "https://aca-prod.accela.com/SANTACLARACA/Cap/CapHome.aspx?module=Building", "platform": "Accela"},
    {"city": "Berkeley",        "state": "CA", "url": "https://aca-prod.accela.com/BERKELEY/Cap/CapHome.aspx?module=Building", "platform": "Accela"},
    {"city": "El Monte",        "state": "CA", "url": "https://aca-prod.accela.com/ELMONTE/Cap/CapHome.aspx?module=Building", "platform": "Accela"},
    {"city": "Downey",          "state": "CA", "url": "https://aca-prod.accela.com/DOWNEY/Cap/CapHome.aspx?module=Building", "platform": "Accela"},
]


# ---------------------------------------------------------------------------
# Keywords
# ---------------------------------------------------------------------------

SEARCH_ENTRY_KEYWORDS = [
    "search permits", "search records", "public search", "track a permit",
    "building records", "permit search", "citizen access", "search applications",
    "general search", "permit lookup", "record search",
]

DATE_FIELD_PATTERNS = [
    "input[name*='date' i]", "input[placeholder*='date' i]", "input[id*='date' i]",
    "input[id*='Date']", "input[type='date']", "[id*='txtDate']",
    "[id*='DateFrom']", "[id*='DateTo']", "[id*='StartDate']", "[id*='EndDate']",
    "[id*='dtFrom']", "[id*='dtTo']",
]

ADDRESS_FIELD_PATTERNS = [
    "input[name*='address' i]", "input[placeholder*='address' i]",
    "input[id*='address' i]", "input[id*='Address']", "input[id*='StreetNo']",
    "input[id*='txtStreet']", "input[id*='street' i]",
]

BROAD_FIELD_PATTERNS = [
    "input[name*='project' i]", "input[id*='project' i]", "input[id*='ProjectName']",
    "input[name*='description' i]", "input[id*='description' i]",
    "select[id*='type' i]", "select[id*='Type']", "select[id*='PermitType']",
    "select[name*='type' i]", "input[id*='worktype' i]",
]


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class NavigationStep:
    step: int
    action: str
    target: str
    selector: str
    success: bool
    note: str = ""


@dataclass
class FormField:
    field_type: str
    selector: str
    name: str
    required: bool
    placeholder: str = ""


@dataclass
class ReconResult:
    city: str
    state: str
    url: str
    platform: str
    timestamp: str
    tier: str = "UNKNOWN"
    broad_search_possible: bool = False
    date_range_available: bool = False
    address_required: bool = False
    has_permit_type_filter: bool = False
    search_page_url: str = ""
    iframe_detected: bool = False
    iframe_selector: str = ""
    navigation_steps: list = field(default_factory=list)
    form_fields: list = field(default_factory=list)
    notes: str = ""
    error: str = ""


# ---------------------------------------------------------------------------
# Spider
# ---------------------------------------------------------------------------

class PermitReconSpider:

    def __init__(self, headless: bool = True, timeout: int = 15000):
        self.headless = headless
        self.timeout = timeout

    async def run(self, cities: list) -> list[ReconResult]:
        results = []
        async with async_playwright() as pw:
            browser = await pw.chromium.launch(headless=self.headless)
            for city_config in cities:
                log.info(f"--- Reconning: {city_config['city']}, {city_config['state']} ---")
                context = await browser.new_context(
                    user_agent=(
                        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/120.0.0.0 Safari/537.36"
                    )
                )
                result = await self._recon_city(context, city_config)
                await context.close()
                results.append(result)
                log.info(f"    Result: {result.tier} | Date Range: {result.date_range_available} | Broad: {result.broad_search_possible}")
            await browser.close()
        return results

    async def _recon_city(self, context, config: dict) -> ReconResult:
        result = ReconResult(
            city=config["city"], state=config["state"], url=config["url"],
            platform=config["platform"], timestamp=datetime.now().isoformat(),
        )
        step_counter = [0]

        def log_step(action, target, selector, success, note=""):
            step_counter[0] += 1
            s = NavigationStep(step=step_counter[0], action=action, target=target,
                               selector=selector, success=success, note=note)
            result.navigation_steps.append(asdict(s))
            status = "✓" if success else "✗"
            log.info(f"    Step {s.step} [{status}] {action}: {target} | {note}")
            return s

        page = await context.new_page()
        page.set_default_timeout(self.timeout)

        try:
            await page.goto(config["url"], wait_until="domcontentloaded")
            await page.wait_for_timeout(2000)
            log_step("navigate", config["url"], config["url"], True,
                     f"title='{await page.title()}'")

            search_context = await self._find_search_entry(page, result, log_step)
            active_frame = await self._detect_and_enter_iframe(page, search_context, result, log_step)
            await self._handle_submenus(active_frame, result, log_step)
            await self._analyze_form(active_frame, result, log_step)
            self._classify(result)

        except Exception as e:
            result.tier = "ERROR"
            result.error = str(e)
            log.error(f"    ERROR on {config['city']}: {e}")
        finally:
            result.search_page_url = page.url
            await page.close()

        return result

    async def _find_search_entry(self, page, result, log_step):
        for keyword in SEARCH_ENTRY_KEYWORDS:
            for role in ["link", "button"]:
                locator = page.get_by_role(role, name=re.compile(keyword, re.IGNORECASE))
                if await locator.count() > 0:
                    href = await locator.first.get_attribute("href") or ""
                    try:
                        await locator.first.click()
                        await page.wait_for_timeout(2000)
                        log_step("click", f"{role}: '{keyword}'",
                                 f"role={role} name=/{keyword}/i", True,
                                 f"href={href} → now at {page.url}")
                        return page
                    except Exception:
                        pass

            locator = page.locator(f"text=/{keyword}/i")
            if await locator.count() > 0:
                try:
                    tag = await locator.first.evaluate("el => el.tagName")
                    await locator.first.click()
                    await page.wait_for_timeout(2000)
                    log_step("click", f"{tag}: '{keyword}'",
                             f"text=/{keyword}/i", True, f"now at {page.url}")
                    return page
                except Exception:
                    pass

        log_step("detect", "search entry point", "various", False,
                 "No search entry keyword matched — may already be on search page")
        return page

    async def _detect_and_enter_iframe(self, page, search_context, result, log_step):
        frames = page.frames
        child_frames = [f for f in frames if f != page.main_frame]

        if child_frames:
            result.iframe_detected = True
            for frame in child_frames:
                url = frame.url
                if url in ("about:blank", "") or "google" in url or "analytics" in url:
                    continue
                best_selector = f"iframe[src*='{url.split('/')[-1]}']" if url else "iframe"
                result.iframe_selector = best_selector
                log_step("frame_switch", f"iframe at {frame.url}", best_selector, True,
                         f"Switched into child frame")
                return frame

        iframe_els = await page.locator("iframe").all()
        if iframe_els:
            result.iframe_detected = True
            for i, iframe_el in enumerate(iframe_els):
                src = await iframe_el.get_attribute("src") or ""
                if src and "google" not in src and "analytics" not in src:
                    selector = f"iframe:nth-of-type({i+1})"
                    frame_locator = page.frame_locator(selector)
                    result.iframe_selector = selector
                    log_step("frame_switch", f"iframe #{i+1} src={src}", selector, True,
                             "Using FrameLocator")
                    return frame_locator

            log_step("frame_switch", "iframe detected but all trivial", "iframe", False,
                     "All iframes appear to be ads/analytics")

        log_step("detect", "iframe check", "iframe", False, "No iframes detected — working directly on page")
        return page

    async def _handle_submenus(self, context, result, log_step):
        submenu_patterns = [
            ("link", "Building"), ("button", "Building"),
            ("link", "Electrical"), ("tab", "Building Permits"),
        ]
        for role, label in submenu_patterns:
            try:
                loc = context.get_by_role(role, name=re.compile(label, re.IGNORECASE))
                if await loc.count() > 0:
                    await loc.first.click()
                    await asyncio.sleep(1.5)
                    log_step("click", f"submenu: {role}='{label}'",
                             f"role={role} name=/{label}/i", True, "Submenu/tab clicked")
                    break
            except Exception:
                continue

    async def _analyze_form(self, context, result, log_step):
        async def field_exists(selector):
            try:
                loc = context.locator(selector)
                count = await loc.count()
                if count > 0:
                    name = await loc.first.get_attribute("name") or ""
                    placeholder = await loc.first.get_attribute("placeholder") or ""
                    required = await loc.first.get_attribute("required") is not None
                    return True, f"name={name} placeholder={placeholder} required={required}"
                return False, ""
            except Exception:
                return False, ""

        for selector in DATE_FIELD_PATTERNS:
            found, detail = await field_exists(selector)
            if found:
                result.date_range_available = True
                result.form_fields.append(asdict(FormField("date", selector, detail, False)))
                log_step("detect", "date range field", selector, True, detail)
                break
        if not result.date_range_available:
            log_step("detect", "date range field", "various", False, "No date field found")

        for selector in BROAD_FIELD_PATTERNS:
            found, detail = await field_exists(selector)
            if found:
                result.has_permit_type_filter = True
                result.form_fields.append(asdict(FormField("broad", selector, detail, False)))
                log_step("detect", "broad search field (project/type)", selector, True, detail)
                break

        for selector in ADDRESS_FIELD_PATTERNS:
            found, detail = await field_exists(selector)
            if found:
                required = "required=True" in detail
                result.address_required = required
                result.form_fields.append(asdict(FormField("address", selector, detail, required)))
                log_step("detect", "address field", selector, True,
                         f"{detail} | required={required}")
                break

        try:
            total_inputs = await context.locator("input:visible, select:visible").count()
            log_step("detect", "total visible form inputs",
                     "input:visible, select:visible", True, f"count={total_inputs}")
        except Exception:
            pass

    def _classify(self, result):
        if result.date_range_available and (result.has_permit_type_filter or not result.address_required):
            result.tier = "TIER1_BROAD"
            result.broad_search_possible = True
        elif result.date_range_available and result.address_required:
            result.tier = "TIER2_PARTIAL"
        elif not result.date_range_available:
            result.tier = "TIER3_LOCKED"
        else:
            result.tier = "UNKNOWN"


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------

def save_results(results, json_path, csv_path):
    with open(json_path, "w") as f:
        json.dump([asdict(r) for r in results], f, indent=2)
    log.info(f"Saved full recon data → {json_path}")

    with open(csv_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=[
            "city", "state", "platform", "tier", "broad_search_possible",
            "date_range_available", "address_required", "has_permit_type_filter",
            "iframe_detected", "search_page_url", "error", "url",
        ])
        writer.writeheader()
        for r in results:
            writer.writerow({
                "city": r.city, "state": r.state, "platform": r.platform,
                "tier": r.tier, "broad_search_possible": r.broad_search_possible,
                "date_range_available": r.date_range_available,
                "address_required": r.address_required,
                "has_permit_type_filter": r.has_permit_type_filter,
                "iframe_detected": r.iframe_detected,
                "search_page_url": r.search_page_url,
                "error": r.error, "url": r.url,
            })
    log.info(f"Saved summary CSV → {csv_path}")


def print_summary(results):
    print("\n" + "="*70)
    print("PERMIT PORTAL RECON SUMMARY — TOP 50 CA CITIES")
    print("="*70)
    tier_counts = {}
    for r in results:
        tier_counts[r.tier] = tier_counts.get(r.tier, 0) + 1
        icon = {"TIER1_BROAD": "✅", "TIER2_PARTIAL": "🟡",
                "TIER3_LOCKED": "❌", "ERROR": "💥"}.get(r.tier, "❓")
        print(f"{icon} {r.city}, {r.state} ({r.platform}) → {r.tier}")
    print("-"*70)
    for tier, count in sorted(tier_counts.items()):
        print(f"  {tier}: {count}")
    print("="*70 + "\n")


async def main():
    spider = PermitReconSpider(headless=True, timeout=15000)
    results = await spider.run(CITIES)
    save_results(results, "permit_recon_results.json", "permit_recon_results.csv")
    print_summary(results)


if __name__ == "__main__":
    asyncio.run(main())
