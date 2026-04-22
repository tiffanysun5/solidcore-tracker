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


# ── Spot-watch state ──────────────────────────────────────────────────────────

def load_spot_state() -> dict[str, int]:
    """Return saved {slot_key: available_spots} from the last run."""
    f = STATE_DIR / "spot_watch_state.json"
    if f.exists():
        try:
            return json.loads(f.read_text()).get("spots", {})
        except Exception as exc:
            log.warning("Could not read spot_watch_state.json: %s", exc)
    return {}


def save_spot_state(spots: dict[str, int]) -> None:
    """Persist current {slot_key: available_spots}."""
    STATE_DIR.mkdir(exist_ok=True)
    (STATE_DIR / "spot_watch_state.json").write_text(
        json.dumps({"spots": spots, "updated": date.today().isoformat()}, indent=2)
    )
    log.info("Spot state saved: %d slots tracked", len(spots))


# ── Persistent completed-visit cache ─────────────────────────────────────────
# Accumulates completed visits so they never fall off the API's short window.
# Format: {"YYYY-MM": ["YYYY-MM-DD", ...], ...}

def load_visit_cache() -> dict[str, list[str]]:
    """Return {month_str: [date_str, ...]} of all known completed visits."""
    f = STATE_DIR / "visit_cache.json"
    if f.exists():
        try:
            return json.loads(f.read_text())
        except Exception as exc:
            log.warning("Could not read visit_cache.json: %s", exc)
    return {}


def save_visit_cache(cache: dict[str, list[str]]) -> None:
    STATE_DIR.mkdir(exist_ok=True)
    (STATE_DIR / "visit_cache.json").write_text(json.dumps(cache, indent=2))


# Known visits that fell off the API window — seeded here so Actions cache
# gets the right count on first run.  Add entries whenever the API misses one.
_VISIT_SEEDS: dict[str, list[str]] = {
    "2026-04|nofar": ["2026-04-02", "2026-04-07", "2026-04-10", "2026-04-15", "2026-04-18"],
}


def merge_visits(studio_keyword: str, new_dates: list[date]) -> list[date]:
    """
    Merge newly-seen visit dates for studio_keyword into the cache and return
    the full known list for the current month.
    """
    month_key = date.today().strftime("%Y-%m") + "|" + studio_keyword
    cache = load_visit_cache()
    # Start from seeds so known-historical visits are never lost
    existing = set(_VISIT_SEEDS.get(month_key, []))
    existing.update(cache.get(month_key, []))
    for d in new_dates:
        existing.add(d.isoformat())
    cache[month_key] = sorted(existing)
    save_visit_cache(cache)
    return [date.fromisoformat(s) for s in cache[month_key]]
