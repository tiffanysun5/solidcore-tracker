"""
Persist booking state between runs — used for change detection.

Files written to state/ directory (persisted via GitHub Actions cache):
  bookings_state.json  — set of upcoming attendance IDs + timestamp
  last_sent_date.txt   — ISO date of last email send (dedup guard)
"""

from __future__ import annotations

import json
import logging
from datetime import date
from pathlib import Path

log = logging.getLogger(__name__)

STATE_DIR = Path(__file__).parent.parent / "state"


def load_booking_ids() -> set[str]:
    """Return the set of upcoming attendance IDs from the last saved state."""
    f = STATE_DIR / "bookings_state.json"
    if f.exists():
        try:
            return set(json.loads(f.read_text()).get("ids", []))
        except Exception as exc:
            log.warning("Could not read bookings_state.json: %s", exc)
    return set()


def save_booking_ids(ids: set[str]) -> None:
    """Persist the current set of upcoming attendance IDs."""
    STATE_DIR.mkdir(exist_ok=True)
    (STATE_DIR / "bookings_state.json").write_text(
        json.dumps({"ids": sorted(ids), "updated": date.today().isoformat()}, indent=2)
    )
    log.info("State saved: %d booking IDs", len(ids))


def already_sent_today() -> bool:
    """Return True if an email was already sent during today's date (ET)."""
    f = STATE_DIR / "last_sent_date.txt"
    if f.exists():
        return f.read_text().strip() == date.today().isoformat()
    return False


def mark_sent_today() -> None:
    """Record that the email digest was sent today."""
    STATE_DIR.mkdir(exist_ok=True)
    (STATE_DIR / "last_sent_date.txt").write_text(date.today().isoformat())
    log.info("Marked email as sent today (%s)", date.today().isoformat())
