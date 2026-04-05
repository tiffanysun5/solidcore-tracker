#!/usr/bin/env python3
"""
Sync Wellhub bookings → Google Calendar.

Run locally:   python sync_cal.py
Run in CI:     python sync_cal.py  (needs GOOGLE_* env vars)
"""

from __future__ import annotations
import logging
import os
import sys
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
    missing = [k for k in ("GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET", "GOOGLE_REFRESH_TOKEN")
               if not os.environ.get(k)]
    if missing:
        log.error("Missing env vars: %s — run setup_gcal.py first", ", ".join(missing))
        sys.exit(1)

    log.info("Fetching upcoming Wellhub bookings...")
    from src.wellhub_api import get_upcoming_bookings
    bookings = get_upcoming_bookings()
    log.info("  %d upcoming bookings found", len(bookings))
    for b in bookings:
        log.info("  • %s  %s  %s", b.dt.strftime("%a %b %-d %-I:%M %p"), b.studio_name, b.class_name)

    log.info("Syncing to Google Calendar...")
    from src.gcal import sync_calendar
    created, deleted = sync_calendar(bookings)
    log.info("Done: %d created, %d deleted", created, deleted)

if __name__ == "__main__":
    main()
