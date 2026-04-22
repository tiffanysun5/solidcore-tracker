#!/usr/bin/env python3
"""
Wellhub change detector — run every 15 min by wellhub_watch.yml.

Fetches current upcoming Wellhub bookings and compares against saved state.
If anything changed (booking added or cancelled directly in the Wellhub app),
runs the full main.py digest so you get a fresh email with updated info.

Also auto-books the best slot for the new day (today + BOOKING_WINDOW_DAYS)
when it first becomes available, preferring 12:05 or 12:15 pm.
"""

from __future__ import annotations

import logging
import os
import subprocess
import sys
from datetime import date, datetime, timedelta
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

# ── Auto-booking preferences ───────────────────────────────────────────────
# Preferred class start times (hour, minute) — tried in order.
PREF_TIMES = [(12, 5), (12, 15)]
# After these, any class in 11am–2pm is acceptable.
PREFERRED_START = 11
PREFERRED_END   = 14  # exclusive

# For class DATES within the next N days from today, avoid booking before AVOID_BEFORE_HOUR.
AVOID_EARLY_DAYS  = 7     # next week
AVOID_BEFORE_HOUR = 11    # 9am–10:59am excluded

# Class types to skip for auto-booking (case-insensitive substring of class_name).
EXCLUDE_CLASS_TYPES = ["power30", "intro", "starter50"]

# ── Notification email via SMTP ────────────────────────────────────────────
SMTP_HOST = os.getenv("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER = os.getenv("SMTP_USER", "")
SMTP_PASS = os.getenv("SMTP_PASSWORD", "")


def _send_auto_book_email(slot, to_email: str, success: bool, reason: str = "") -> None:
    """Send a quick confirmation (or failure notice) for an auto-booking attempt."""
    import smtplib
    from email.mime.multipart import MIMEMultipart
    from email.mime.text import MIMEText

    if success:
        subject = f"🍑 Auto-booked: Solidcore {slot.date_str} {slot.time_str} — {slot.studio}"
        status_html = (
            f"<p style='color:#059669;font-size:16px;font-weight:700'>✅ Booking confirmed!</p>"
            f"<p><strong>{slot.date_str}</strong> &nbsp;·&nbsp; {slot.time_str} &nbsp;·&nbsp; "
            f"{slot.studio} &nbsp;·&nbsp; {slot.instructor}</p>"
        )
    else:
        subject = f"⚠️ Auto-book attempted — Solidcore {slot.date_str} {slot.time_str} (failed)"
        status_html = (
            f"<p style='color:#dc2626;font-size:16px;font-weight:700'>❌ Booking failed</p>"
            f"<p><strong>{slot.date_str}</strong> &nbsp;·&nbsp; {slot.time_str} &nbsp;·&nbsp; "
            f"{slot.studio} &nbsp;·&nbsp; {slot.instructor}</p>"
            + (f"<p style='color:#888;font-size:13px'>Reason: {reason}</p>" if reason else "")
        )

    html = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"></head>
<body style="font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;background:#f5f5f5;margin:0;padding:20px">
<div style="max-width:480px;margin:0 auto;background:#fff;border-radius:12px;overflow:hidden;box-shadow:0 2px 8px rgba(0,0,0,.1)">
  <div style="background:#111;color:#fff;padding:18px 24px">
    <h1 style="margin:0;font-size:18px">🍑 Auto-book result</h1>
  </div>
  <div style="padding:20px 24px">
    {status_html}
  </div>
  <div style="padding:10px 24px;font-size:11px;color:#aaa;border-top:1px solid #f0f0f0">
    solidcore-tracker auto-booker
  </div>
</div>
</body></html>"""

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"]    = SMTP_USER
    msg["To"]      = to_email
    msg.attach(MIMEText(html, "html"))

    try:
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as s:
            s.starttls()
            s.login(SMTP_USER, SMTP_PASS)
            s.sendmail(SMTP_USER, to_email, msg.as_string())
        log.info("Auto-book email sent to %s", to_email)
    except Exception as exc:
        log.error("Failed to send auto-book email: %s", exc)


def _rank_slot(slot, today: date) -> tuple:
    """
    Lower = better for auto-booking.
    Priority:
      0 — exact preferred time (12:05 or 12:15)
      1 — other preferred window (11am–2pm)
      2 — anything else
    Then sort by time within each tier.
    """
    h, m = slot.dt.hour, slot.dt.minute
    # Avoid early classes for dates within the next AVOID_EARLY_DAYS
    days_out = (slot.date - today).days
    if days_out <= AVOID_EARLY_DAYS and h < AVOID_BEFORE_HOUR:
        return (99, h, m)  # deprioritise completely
    if (h, m) in PREF_TIMES:
        return (0, h, m)
    if PREFERRED_START <= h < PREFERRED_END:
        return (1, h, m)
    return (2, h, m)


def _try_auto_book(today: date, booked_dates: set[date]) -> bool:
    """
    Check if the new-day slot (today + BOOKING_WINDOW_DAYS) is unbooked,
    and if so, fetch the schedule and book the best available class.

    Returns True if a booking was successfully made.
    """
    from src.config import BOOKING_WINDOW_DAYS, STUDIOS, NOTIFY_EMAIL
    from src.state import load_auto_booked_days, save_auto_booked_days
    from src.wellhub_api import get_schedule, book_class

    new_day = today + timedelta(days=BOOKING_WINDOW_DAYS)

    # Already attempted for this new_day?
    auto_booked = load_auto_booked_days()
    if new_day.isoformat() in auto_booked:
        log.info("Auto-book already attempted for %s — skipping", new_day)
        return False

    # Already have a booking that day?
    if new_day in booked_dates:
        log.info("Already booked on %s — skipping auto-book", new_day)
        auto_booked.add(new_day.isoformat())
        save_auto_booked_days(auto_booked)
        return False

    log.info("Fetching schedule to auto-book new day: %s", new_day)
    try:
        slots = get_schedule()
    except Exception as exc:
        log.error("Could not fetch schedule for auto-book: %s", exc)
        return False

    # Log actual booking window for verification
    if slots:
        max_date = max(s.date for s in slots)
        min_date = min(s.date for s in slots)
        log.info("API booking window: %s → %s (%d days ahead)",
                 min_date, max_date, (max_date - today).days)

    approved_instructors = {
        name.lower().rstrip(".")
        for cfg in STUDIOS.values()
        for name in cfg["instructors"]
    }

    def _instructor_ok(instructor: str) -> bool:
        norm = instructor.strip().lower().rstrip(".")
        for approved in approved_instructors:
            if norm == approved or norm.startswith(approved.split(".")[0].rstrip()):
                return True
        return False

    # Filter candidates for new_day
    candidates = []
    for s in slots:
        if s.date != new_day:
            continue
        if s.available_spots <= 0:
            continue
        class_lower = s.class_name.lower()
        if any(ex in class_lower for ex in EXCLUDE_CLASS_TYPES):
            log.debug("Skipping %s — excluded class type", s.class_name)
            continue
        if not _instructor_ok(s.instructor):
            log.debug("Skipping %s %s — instructor not approved", s.time_str, s.instructor)
            continue
        candidates.append(s)

    if not candidates:
        log.info("No bookable candidates for %s — will retry next run", new_day)
        # Don't mark as attempted yet; maybe slots will open later
        return False

    # Rank and pick best
    candidates.sort(key=lambda s: _rank_slot(s, today))
    best = candidates[0]
    rank = _rank_slot(best, today)
    log.info("Best candidate for %s: %s %s %s (rank=%s, spots=%d)",
             new_day, best.time_str, best.studio, best.instructor, rank, best.available_spots)

    # Attempt booking
    booked = False
    fail_reason = ""
    try:
        booked = book_class(
            class_id=best.wellhub_class_id,
            class_id_gql=best.class_id_gql,
            partner_id=best.partner_id,
        )
    except RuntimeError as exc:
        fail_reason = str(exc)
        log.error("Auto-book restriction for %s: %s", best.wellhub_class_id, exc)
    except Exception as exc:
        fail_reason = str(exc)
        log.error("Auto-book error for %s: %s", best.wellhub_class_id, exc)

    # Mark as attempted (so we don't spam retries on failure)
    auto_booked.add(new_day.isoformat())
    save_auto_booked_days(auto_booked)

    # Send confirmation email
    _send_auto_book_email(best, NOTIFY_EMAIL, success=booked, reason=fail_reason)

    if booked:
        log.info("✅ Auto-booked %s %s %s", new_day, best.time_str, best.studio)
    else:
        log.warning("❌ Auto-book failed for %s", new_day)

    return booked


def main() -> None:
    if not os.environ.get("WELLHUB_REFRESH_TOKEN"):
        log.error("WELLHUB_REFRESH_TOKEN not set")
        sys.exit(1)

    from zoneinfo import ZoneInfo
    from src.wellhub_api import get_upcoming_bookings
    from src.state import load_booking_ids, save_booking_ids

    today = datetime.now(tz=ZoneInfo("America/New_York")).date()

    log.info("Fetching current Wellhub bookings...")
    try:
        bookings = get_upcoming_bookings()
    except Exception as exc:
        log.error("Failed to fetch bookings: %s", exc)
        sys.exit(1)

    upcoming        = [b for b in bookings if not b.completed]
    current_ids     = {b.attendance_id for b in upcoming if b.attendance_id}
    booked_dates    = {b.dt.date() for b in upcoming}
    saved_ids       = load_booking_ids()

    added   = current_ids - saved_ids
    removed = saved_ids   - current_ids

    # ── Auto-book new day ──────────────────────────────────────────────────
    auto_booked = _try_auto_book(today, booked_dates)

    if not added and not removed and not auto_booked:
        log.info("No booking changes detected — nothing to do.")
        return

    if added:
        log.info("Booking change detected! +%d added, -%d removed", len(added), len(removed))
        log.info("  Added:   %s", added)
    if removed:
        log.info("  Removed: %s", removed)

    # Save updated state
    save_booking_ids(current_ids)

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
