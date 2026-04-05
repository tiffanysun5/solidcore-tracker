#!/usr/bin/env python3
"""
Main orchestrator — daily scrape + filter + email digest.

Run locally:
  python main.py

Run in CI (GitHub Actions daily.yml):
  python main.py --headless

Environment variables required:
  WELLHUB_EMAIL, WELLHUB_PASSWORD  — Wellhub login
  SMTP_USER, SMTP_PASSWORD         — Gmail SMTP (App Password)
  GITHUB_REPO                      — e.g. "tiffanysun/solidcore-tracker" (for booking link)
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from datetime import datetime
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

STATE_FILE = Path("state/last_matches.json")


def main() -> None:
    parser = argparse.ArgumentParser(description="Solidcore class tracker")
    parser.add_argument("--headless", action="store_true", default=False,
                        help="Run Wellhub browser headless (use in CI)")
    parser.add_argument("--no-email", action="store_true",
                        help="Skip sending email (print digest to stdout)")
    parser.add_argument("--force-email", action="store_true",
                        help="Send email even if no new classes since last run")
    args = parser.parse_args()

    email    = os.environ.get("WELLHUB_EMAIL", "")
    password = os.environ.get("WELLHUB_PASSWORD", "")

    if not email or not password:
        log.error("WELLHUB_EMAIL and WELLHUB_PASSWORD must be set in environment")
        sys.exit(1)

    # ── 1. Scrape muscle focus (public, no auth) ──────────────────────────
    log.info("Step 1: Fetching muscle focus calendar")
    from src.muscle_focus import fetch_muscle_focus
    focus_map = fetch_muscle_focus()
    log.info("  Got %d days of muscle focus data", len(focus_map))

    # ── 2. Scrape Wellhub schedule ─────────────────────────────────────────
    log.info("Step 2: Scraping Wellhub schedule (headless=%s)", args.headless)
    from src.wellhub import get_schedule
    slots = get_schedule(email, password, headless=args.headless)
    log.info("  Got %d total class slots", len(slots))

    # ── 3. Apply filters ───────────────────────────────────────────────────
    log.info("Step 3: Applying filters")
    from src.filters import apply_filters
    matches = apply_filters(slots, focus_map)
    log.info("  %d classes match all criteria", len(matches))

    if not matches:
        log.info("No matching classes — nothing to do")
        return

    # ── 4. Check for new classes since last run ────────────────────────────
    previous_ids = _load_previous_ids()
    current_ids  = {m.slot.wellhub_class_id for m in matches}
    new_ids      = current_ids - previous_ids
    log.info(
        "  %d total matches, %d new since last run",
        len(matches), len(new_ids),
    )

    should_email = args.force_email or bool(new_ids) or not previous_ids
    if not should_email:
        log.info("No new classes — skipping email (use --force-email to override)")
        _save_current_ids(current_ids)
        return

    # ── 5. Send email digest + iMessage ───────────────────────────────────
    from src.config import NOTIFY_EMAIL
    from src.email_digest import send_digest
    from src.imessage import send_imessage

    if args.no_email:
        log.info("--no-email flag set — printing digest to stdout")
        _print_digest(matches)
    else:
        log.info("Step 4: Sending email digest to %s", NOTIFY_EMAIL)
        send_digest(matches, NOTIFY_EMAIL)
        log.info("Step 5: Sending iMessage")
        send_imessage(matches)

    # ── 6. Persist state ──────────────────────────────────────────────────
    _save_current_ids(current_ids)
    log.info("Done.")


def _load_previous_ids() -> set[str]:
    if not STATE_FILE.exists():
        return set()
    try:
        data = json.loads(STATE_FILE.read_text())
        return set(data.get("class_ids", []))
    except Exception as exc:
        log.warning("Could not load state file: %s", exc)
        return set()


def _save_current_ids(ids: set[str]) -> None:
    STATE_FILE.parent.mkdir(exist_ok=True)
    STATE_FILE.write_text(
        json.dumps({"class_ids": sorted(ids), "updated": datetime.now().isoformat()}, indent=2)
    )


def _print_digest(matches) -> None:
    from src.filters import MatchedClass
    preferred = [m for m in matches if m.preferred_time]
    other     = [m for m in matches if not m.preferred_time]

    def render(group: list[MatchedClass], label: str) -> None:
        if not group:
            return
        print(f"\n{'─'*60}")
        print(f"  {label}")
        print(f"{'─'*60}")
        for m in group:
            print(
                f"  {m.slot.date_str}  {m.slot.time_str:<10}  "
                f"{m.slot.studio:<20}  {m.slot.instructor:<15}  "
                f"{', '.join(m.muscles)}"
            )
            print(f"    ID: {m.slot.wellhub_class_id}")

    print(f"\n{'='*60}")
    print(f"  SOLIDCORE TRACKER — {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"  {len(matches)} matching classes")
    print(f"{'='*60}")
    render(preferred, "⭐ PREFERRED (11am–2pm)")
    render(other,     "   OTHER TIMES")
    print()


if __name__ == "__main__":
    main()
