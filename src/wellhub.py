"""
Wellhub browser automation via Playwright.

Two public entry points:
  get_schedule(email, password) -> list[ClassSlot]
  book_class(email, password, class_id) -> bool

Since Wellhub's consumer web app (app.wellhub.com) is a login-gated SPA
behind Cloudflare, we drive a real Chromium browser in non-headless mode
for local runs and headed-but-stealth mode for CI.

Selector constants are grouped at the top so they can be updated quickly
after inspecting the live UI.
"""

from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Optional

from playwright.sync_api import Page, sync_playwright, TimeoutError as PWTimeout

from src.config import STUDIOS, BOOKING_WINDOW_DAYS

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Selectors — update these if Wellhub redesigns the UI
# ---------------------------------------------------------------------------
SEL_EMAIL_INPUT    = 'input[type="email"], input[name="email"]'
SEL_PASSWORD_INPUT = 'input[type="password"]'
SEL_LOGIN_SUBMIT   = 'button[type="submit"]'
SEL_SEARCH_INPUT   = 'input[placeholder*="search" i], input[aria-label*="search" i]'
SEL_CLASS_CARD     = '[data-testid*="class"], [class*="ClassCard"], [class*="class-card"], article'
SEL_CLASS_NAME     = '[class*="className"], [class*="class-name"], h3, h2'
SEL_CLASS_TIME     = '[class*="time"], time, [datetime]'
SEL_CLASS_INSTRUCTOR = '[class*="instructor"], [class*="coach"], [class*="teacher"]'
SEL_BOOK_BUTTON    = 'button:has-text("Book"), button:has-text("Reserve"), a:has-text("Book")'
SEL_CONFIRM_BUTTON = 'button:has-text("Confirm"), button:has-text("Complete")'

WELLHUB_URL = "https://app.wellhub.com"
LOGIN_URL   = f"{WELLHUB_URL}/en-US/login"


@dataclass
class ClassSlot:
    wellhub_class_id: str          # unique identifier for booking
    studio: str                    # "Chelsea" or "Greenwich Village"
    instructor: str
    dt: datetime                   # local datetime of class
    booked: bool = False
    muscles: list[str] = field(default_factory=list)   # filled in by filters.py

    @property
    def date(self) -> date:
        return self.dt.date()

    @property
    def time_str(self) -> str:
        return self.dt.strftime("%-I:%M %p")

    @property
    def date_str(self) -> str:
        return self.dt.strftime("%a %b %-d")

    def to_dict(self) -> dict:
        return {
            "id": self.wellhub_class_id,
            "studio": self.studio,
            "instructor": self.instructor,
            "datetime": self.dt.isoformat(),
            "booked": self.booked,
            "muscles": self.muscles,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "ClassSlot":
        return cls(
            wellhub_class_id=d["id"],
            studio=d["studio"],
            instructor=d["instructor"],
            dt=datetime.fromisoformat(d["datetime"]),
            booked=d.get("booked", False),
            muscles=d.get("muscles", []),
        )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def get_schedule(email: str, password: str, headless: bool = True) -> list[ClassSlot]:
    """Log in to Wellhub and return Solidcore classes for the next BOOKING_WINDOW_DAYS."""
    slots: list[ClassSlot] = []
    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=headless,
            args=["--no-sandbox", "--disable-blink-features=AutomationControlled"],
        )
        ctx = browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/122.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1280, "height": 800},
            locale="en-US",
        )
        # Mask webdriver flag
        ctx.add_init_script(
            "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
        )
        page = ctx.new_page()

        try:
            _login(page, email, password)
            for studio_name, studio_cfg in STUDIOS.items():
                studio_slots = _scrape_studio(page, studio_name, studio_cfg)
                slots.extend(studio_slots)
                log.info("  %s: found %d classes", studio_name, len(studio_slots))
        except Exception as exc:
            log.error("Error during Wellhub scrape: %s", exc)
            # Save a screenshot for debugging
            try:
                page.screenshot(path="debug_screenshot.png")
                log.info("Debug screenshot saved to debug_screenshot.png")
            except Exception:
                pass
            raise
        finally:
            browser.close()

    return slots


def book_class(email: str, password: str, class_id: str, headless: bool = True) -> bool:
    """Book a single class by its Wellhub class ID. Returns True on success."""
    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=headless,
            args=["--no-sandbox", "--disable-blink-features=AutomationControlled"],
        )
        ctx = browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/122.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1280, "height": 800},
            locale="en-US",
        )
        ctx.add_init_script(
            "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
        )
        page = ctx.new_page()
        try:
            _login(page, email, password)
            return _book_by_id(page, class_id)
        except Exception as exc:
            log.error("Booking failed for class %s: %s", class_id, exc)
            try:
                page.screenshot(path=f"debug_book_{class_id}.png")
            except Exception:
                pass
            return False
        finally:
            browser.close()


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _login(page: Page, email: str, password: str) -> None:
    log.info("Logging in to Wellhub as %s", email)
    page.goto(LOGIN_URL, wait_until="domcontentloaded", timeout=30_000)
    page.wait_for_timeout(2_000)  # let Cloudflare challenge resolve

    # Fill email
    page.wait_for_selector(SEL_EMAIL_INPUT, timeout=15_000)
    page.fill(SEL_EMAIL_INPUT, email)

    # Fill password — some flows show it on the next screen
    try:
        page.fill(SEL_PASSWORD_INPUT, password)
    except PWTimeout:
        # Password field may appear after clicking Next
        page.click(SEL_LOGIN_SUBMIT)
        page.wait_for_selector(SEL_PASSWORD_INPUT, timeout=10_000)
        page.fill(SEL_PASSWORD_INPUT, password)

    page.click(SEL_LOGIN_SUBMIT)
    # Wait for navigation away from login page
    page.wait_for_url(lambda url: "login" not in url, timeout=20_000)
    log.info("Login successful")


def _scrape_studio(page: Page, studio_name: str, studio_cfg: dict) -> list[ClassSlot]:
    """Navigate to the studio's schedule page in Wellhub and extract class slots."""
    slots: list[ClassSlot] = []
    search_term = studio_cfg["wellhub_search"]

    # Try navigating to activities/search
    page.goto(f"{WELLHUB_URL}/en-US/activities", wait_until="domcontentloaded", timeout=20_000)
    page.wait_for_timeout(1_500)

    # Search for the studio
    try:
        page.wait_for_selector(SEL_SEARCH_INPUT, timeout=8_000)
        page.fill(SEL_SEARCH_INPUT, search_term)
        page.keyboard.press("Enter")
        page.wait_for_timeout(2_000)
    except PWTimeout:
        log.warning("Search input not found for %s, trying direct URL", studio_name)

    # Intercept network requests to capture the schedule API response if possible
    api_slots = _try_intercept_api(page, studio_name)
    if api_slots:
        return api_slots

    # Fall back to DOM scraping
    return _scrape_dom(page, studio_name)


def _try_intercept_api(page: Page, studio_name: str) -> list[ClassSlot]:
    """
    Monitor network requests for schedule/class API calls.
    Wellhub's SPA fetches class data via XHR; we capture the JSON if possible.
    """
    captured: list[dict] = []

    def on_response(response):
        url = response.url
        if any(kw in url for kw in ("classes", "schedule", "slots", "activities")):
            try:
                body = response.json()
                captured.append({"url": url, "body": body})
                log.debug("Captured API response: %s", url)
            except Exception:
                pass

    page.on("response", on_response)
    page.wait_for_timeout(3_000)
    page.remove_listener("response", on_response)

    slots: list[ClassSlot] = []
    for item in captured:
        parsed = _parse_api_response(item["body"], studio_name)
        slots.extend(parsed)

    return slots


def _parse_api_response(data: dict | list, studio_name: str) -> list[ClassSlot]:
    """
    Attempt to parse a captured Wellhub API JSON response into ClassSlots.
    Structure is inferred — update once we observe real responses.
    """
    slots: list[ClassSlot] = []
    cutoff = datetime.now() + timedelta(days=BOOKING_WINDOW_DAYS)

    # Normalize to list
    items: list[dict] = []
    if isinstance(data, list):
        items = data
    elif isinstance(data, dict):
        for key in ("classes", "slots", "items", "results", "data"):
            if key in data and isinstance(data[key], list):
                items = data[key]
                break

    for item in items:
        try:
            class_id   = str(item.get("id", item.get("classId", "")))
            instructor = (
                item.get("instructor", {}).get("name", "")
                or item.get("instructorName", "")
                or item.get("coach", {}).get("name", "")
                or ""
            )
            dt_raw = (
                item.get("startTime")
                or item.get("start_time")
                or item.get("datetime")
                or item.get("scheduledAt")
            )
            if not (class_id and instructor and dt_raw):
                continue

            dt = datetime.fromisoformat(str(dt_raw).replace("Z", "+00:00"))
            if dt > cutoff:
                continue

            slots.append(ClassSlot(
                wellhub_class_id=class_id,
                studio=studio_name,
                instructor=instructor,
                dt=dt,
            ))
        except Exception as exc:
            log.debug("Could not parse item: %s — %s", item, exc)

    return slots


def _scrape_dom(page: Page, studio_name: str) -> list[ClassSlot]:
    """
    Fallback DOM scraper. Reads class cards from the rendered page.
    Selectors are approximations — tune after first run.
    """
    log.info("DOM scrape for %s", studio_name)
    slots: list[ClassSlot] = []
    cutoff = datetime.now() + timedelta(days=BOOKING_WINDOW_DAYS)

    try:
        page.wait_for_selector(SEL_CLASS_CARD, timeout=10_000)
    except PWTimeout:
        log.warning("No class cards found for %s", studio_name)
        return slots

    cards = page.query_selector_all(SEL_CLASS_CARD)
    log.info("Found %d raw cards for %s", len(cards), studio_name)

    for card in cards:
        try:
            # Extract text from card sub-elements
            name_el  = card.query_selector(SEL_CLASS_NAME)
            time_el  = card.query_selector(SEL_CLASS_TIME)
            inst_el  = card.query_selector(SEL_CLASS_INSTRUCTOR)

            class_name = name_el.inner_text().strip() if name_el else ""
            time_str   = time_el.inner_text().strip() if time_el else (
                time_el.get_attribute("datetime") if time_el else ""
            )
            instructor = inst_el.inner_text().strip() if inst_el else ""

            # Try to get an ID from data attributes or href
            class_id = (
                card.get_attribute("data-id")
                or card.get_attribute("data-class-id")
                or card.get_attribute("data-slot-id")
                or ""
            )
            link_el = card.query_selector("a[href]")
            if not class_id and link_el:
                href = link_el.get_attribute("href") or ""
                # Extract last path segment as ID
                class_id = href.rstrip("/").split("/")[-1]

            if not class_id or not instructor:
                continue

            dt = _parse_time_str(time_str)
            if dt is None or dt > cutoff:
                continue

            slots.append(ClassSlot(
                wellhub_class_id=class_id,
                studio=studio_name,
                instructor=instructor,
                dt=dt,
            ))
        except Exception as exc:
            log.debug("Card parse error: %s", exc)

    return slots


def _book_by_id(page: Page, class_id: str) -> bool:
    """
    Navigate to the class detail page and click Book → Confirm.
    Wellhub class URLs are typically: /en-US/activities/classes/{class_id}
    """
    url = f"{WELLHUB_URL}/en-US/activities/classes/{class_id}"
    log.info("Navigating to class page: %s", url)
    page.goto(url, wait_until="domcontentloaded", timeout=20_000)
    page.wait_for_timeout(1_500)

    # Click Book button
    try:
        page.wait_for_selector(SEL_BOOK_BUTTON, timeout=10_000)
        page.click(SEL_BOOK_BUTTON)
        page.wait_for_timeout(1_000)
    except PWTimeout:
        log.error("Book button not found for class %s", class_id)
        return False

    # Confirm if needed
    try:
        page.wait_for_selector(SEL_CONFIRM_BUTTON, timeout=8_000)
        page.click(SEL_CONFIRM_BUTTON)
        page.wait_for_timeout(1_500)
    except PWTimeout:
        pass  # No confirmation modal — booking may already be done

    # Check for success indicator
    try:
        page.wait_for_selector(
            ':text("Booked"), :text("Reserved"), :text("Confirmed"), :text("See you")',
            timeout=10_000,
        )
        log.info("Booking confirmed for class %s", class_id)
        return True
    except PWTimeout:
        log.warning("No confirmation text found — booking status unclear for %s", class_id)
        page.screenshot(path=f"debug_book_result_{class_id}.png")
        return False


def _parse_time_str(text: str) -> Optional[datetime]:
    """
    Parse time strings that might appear in the UI.
    E.g. "Mon Apr 7 · 12:00 PM", "2026-04-07T12:00:00", "10:30 AM"
    """
    if not text:
        return None

    # ISO datetime
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        pass

    # Common human-readable formats
    formats = [
        "%a %b %d · %I:%M %p",
        "%a, %b %d · %I:%M %p",
        "%A, %B %d, %Y %I:%M %p",
        "%m/%d/%Y %I:%M %p",
        "%B %d, %Y %I:%M %p",
        "%I:%M %p",    # time only — assume today
    ]
    for fmt in formats:
        try:
            dt = datetime.strptime(text.strip(), fmt)
            if dt.year == 1900:
                # Time-only parse — attach today's date
                today = datetime.now()
                dt = dt.replace(year=today.year, month=today.month, day=today.day)
            return dt
        except ValueError:
            continue

    log.debug("Could not parse time string: %r", text)
    return None
