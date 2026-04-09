#!/usr/bin/env python3
"""
Main orchestrator — daily email digest.

Run locally:   python main.py
Run in CI:     python main.py  (needs WELLHUB_REFRESH_TOKEN, SMTP_* env vars)
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger(__name__)

# Load .env file if present (local development)
_env_path = Path(__file__).parent / ".env"
if _env_path.exists():
    for _line in _env_path.read_text().splitlines():
        _line = _line.strip()
        if _line and not _line.startswith("#") and "=" in _line:
            _k, _, _v = _line.partition("=")
            os.environ.setdefault(_k.strip(), _v.strip())


def main() -> None:
    parser = argparse.ArgumentParser(description="Solidcore class tracker")
    parser.add_argument("--headless", action="store_true", default=False,
                        help="(Ignored — kept for backwards compat)")
    parser.add_argument("--no-email", action="store_true",
                        help="Skip sending email (print digest to stdout)")
    parser.add_argument("--force-email", action="store_true",
                        help="Alias for normal send (kept for compat)")
    args = parser.parse_args()

    tokens_file = Path(__file__).parent / "tokens.json"
    if not os.environ.get("WELLHUB_REFRESH_TOKEN") and not tokens_file.exists():
        log.error("WELLHUB_REFRESH_TOKEN env var not set and tokens.json not found.")
        sys.exit(1)

    # ── 1. Muscle focus (public) ──────────────────────────────────────────
    log.info("Step 1: Fetching muscle focus calendar")
    from src.muscle_focus import fetch_muscle_focus
    focus_map = fetch_muscle_focus()
    log.info("  Got %d days of muscle focus data", len(focus_map))

    # ── 2. Bookings: upcoming reserved + recent completed (for quota) ────────
    log.info("Step 2: Fetching bookings + check-in history")
    from src.wellhub_api import get_upcoming_bookings, get_schedule, get_extra_slots
    all_bookings     = get_upcoming_bookings()
    upcoming_bookings = [b for b in all_bookings if not b.completed]
    booked_dates      = {b.dt.date() for b in upcoming_bookings}
    log.info("  %d upcoming bookings on dates: %s", len(upcoming_bookings), sorted(booked_dates))

    # ── 3. Wellhub schedule (14-day window) ───────────────────────────────
    log.info("Step 3: Fetching Wellhub schedule")
    slots = get_schedule()
    log.info("  Got %d total class slots", len(slots))

    # ── 3b. Extra studios (Nofar, CorePower) ──────────────────────────────
    log.info("Step 3b: Fetching extra studio slots")
    extra_slots = get_extra_slots()
    log.info("  Got %d extra slots", len(extra_slots))

    # ── 4. Filter — skip already-booked days ─────────────────────────────
    log.info("Step 4: Applying filters")
    from src.filters import apply_filters
    matches = apply_filters(slots, focus_map, booked_dates=booked_dates)  # uses upcoming only
    log.info("  %d classes match all criteria", len(matches))

    # ── 5. The "new" day = today + 14 (just opened this morning) ─────────
    from zoneinfo import ZoneInfo
    today   = datetime.now(tz=ZoneInfo("America/New_York")).date()
    new_day = today + timedelta(days=14)
    log.info("  New day opening today: %s", new_day)

    # ── 6. Send email ─────────────────────────────────────────────────────
    from src.config import NOTIFY_EMAIL
    from src.email_digest import send_digest

    if args.no_email:
        log.info("--no-email: printing to stdout")
        _print_digest(matches, upcoming_bookings, new_day)
    else:
        log.info("Step 5: Sending email digest to %s", NOTIFY_EMAIL)
        # Pass all_bookings (upcoming + completed) so quota counts past check-ins too
        # Key by (date, hour, minute, studio_key) since booking class_id ≠ slot wellhub_class_id
        def _studio_key(name: str) -> str:
            n = name.lower()
            if "chelsea" in n: return "chelsea"
            if "greenwich" in n: return "greenwich"
            return n.split()[0] if n.split() else n
        slot_by_id = {
            (s.date, s.dt.hour, s.dt.minute, _studio_key(s.studio)): s
            for s in slots
        }
        send_digest(matches, all_bookings, upcoming_bookings, new_day, NOTIFY_EMAIL,
                    extra_slots=extra_slots, focus_map=focus_map, slot_by_id=slot_by_id,
                    all_slots=slots)

    log.info("Done.")


def _print_digest(matches, bookings, new_day: date) -> None:
    from zoneinfo import ZoneInfo
    ny = ZoneInfo("America/New_York")
    print(f"\n{'='*60}")
    print(f"  SOLIDCORE TRACKER — {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"{'='*60}")

    if bookings:
        print("\n── ALREADY BOOKED ──────────────────────────────────────")
        for b in sorted(bookings, key=lambda x: x.dt):
            title = b.class_name.split(" | ", 1)[-1] if " | " in b.class_name else b.class_name
            print(f"  {b.dt.strftime('%a %b %-d %-I:%M %p'):<22}  {title}")

    new_day_matches = [m for m in matches if m.slot.date == new_day]
    other_matches   = [m for m in matches if m.slot.date != new_day]

    if new_day_matches:
        print(f"\n── NEW DAY: {new_day.strftime('%a %b %-d')} ─────────────────────────────")
        for m in new_day_matches:
            star = "⭐ " if m.preferred_time else "   "
            print(f"  {star}{m.slot.time_str:<10}  {m.slot.instructor:<15}  {', '.join(m.muscles)}")

    if other_matches:
        print("\n── OTHER OPEN DAYS ──────────────────────────────────────")
        for m in other_matches:
            star = "⭐ " if m.preferred_time else "   "
            print(f"  {star}{m.slot.date_str:<14}  {m.slot.time_str:<10}  {m.slot.instructor:<15}  {', '.join(m.muscles)}")
    print()


if __name__ == "__main__":
    main()
