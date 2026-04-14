#!/usr/bin/env python3
"""
Wellhub change detector — run hourly by wellhub_watch.yml.

Fetches current upcoming Wellhub bookings and compares against saved state.
If anything changed (booking added or cancelled directly in the Wellhub app),
runs the full main.py digest so you get a fresh email with updated info.
"""

from __future__ import annotations

import logging
import os
import subprocess
import sys
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger(__name__)

# Load .env if present
_env = Path(".env")
if _env.exists():
    for line in _env.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, _, v = line.partition("=")
            os.environ.setdefault(k.strip(), v.strip())


def main() -> None:
    if not os.environ.get("WELLHUB_REFRESH_TOKEN"):
        log.error("WELLHUB_REFRESH_TOKEN not set")
        sys.exit(1)

    from src.wellhub_api import get_upcoming_bookings
    from src.state import load_booking_ids, save_booking_ids

    log.info("Fetching current Wellhub bookings...")
    try:
        bookings = get_upcoming_bookings()
    except Exception as exc:
        log.error("Failed to fetch bookings: %s", exc)
        sys.exit(1)

    current_ids = {b.attendance_id for b in bookings if b.attendance_id and not b.completed}
    saved_ids   = load_booking_ids()

    added   = current_ids - saved_ids
    removed = saved_ids   - current_ids

    if not added and not removed:
        log.info("No booking changes detected — nothing to do.")
        return

    log.info("Booking change detected! +%d added, -%d removed", len(added), len(removed))
    if added:
        log.info("  Added:   %s", added)
    if removed:
        log.info("  Removed: %s", removed)

    # Send a fresh digest (--force-email bypasses the already-sent-today guard)
    log.info("Sending updated email digest...")
    result = subprocess.run(
        [sys.executable, "main.py", "--force-email"],
        check=False,
    )
    if result.returncode != 0:
        log.error("main.py exited with code %d", result.returncode)
        sys.exit(result.returncode)

    log.info("Done — updated email sent.")


if __name__ == "__main__":
    main()
