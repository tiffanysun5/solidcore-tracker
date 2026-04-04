"""
Scrapes the public Solidcore monthly muscle-focus calendar.
URL: https://solidcore.co/monthly-muscle-focus

The Webflow CMS page embeds structured data in the DOM:
  .workout-item  → one entry per day
  .workout-date  → e.g. "April 3, 2026"
  .muscle-1      → primary muscle, e.g. "Leg Wrap"
  .muscle-2      → secondary muscle, e.g. "Push"

Returns a dict mapping date → list[str] of muscle names (lowercased for comparison).
"""

from __future__ import annotations

import logging
from datetime import date, datetime
from typing import Optional

import requests
from bs4 import BeautifulSoup

MUSCLE_FOCUS_URL = "https://solidcore.co/monthly-muscle-focus"
log = logging.getLogger(__name__)


def fetch_muscle_focus() -> dict[date, list[str]]:
    """Return {date: [muscle1, muscle2, ...]} for all entries on the page."""
    log.info("Fetching muscle focus from %s", MUSCLE_FOCUS_URL)
    resp = requests.get(
        MUSCLE_FOCUS_URL,
        headers={"User-Agent": "Mozilla/5.0 (compatible; SolidcoreTracker/1.0)"},
        timeout=20,
    )
    resp.raise_for_status()
    return _parse(resp.text)


def _parse(html: str) -> dict[date, list[str]]:
    soup = BeautifulSoup(html, "html.parser")
    result: dict[date, list[str]] = {}

    for item in soup.select(".workout-item"):
        date_el = item.select_one(".workout-date")
        m1_el   = item.select_one(".muscle-1")
        m2_el   = item.select_one(".muscle-2")

        if not date_el:
            continue

        parsed_date = _parse_date(date_el.get_text(strip=True))
        if parsed_date is None:
            continue

        muscles: list[str] = []
        for el in (m1_el, m2_el):
            if el:
                text = el.get_text(strip=True)
                if text:
                    muscles.append(text)

        result[parsed_date] = muscles

    log.info("Parsed %d muscle-focus entries", len(result))
    return result


def _parse_date(text: str) -> Optional[date]:
    """Parse strings like 'April 3, 2026' or 'March 27, 2026'."""
    for fmt in ("%B %d, %Y", "%b %d, %Y"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    log.warning("Could not parse date: %r", text)
    return None


def muscles_for_date(focus_map: dict[date, list[str]], d: date) -> list[str]:
    return focus_map.get(d, [])


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    data = fetch_muscle_focus()
    for d, muscles in sorted(data.items()):
        print(f"{d}: {', '.join(muscles)}")
