#!/usr/bin/env python3
"""
Sync Wellhub bookings → docs/calendar.ics (hosted on GitHub Pages).

Any calendar app (Google Calendar, Apple Calendar, Outlook) can subscribe to:
  https://tiffanysun5.github.io/solidcore-tracker/calendar.ics

No Google credentials or API keys needed — just a public URL.

Run locally:  python sync_cal.py
Run in CI:    python sync_cal.py  (needs WELLHUB_REFRESH_TOKEN)
"""

from __future__ import annotations
import logging
import os
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)

# Load .env
_env = Path(__file__).parent / ".env"
if _env.exists():
    for _line in _env.read_text().splitlines():
        _line = _line.strip()
        if _line and not _line.startswith("#") and "=" in _line:
            _k, _, _v = _line.partition("=")
            os.environ.setdefault(_k.strip(), _v.strip())


def main():
    log.info("Fetching upcoming Wellhub bookings...")
    from src.wellhub_api import get_upcoming_bookings
    bookings = get_upcoming_bookings()
    log.info("  %d upcoming bookings found", len(bookings))
    for b in bookings:
        log.info("  • %s  %s  %s",
                 b.dt.strftime("%a %b %-d %-I:%M %p"),
                 b.studio_name.replace("[solidcore] ", ""),
                 b.class_name)

    log.info("Generating calendar.ics...")
    from src.ical import generate_ics
    ics_content = generate_ics(bookings)

    out_path = Path(__file__).parent / "docs" / "calendar.ics"
    out_path.write_text(ics_content, encoding="utf-8")
    log.info("Written %d events to %s", len(bookings), out_path)


if __name__ == "__main__":
    main()
