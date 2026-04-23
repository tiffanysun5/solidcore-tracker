#!/usr/bin/env python3
"""
Spot watcher — checks if watched classes go from full → available.

Reads WATCH_DATE / WATCH_AFTER_HOUR from env (set by wellhub_watch.yml).
Falls back to tomorrow / 12 if not set.

Sends an alert email when spots open.  Run hourly alongside check_wellhub.py.
"""

from __future__ import annotations

import json
import logging
import os
import smtplib
import urllib.parse
from datetime import date, datetime, timedelta
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path
from zoneinfo import ZoneInfo

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

SMTP_HOST   = os.getenv("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT   = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER   = os.getenv("SMTP_USER", "")
SMTP_PASS   = os.getenv("SMTP_PASSWORD", "")
GITHUB_REPO = os.getenv("APP_REPO", os.getenv("GITHUB_REPO", "tiffanysun5/solidcore-tracker"))


def _book_url(slot) -> str:
    owner, _, repo = GITHUB_REPO.partition("/")
    params = urllib.parse.urlencode({
        "class_id":     slot.wellhub_class_id,
        "class_id_gql": slot.class_id_gql,
        "partner_id":   slot.partner_id,
        "studio":       slot.studio,
        "instructor":   slot.instructor,
        "dt":           f"{slot.date_str} {slot.time_str}",
        "muscles":      "",
        "repo":         GITHUB_REPO,
    })
    return f"https://{owner}.github.io/{repo}/book.html?{params}"


def _cancel_url(booking, open_slots: list | None = None) -> str:
    owner, _, repo = GITHUB_REPO.partition("/")
    alts = []
    for s in (open_slots or []):
        alts.append({
            "cid":  s.wellhub_class_id,
            "cgql": s.class_id_gql,
            "pid":  s.partner_id,
            "s":    s.studio,
            "i":    s.instructor,
            "t":    f"{s.date_str} {s.time_str}",
            "m":    "",
            "sp":   s.available_spots,
        })
    params = urllib.parse.urlencode({
        "attendance_id": booking.attendance_id,
        "studio":        booking.studio_name,
        "dt":            booking.dt.strftime("%a %b %-d %-I:%M %p"),
        "repo":          GITHUB_REPO,
        "alts":          json.dumps(alts),
    })
    return f"https://{owner}.github.io/{repo}/cancel.html?{params}"


def _send_alert(slots: list, to_email: str, cancel_booking=None) -> None:
    rows = ""
    for s in slots:
        sp = s.available_spots
        sp_color = "#059669" if sp >= 3 else "#f59e0b"
        book_url = _book_url(s)
        rows += (
            f"<tr>"
            f"<td style='padding:10px 12px;font-size:14px;font-weight:600;white-space:nowrap'>{s.time_str}</td>"
            f"<td style='padding:10px 12px;font-size:14px;color:#2563eb;font-weight:500'>{s.studio}</td>"
            f"<td style='padding:10px 12px;font-size:14px;color:#555'>{s.instructor}</td>"
            f"<td style='padding:10px 12px;font-size:13px;font-weight:700;color:{sp_color}'>{sp} spot{'s' if sp != 1 else ''}</td>"
            f"<td style='padding:10px 12px'>"
            f"<a href='{book_url}' style='background:#111;color:#fff;padding:7px 16px;border-radius:6px;"
            f"text-decoration:none;font-size:13px;font-weight:700;white-space:nowrap'>Book →</a>"
            f"</td>"
            f"</tr>"
        )

    date_label = slots[0].date_str if slots else "tomorrow"

    # If there's an existing booking to cancel first, build a single combined URL
    # (cancel.html with open slots pre-loaded as alts — cancel then book in one page)
    cancel_html = ""
    combined_url = None
    if cancel_booking:
        combined_url = _cancel_url(cancel_booking, open_slots=slots)
        cb_dt     = cancel_booking.dt.strftime("%a %b %-d %-I:%M %p")
        cb_studio = cancel_booking.studio_name
        cancel_html = (
            f"<div style='margin:0 28px 0;padding:14px 16px;background:#fef2f2;"
            f"border:1px solid #fecaca;border-radius:8px;display:flex;"
            f"align-items:center;justify-content:space-between;gap:12px'>"
            f"<div style='font-size:13px;color:#991b1b'>"
            f"<strong>Cancel first:</strong> {cb_studio} · {cb_dt}"
            f"</div>"
            f"<a href='{combined_url}' style='background:#dc2626;color:#fff;padding:7px 14px;"
            f"border-radius:6px;text-decoration:none;font-size:13px;font-weight:700;"
            f"white-space:nowrap'>Cancel &amp; book →</a>"
            f"</div>"
        )

    html = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"></head>
<body style="font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;background:#f5f5f5;margin:0;padding:20px">
<div style="max-width:580px;margin:0 auto;background:#fff;border-radius:12px;overflow:hidden;box-shadow:0 2px 8px rgba(0,0,0,.1)">
  <div style="background:#059669;color:#fff;padding:20px 28px">
    <h1 style="margin:0;font-size:20px">🍑 Spot opened up!</h1>
    <p style="margin:6px 0 0;font-size:13px;opacity:.85">Solidcore {date_label} — a class just became available</p>
  </div>
  {cancel_html}
  <div style="padding:20px 28px">
    <table style="width:100%;border-collapse:collapse">
      <thead>
        <tr style="border-bottom:2px solid #eee">
          <th style="text-align:left;padding:6px 12px;font-size:11px;color:#888;text-transform:uppercase;letter-spacing:.5px">Time</th>
          <th style="text-align:left;padding:6px 12px;font-size:11px;color:#888;text-transform:uppercase;letter-spacing:.5px">Studio</th>
          <th style="text-align:left;padding:6px 12px;font-size:11px;color:#888;text-transform:uppercase;letter-spacing:.5px">Instructor</th>
          <th style="text-align:left;padding:6px 12px;font-size:11px;color:#888;text-transform:uppercase;letter-spacing:.5px">Spots</th>
          <th></th>
        </tr>
      </thead>
      <tbody>{rows}</tbody>
    </table>
  </div>
  <div style="padding:12px 28px;font-size:11px;color:#aaa;border-top:1px solid #f0f0f0">
    🍑 solidcore-tracker spot watcher
  </div>
</div>
</body></html>"""

    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"🍑 Spot opened — Solidcore {date_label} ({len(slots)} class{'es' if len(slots) != 1 else ''})"
    msg["From"]    = SMTP_USER
    msg["To"]      = to_email
    msg.attach(MIMEText(html, "html"))

    try:
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as s:
            s.starttls()
            s.login(SMTP_USER, SMTP_PASS)
            s.sendmail(SMTP_USER, to_email, msg.as_string())
        log.info("Alert email sent to %s", to_email)
    except Exception as exc:
        log.error("Failed to send alert email: %s", exc)

    # ── SMS via Verizon email-to-text gateway ─────────────────────────────
    sms_addr = os.getenv("NOTIFY_SMS", "")
    if sms_addr:
        lines = [f"🍑 Spot open! Solidcore {date_label}"]
        for s in slots:
            lines.append(f"{s.time_str} · {s.studio} · {s.instructor} · {s.available_spots} spot{'s' if s.available_spots != 1 else ''}")
        if combined_url:
            lines.append(f"Cancel & book → {combined_url}")
        elif slots:
            lines.append(_book_url(slots[0]))
        sms_text = "\n".join(lines)
        sms_msg = MIMEText(sms_text)
        sms_msg["Subject"] = ""
        sms_msg["From"]    = SMTP_USER
        sms_msg["To"]      = sms_addr
        try:
            with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as s:
                s.starttls()
                s.login(SMTP_USER, SMTP_PASS)
                s.sendmail(SMTP_USER, sms_addr, sms_msg.as_string())
            log.info("SMS alert sent to %s", sms_addr)
        except Exception as exc:
            log.error("Failed to send SMS alert: %s", exc)


def main() -> None:
    if not os.environ.get("WELLHUB_REFRESH_TOKEN"):
        log.error("WELLHUB_REFRESH_TOKEN not set")
        return

    ny    = ZoneInfo("America/New_York")
    now   = datetime.now(tz=ny)
    today = now.date()

    after_hour       = int(os.getenv("WATCH_AFTER_HOUR",    "12"))  # noon
    done_by_hour     = int(os.getenv("WATCH_DONE_BY_HOUR",  "17"))  # 5pm
    done_by_min      = int(os.getenv("WATCH_DONE_BY_MIN",   "0"))
    class_duration_min = 50

    # Always watch today (slots still in the future) + tomorrow.
    # If WATCH_DATE is set, watch that specific date only.
    watch_date_str = os.getenv("WATCH_DATE", "")
    if watch_date_str:
        try:
            watch_dates = [date.fromisoformat(watch_date_str)]
        except ValueError:
            watch_dates = [today, today + timedelta(days=1)]
    else:
        watch_dates = [today, today + timedelta(days=1)]

    # Drop dates that are fully in the past
    watch_dates = [d for d in watch_dates if d >= today]
    if not watch_dates:
        log.info("All watch dates have passed — nothing to do.")
        return

    # WATCH_EXCLUDE: comma-separated extra class type keywords to skip (on top of defaults)
    _extra_excl = [x.strip().lower() for x in os.getenv("WATCH_EXCLUDE", "").split(",") if x.strip()]
    EXCLUDE_TYPES = ["power30", "intro", "starter50"] + _extra_excl

    log.info("Watching %s | after %d:00, done by %d:%02d, excl %s",
             watch_dates, after_hour, done_by_hour, done_by_min, EXCLUDE_TYPES)

    from src.wellhub_api import get_schedule, get_upcoming_bookings
    from src.state import load_spot_state, save_spot_state
    from src.config import NOTIFY_EMAIL

    try:
        slots = get_schedule()
    except Exception as exc:
        log.error("Could not fetch schedule: %s", exc)
        return

    # Find any upcoming booking on a different day that may need cancelling first
    # (e.g. Friday class when watching for Thursday openings).
    # We look for Solidcore bookings NOT on the watch dates and surface the soonest one.
    cancel_booking = None
    try:
        bookings = get_upcoming_bookings()
        upcoming = [b for b in bookings if not b.completed and b.dt > now
                    and b.date not in watch_dates
                    and "[solidcore]" in b.studio_name.lower()]
        if upcoming:
            cancel_booking = min(upcoming, key=lambda b: b.dt)
            log.info("Cancel-first booking found: %s %s", cancel_booking.studio_name, cancel_booking.dt)
    except Exception as exc:
        log.warning("Could not fetch bookings for cancel banner: %s", exc)

    def finishes_by(s) -> bool:
        end_dt = s.dt + timedelta(minutes=class_duration_min)
        return (end_dt.hour, end_dt.minute) <= (done_by_hour, done_by_min)

    def still_upcoming(s) -> bool:
        """For today's classes: only watch ones that haven't started yet."""
        if s.date > today:
            return True
        return s.dt > now  # today: must be in the future

    def is_excluded(s) -> bool:
        return any(ex in s.class_name.lower() for ex in EXCLUDE_TYPES)

    target = [
        s for s in slots
        if s.date in watch_dates
        and s.dt.hour >= after_hour
        and finishes_by(s)
        and still_upcoming(s)
        and not is_excluded(s)
    ]
    log.info("Found %d eligible slots across %s", len(target), watch_dates)

    def slot_key(s) -> str:
        return f"{s.date}|{s.dt.hour:02d}:{s.dt.minute:02d}|{s.studio}"

    current:  dict[str, int] = {slot_key(s): s.available_spots for s in target}
    previous: dict[str, int] = load_spot_state()

    # A spot "opened" = was 0 (or unseen) last run, now > 0
    newly_open = [
        s for s in target
        if s.available_spots > 0 and previous.get(slot_key(s), 0) == 0
    ]

    # ── Also watch Nofar 10am–11am tomorrow ──────────────────────────────────
    nofar_newly_open = _watch_nofar(now, today, slot_key)

    save_spot_state(current)

    all_newly_open = newly_open + nofar_newly_open
    if not all_newly_open:
        log.info("No newly-opened spots — all good.")
        return

    log.info("%d class(es) just opened up: %s",
             len(all_newly_open), [slot_key(s) for s in all_newly_open])

    _send_alert(all_newly_open, NOTIFY_EMAIL, cancel_booking=cancel_booking)


def _watch_nofar(now: datetime, today: date, slot_key) -> list:
    """Fetch Nofar tomorrow 10am–11am and return any newly-opened slots."""
    from src.wellhub_api import _gql, SCHEDULE_QUERY, LAT, LNG, ClassSlot
    from src.state import load_spot_state, save_spot_state
    from datetime import timezone

    tomorrow = today + timedelta(days=1)
    NOFAR_PARTNER_ID = "0a283587-673b-4cea-9796-68b5bf387ae1"
    NOFAR_STUDIO     = "Nofar Method - Flatiron"
    NOFAR_WATCH_HOURS = {10, 11}   # watch 10am and 11am classes

    start = datetime(tomorrow.year, tomorrow.month, tomorrow.day, 4, 0, 0, tzinfo=timezone.utc)
    end   = start + timedelta(hours=23, minutes=59, seconds=59)

    try:
        results = _gql([{
            "operationName": "partnerClassSchedule",
            "variables": {
                "partnerId": NOFAR_PARTNER_ID,
                "filters": {
                    "startDate": start.strftime("%Y-%m-%dT%H:%M:%S.000Z"),
                    "endDate":   end.strftime("%Y-%m-%dT%H:%M:%S.999Z"),
                },
                "deviceLocation": {"coordinates": [LAT, LNG], "type": "shared"},
            },
            "query": SCHEDULE_QUERY,
        }])
        items = (results[0].get("data", {})
                 .get("partnerClassSchedule", {})
                 .get("items", []))
    except Exception as exc:
        log.warning("Nofar fetch failed: %s", exc)
        return []

    from zoneinfo import ZoneInfo
    ny = ZoneInfo("America/New_York")
    slots = []
    for item in items:
        if item.get("isDisabled"):
            continue
        try:
            dt = datetime.fromisoformat(item["date"].replace("Z", "+00:00")).astimezone(ny)
        except Exception:
            continue
        if dt.hour not in NOFAR_WATCH_HOURS:
            continue
        instructors = item.get("instructors", [])
        instructor  = instructors[0]["name"].split(" - ")[0].strip() if instructors else ""
        slot = ClassSlot(
            wellhub_class_id = item.get("id", ""),
            class_id_gql     = str(item.get("classId", "")),
            partner_id       = NOFAR_PARTNER_ID,
            studio           = NOFAR_STUDIO,
            instructor       = instructor,
            dt               = dt,
            available_spots  = item.get("availableSpots", 0),
            class_name       = item.get("name", ""),
        )
        slots.append(slot)

    log.info("Nofar tomorrow 10–11am: %d slots found", len(slots))

    # Load/save nofar-specific state (separate key prefix to avoid Solidcore collision)
    state = load_spot_state()
    newly_open = [
        s for s in slots
        if s.available_spots > 0 and state.get("nofar|" + slot_key(s), 0) == 0
    ]

    # Merge nofar state into the shared state dict and save
    nofar_state = {"nofar|" + slot_key(s): s.available_spots for s in slots}
    state.update(nofar_state)
    save_spot_state(state)

    return newly_open


if __name__ == "__main__":
    main()
