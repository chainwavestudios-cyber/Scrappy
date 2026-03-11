"""
Permit Portal Recon Spider
==========================
Uses Playwright to navigate city building permit portals, detect search capabilities,
and log the exact navigation path for later use in production scrapers.

Usage:
    pip install playwright asyncio
    playwright install chromium
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
# Config — add cities here
# ---------------------------------------------------------------------------

CITIES = [
    {
        "city": "San Diego",
        "state": "CA",
        "url": "https://aca-prod.accela.com/SANDIEGO/Cap/CapHome.aspx?module=Building",
        "platform": "Accela",
    },
    {
        "city": "Sacramento",
        "state": "CA",
        "url": "https://aca-prod.accela.com/SACRAMENTO/Cap/CapHome.aspx?module=Building",
        "platform": "Accela",
    },
    {
        "city": "San Jose",
        "state": "CA",
        "url": "https://permits.sanjoseca.gov/search/",
        "platform": "Custom",
    },
    {
        "city": "Fresno",
        "state": "CA",
        "url": "https://aca-prod.accela.com/FRESNO/Cap/CapHome.aspx?module=Building",
        "platform": "Accela",
    },
    {
        "city": "Long Beach",
        "state": "CA",
        "url": "https://energovweb.longbeach.gov/energov_prod/selfservice",
        "platform": "EnerGov",
    },
    # Add more cities here...
]


# ---------------------------------------------------------------------------
# Keywords to find the search entry point
# ---------------------------------------------------------------------------

SEARCH_ENTRY_KEYWORDS = [
    "search permits",
    "search records",
    "public search",
    "track a permit",
    "building records",
    "permit search",
    "citizen access",
    "search applications",
    "general search",
    "permit lookup",
    "record search",
]

# Keywords that indicate a broad/type-based search option
BROAD_SEARCH_KEYWORDS = [
    "photovoltaic",
    "solar",
    "permit type",
    "type of permit",
    "work type",
    "record type",
    "all permits",
    "category",
]

# Field selectors that indicate a date range is available
DATE_FIELD_PATTERNS = [
    "input[name*='date' i]",
    "input[placeholder*='date' i]",
    "input[id*='date' i]",
    "input[id*='Date']",
    "input[type='date']",
    "[id*='txtDate']",
    "[id*='DateFrom']",
    "[id*='DateTo']",
    "[id*='StartDate']",
    "[id*='EndDate']",
    "[id*='dtFrom']",
    "[id*='dtTo']",
]

# Field selectors that indicate address is available (could be required or optional)
ADDRESS_FIELD_PATTERNS = [
    "input[name*='address' i]",
    "input[placeholder*='address' i]",
    "input[id*='address' i]",
    "input[id*='Address']",
    "input[id*='StreetNo']",
    "input[id*='txtStreet']",
    "input[id*='street' i]",
]

# Permit type / description search fields (enables broad search)
BROAD_FIELD_PATTERNS = [
    "input[name*='project' i]",
    "input[id*='project' i]",
    "input[id*='ProjectName']",
    "input[name*='description' i]",
    "input[id*='description' i]",
    "select[id*='type' i]",
    "select[id*='Type']",
    "select[id*='PermitType']",
    "select[name*='type' i]",
    "input[id*='worktype' i]",
]


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class NavigationStep:
    step: int
    action: str           # "navigate", "click", "frame_switch", "wait", "detect"
    target: str           # description of what was targeted
    selector: str         # actual selector or URL used
    success: bool
    note: str = ""


@dataclass
class FormField:
    field_type: str       # "date", "address", "broad", "permit_type", "other"
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
    
    # Classification
    tier: str = "UNKNOWN"           # "TIER1_BROAD", "TIER2_PARTIAL", "TIER3_LOCKED", "ERROR"
    broad_search_possible: bool = False
    date_range_available: bool = False
    address_required: bool = False
    has_permit_type_filter: bool = False
    
    # What was found
    search_page_url: str = ""       # final URL where form was found
    iframe_detected: bool = False
    iframe_selector: str = ""
    
    # Navigation log — replay this to scrape
    navigation_steps: list = field(default_factory=list)
    form_fields: list = field(default_factory=list)
    
    # Raw notes
    notes: str = ""
    error: str = ""


# ---------------------------------------------------------------------------
# Core recon logic
# ---------------------------------------------------------------------------

class PermitReconSpider:

    def __init__(self, headless: bool = True, timeout: int = 15000):
        self.headless = headless
        self.timeout = timeout

    async def run(self, cities: list) -> list[ReconResult]:
        results = []
        async with async_playwright() as pw:
            browser = await pw.chromium.launch(headless=self.headless)
            context = await browser.new_context(
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/120.0.0.0 Safari/537.36"
                )
            )
            for city_config in cities:
                log.info(f"--- Reconning: {city_config['city']}, {city_config['state']} ---")
                result = await self._recon_city(context, city_config)
                results.append(result)
                log.info(f"    Result: {result.tier} | Date Range: {result.date_range_available} | Broad: {result.broad_search_possible}")
            await browser.close()
        return results

    async def _recon_city(self, context, config: dict) -> ReconResult:
        result = ReconResult(
            city=config["city"],
            state=config["state"],
            url=config["url"],
            platform=config["platform"],
            timestamp=datetime.now().isoformat(),
        )
        step_counter = [0]

        def log_step(action, target, selector, success, note=""):
            step_counter[0] += 1
            s = NavigationStep(
                step=step_counter[0],
                action=action,
                target=target,
                selector=selector,
                success=success,
                note=note,
            )
            result.navigation_steps.append(asdict(s))
            status = "✓" if success else "✗"
            log.info(f"    Step {s.step} [{status}] {action}: {target} | {note}")
            return s

        page = await context.new_page()
        page.set_default_timeout(self.timeout)

        try:
            # Step 1: Navigate to portal URL
            await page.goto(config["url"], wait_until="domcontentloaded")
            await page.wait_for_timeout(2000)
            log_step("navigate", config["url"], config["url"], True,
                     f"title='{await page.title()}'")

            # Step 2: Try to find search entry point (click if needed)
            search_context = await self._find_search_entry(page, result, log_step)

            # Step 3: Detect iframes
            active_frame = await self._detect_and_enter_iframe(
                page, search_context, result, log_step
            )

            # Step 4: Look for submenus / permit type selection
            await self._handle_submenus(active_frame, result, log_step)

            # Step 5: Analyze the search form
            await self._analyze_form(active_frame, result, log_step)

            # Step 6: Classify
            self._classify(result)

        except Exception as e:
            result.tier = "ERROR"
            result.error = str(e)
            log.error(f"    ERROR on {config['city']}: {e}")
        finally:
            result.search_page_url = page.url
            await page.close()

        return result

    async def _find_search_entry(self, page: Page, result: ReconResult, log_step) -> Page:
        """
        Look for a 'Search Permits' type link or button and click it.
        Returns the page (unchanged) — frame detection happens separately.
        """
        for keyword in SEARCH_ENTRY_KEYWORDS:
            # Try link text match
            locator = page.get_by_role("link", name=re.compile(keyword, re.IGNORECASE))
            if await locator.count() > 0:
                href = await locator.first.get_attribute("href") or ""
                await locator.first.click()
                await page.wait_for_timeout(2000)
                log_step("click", f"link: '{keyword}'",
                         f"role=link name=/{keyword}/i", True,
                         f"href={href} → now at {page.url}")
                return page

            # Try button text match
            locator = page.get_by_role("button", name=re.compile(keyword, re.IGNORECASE))
            if await locator.count() > 0:
                await locator.first.click()
                await page.wait_for_timeout(2000)
                log_step("click", f"button: '{keyword}'",
                         f"role=button name=/{keyword}/i", True,
                         f"now at {page.url}")
                return page

            # Try any element with matching text (tabs, divs, spans)
            locator = page.locator(f"text=/{keyword}/i")
            if await locator.count() > 0:
                tag = await locator.first.evaluate("el => el.tagName")
                await locator.first.click()
                await page.wait_for_timeout(2000)
                log_step("click", f"{tag}: '{keyword}'",
                         f"text=/{keyword}/i", True,
                         f"now at {page.url}")
                return page

        log_step("detect", "search entry point", "various", False,
                 "No search entry keyword matched — may already be on search page")
        return page

    async def _detect_and_enter_iframe(self, page: Page, search_context, result: ReconResult, log_step):
        """
        Detect iframes on the page. If found, switch into the most likely one.
        Returns either the iframe FrameLocator or the page itself.
        """
        frames = page.frames
        
        # Look for child frames (not the main frame)
        child_frames = [f for f in frames if f != page.main_frame]
        
        if child_frames:
            result.iframe_detected = True
            # Pick the largest / most likely frame (heuristic: not tiny, not ads)
            best_frame = None
            best_selector = ""
            for frame in child_frames:
                url = frame.url
                # Skip blank, tiny utility frames
                if url in ("about:blank", "") or "google" in url or "analytics" in url:
                    continue
                best_frame = frame
                best_selector = f"iframe[src*='{url.split('/')[-1]}']" if url else "iframe"
                break

            if best_frame:
                result.iframe_selector = best_selector
                log_step("frame_switch", f"iframe at {best_frame.url}",
                         best_selector, True,
                         f"Switched into child frame — {len(child_frames)} total child frames found")
                return best_frame

        # Also check for iframe elements explicitly
        iframe_els = await page.locator("iframe").all()
        if iframe_els:
            result.iframe_detected = True
            # Use the first non-trivial iframe
            for i, iframe_el in enumerate(iframe_els):
                src = await iframe_el.get_attribute("src") or ""
                if src and "google" not in src and "analytics" not in src:
                    selector = f"iframe:nth-of-type({i+1})"
                    frame_locator = page.frame_locator(selector)
                    result.iframe_selector = selector
                    log_step("frame_switch", f"iframe #{i+1} src={src}",
                             selector, True,
                             "Using FrameLocator for nested iframe interaction")
                    return frame_locator

            log_step("frame_switch", "iframe detected but all trivial", "iframe", False,
                     "All iframes appear to be ads/analytics")

        log_step("detect", "iframe check", "iframe", False,
                 "No iframes detected — working directly on page")
        return page

    async def _handle_submenus(self, context, result: ReconResult, log_step):
        """
        Handle permit type submenus or category selectors that appear
        before the main search form is visible.
        """
        # Common patterns: a "Building" tab, a permit category dropdown, etc.
        submenu_patterns = [
            ("link", "Building"),
            ("link", "Electrical"),
            ("button", "Building"),
            ("tab", "Building Permits"),
            ("text", "General Search"),
        ]

        for role, label in submenu_patterns:
            try:
                if role == "text":
                    loc = context.locator(f"text={label}")
                else:
                    loc = context.get_by_role(role, name=re.compile(label, re.IGNORECASE))
                
                if hasattr(loc, 'count'):
                    count = await loc.count()
                else:
                    # FrameLocator returns locator directly
                    count = await loc.count()
                    
                if count > 0:
                    await loc.first.click()
                    await context.locator("body").page.wait_for_timeout(1500) if hasattr(context, 'page') else None
                    log_step("click", f"submenu: {role}='{label}'",
                             f"role={role} name=/{label}/i", True,
                             "Submenu/tab clicked")
                    break
            except Exception:
                continue

    async def _analyze_form(self, context, result: ReconResult, log_step):
        """
        Inspect the search form for date range, address, and broad search fields.
        """
        # Helper to check if a selector exists in context
        async def field_exists(selector: str) -> tuple[bool, str]:
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

        # Check for date range fields
        for selector in DATE_FIELD_PATTERNS:
            found, detail = await field_exists(selector)
            if found:
                result.date_range_available = True
                result.form_fields.append(asdict(FormField(
                    field_type="date",
                    selector=selector,
                    name=detail,
                    required=False,
                    placeholder="",
                )))
                log_step("detect", "date range field", selector, True, detail)
                break

        if not result.date_range_available:
            log_step("detect", "date range field", "various", False, "No date field found")

        # Check for broad/project-name search fields
        for selector in BROAD_FIELD_PATTERNS:
            found, detail = await field_exists(selector)
            if found:
                result.has_permit_type_filter = True
                result.form_fields.append(asdict(FormField(
                    field_type="broad",
                    selector=selector,
                    name=detail,
                    required=False,
                )))
                log_step("detect", "broad search field (project/type)", selector, True, detail)
                break

        # Check for address fields and whether they appear required
        for selector in ADDRESS_FIELD_PATTERNS:
            found, detail = await field_exists(selector)
            if found:
                required = "required=True" in detail
                result.address_required = required
                result.form_fields.append(asdict(FormField(
                    field_type="address",
                    selector=selector,
                    name=detail,
                    required=required,
                )))
                log_step("detect", "address field", selector, True,
                         f"{detail} | required={required}")
                break

        # Count total visible form inputs (general richness indicator)
        try:
            total_inputs = await context.locator("input:visible, select:visible").count()
            log_step("detect", "total visible form inputs", "input:visible, select:visible",
                     True, f"count={total_inputs}")
        except Exception:
            pass

    def _classify(self, result: ReconResult):
        """Assign a tier based on what was found."""
        if result.date_range_available and (result.has_permit_type_filter or not result.address_required):
            result.tier = "TIER1_BROAD"
            result.broad_search_possible = True
        elif result.date_range_available and result.address_required:
            result.tier = "TIER2_PARTIAL"
            result.broad_search_possible = False
        elif not result.date_range_available:
            result.tier = "TIER3_LOCKED"
            result.broad_search_possible = False
        else:
            result.tier = "UNKNOWN"


# ---------------------------------------------------------------------------
# Output helpers
# ---------------------------------------------------------------------------

def save_results(results: list[ReconResult], json_path: str, csv_path: str):
    # Full detail JSON
    with open(json_path, "w") as f:
        json.dump([asdict(r) for r in results], f, indent=2)
    log.info(f"Saved full recon data → {json_path}")

    # Summary CSV
    with open(csv_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=[
            "city", "state", "platform", "tier", "broad_search_possible",
            "date_range_available", "address_required", "has_permit_type_filter",
            "iframe_detected", "iframe_selector", "search_page_url",
            "num_nav_steps", "num_form_fields", "error", "url",
        ])
        writer.writeheader()
        for r in results:
            writer.writerow({
                "city": r.city,
                "state": r.state,
                "platform": r.platform,
                "tier": r.tier,
                "broad_search_possible": r.broad_search_possible,
                "date_range_available": r.date_range_available,
                "address_required": r.address_required,
                "has_permit_type_filter": r.has_permit_type_filter,
                "iframe_detected": r.iframe_detected,
                "iframe_selector": r.iframe_selector,
                "search_page_url": r.search_page_url,
                "num_nav_steps": len(r.navigation_steps),
                "num_form_fields": len(r.form_fields),
                "error": r.error,
                "url": r.url,
            })
    log.info(f"Saved summary CSV → {csv_path}")


def print_summary(results: list[ReconResult]):
    print("\n" + "="*70)
    print("PERMIT PORTAL RECON SUMMARY")
    print("="*70)
    tier_counts = {}
    for r in results:
        tier_counts[r.tier] = tier_counts.get(r.tier, 0) + 1
        icon = {"TIER1_BROAD": "✅", "TIER2_PARTIAL": "🟡", "TIER3_LOCKED": "❌", "ERROR": "💥"}.get(r.tier, "❓")
        iframe_note = f" [iframe: {r.iframe_selector}]" if r.iframe_detected else ""
        print(f"{icon} {r.city}, {r.state} ({r.platform}) → {r.tier}{iframe_note}")
        if r.navigation_steps:
            for step in r.navigation_steps:
                status = "✓" if step["success"] else "✗"
                print(f"     {step['step']}. [{status}] {step['action']}: {step['target']}")
                if step["note"]:
                    print(f"          → {step['note']}")
        if r.error:
            print(f"     ERROR: {r.error}")
        print()
    print("-"*70)
    for tier, count in sorted(tier_counts.items()):
        print(f"  {tier}: {count}")
    print("="*70 + "\n")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

async def main():
    spider = PermitReconSpider(
        headless=True,   # Set False to watch the browser navigate live
        timeout=15000,
    )

    results = await spider.run(CITIES)

    save_results(
        results,
        json_path="permit_recon_results.json",
        csv_path="permit_recon_results.csv",
    )

    print_summary(results)


if __name__ == "__main__":
    asyncio.run(main())
