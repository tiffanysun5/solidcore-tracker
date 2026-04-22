"""
Build and send the daily email digest.

Layout:
  1. Weekly quota pills
  2. YOUR UPCOMING CLASSES — already booked
  3. NEW DAY — today+14 (just opened), preferred then backup
  4. OTHER OPEN DAYS — remaining unbooked days, preferred then backup
"""

from __future__ import annotations

import logging
import os
import smtplib
import urllib.parse
from datetime import date, datetime, timedelta
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from src.filters import MatchedClass

log = logging.getLogger(__name__)

SMTP_HOST     = os.getenv("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT     = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER     = os.getenv("SMTP_USER", "")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "")
GITHUB_REPO   = os.getenv("APP_REPO", os.getenv("GITHUB_REPO", "tiffanysun5/solidcore-tracker"))

CSS = """
body{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;background:#f5f5f5;margin:0;padding:20px;color:#222}
.wrap{max-width:660px;margin:0 auto;background:#fff;border-radius:12px;overflow:hidden;box-shadow:0 2px 8px rgba(0,0,0,.1)}
.hdr{background:#111;color:#fff;padding:22px 28px}
.hdr h1{margin:0;font-size:21px;letter-spacing:-.3px}
.hdr p{margin:5px 0 0;font-size:12px;opacity:.65}
.sec{padding:18px 28px}
.sec-title{font-size:10px;font-weight:700;letter-spacing:1.2px;text-transform:uppercase;color:#888;margin:0 0 10px}
.div{height:1px;background:#f0f0f0;margin:0 28px}
table{width:100%;border-collapse:collapse;font-size:13px}
th{text-align:left;color:#666;font-weight:600;font-size:11px;text-transform:uppercase;letter-spacing:.5px;padding:5px 8px;border-bottom:2px solid #eee;white-space:nowrap}
td{padding:9px 8px;border-bottom:1px solid #f5f5f5;vertical-align:middle}
.r-pref td:first-child{border-left:3px solid #f59e0b}
.r-pref{background:#fffbeb}
.r-backup td:first-child{border-left:3px solid #3b82f6}
.r-backup{background:#eff6ff}
.subhdr td{padding:5px 8px 3px;font-size:10px;font-weight:700;letter-spacing:.8px;text-transform:uppercase;color:#9ca3af;background:#f9fafb;border-bottom:1px solid #e5e7eb}
.badge{display:inline-block;font-size:9px;font-weight:700;padding:2px 5px;border-radius:3px;letter-spacing:.4px}
.bp{background:#fef3c7;color:#92400e}
.bb{background:#dbeafe;color:#1e40af}
.muscle{color:#059669;font-weight:600}
.muscle-sec{color:#6b7280;font-size:11px}
.empty{color:#aaa;font-size:13px;font-style:italic;margin:4px 0}
.book-btn{display:inline-block;background:#111;color:#fff!important;padding:5px 13px;border-radius:6px;text-decoration:none;font-size:12px;font-weight:600;white-space:nowrap}
.ftr{padding:14px 28px;font-size:11px;color:#aaa}
"""


def send_digest(
    matches:           list[MatchedClass],
    all_bookings:      list,
    upcoming_bookings: list,
    new_day:           date,
    to_email:          str,
    extra_slots:       list | None = None,
    focus_map:         dict | None = None,
    slot_by_id:        dict | None = None,
    all_slots:         list | None = None,
    new_day_all:       list | None = None,
    travel_city:       str | None = None,
    travel_slots:      list | None = None,
) -> None:
    subject, html_body = _build_email(matches, all_bookings, upcoming_bookings, new_day,
                                      extra_slots or [], focus_map or {}, slot_by_id or {},
                                      all_slots or [], new_day_all or [],
                                      travel_city=travel_city,
                                      travel_slots=travel_slots or [])
    _send(to_email, subject, html_body)


def _build_email(
    matches:           list[MatchedClass],
    all_bookings:      list,
    upcoming_bookings: list,
    new_day:           date,
    extra_slots:       list | None = None,
    focus_map:         dict | None = None,
    slot_by_id:        dict | None = None,
    slots:             list | None = None,
    new_day_all:       list | None = None,
    travel_city:       str | None = None,
    travel_slots:      list | None = None,
) -> tuple[str, str]:
    extra_slots  = extra_slots  or []
    focus_map    = focus_map    or {}
    slot_by_id   = slot_by_id   or {}
    slots        = slots        or []
    new_day_all  = new_day_all  or []
    travel_slots = travel_slots or []

    from zoneinfo import ZoneInfo
    ny    = ZoneInfo("America/New_York")
    today = datetime.now(tz=ny).date()

    new_day_matches = new_day_all if new_day_all else [m for m in matches if m.slot.date == new_day]
    other_matches   = [m for m in matches if m.slot.date != new_day]

    # Subject
    nc = len(new_day_matches)
    subject = (
        f"[Solidcore] {new_day.strftime('%a %b %-d')} — "
        f"{nc} new class{'es' if nc != 1 else ''} available"
        + (f"  ·  {len(other_matches)} other open day{'s' if len(other_matches) != 1 else ''}"
           if other_matches else "")
    )

    # Weekly quota — solidcore only (premium class limit per week)
    from src.config import WEEKLY_CLASS_LIMIT
    solidcore_bookings = [b for b in all_bookings if "[solidcore]" in b.studio_name.lower()]
    this_mon = today - timedelta(days=today.weekday())
    this_sun = this_mon + timedelta(days=6)
    next_mon = this_sun + timedelta(days=1)
    next_sun = next_mon + timedelta(days=6)
    LIMIT = WEEKLY_CLASS_LIMIT

    def wcount(bkgs, mon, sun):
        return sum(1 for b in bkgs if mon <= b.dt.date() <= sun)

    tw_left = LIMIT - wcount(solidcore_bookings, this_mon, this_sun)
    nw_left = LIMIT - wcount(solidcore_bookings, next_mon, next_sun)

    def pill(left):
        c = "#059669" if left > 1 else ("#f59e0b" if left == 1 else "#ef4444")
        return (f'<span style="background:{c};color:#fff;font-size:11px;font-weight:700;'
                f'padding:3px 10px;border-radius:20px;display:inline-block">'
                f'{left} of {LIMIT} left</span>')

    quota = (
        f'<div style="display:flex;gap:14px;flex-wrap:wrap;margin-bottom:14px">'
        f'<span style="font-size:12px;color:#555">This week ({this_mon.strftime("%-d %b")}–{this_sun.strftime("%-d %b")}): {pill(tw_left)}</span>'
        f'<span style="font-size:12px;color:#555">Next week ({next_mon.strftime("%-d %b")}–{next_sun.strftime("%-d %b")}): {pill(nw_left)}</span>'
        f'</div>'
    )

    # Monthly reminder — Othership + Stretch*d (once per month each)
    from src.config import MONTHLY_STUDIOS
    this_month_start = today.replace(day=1)
    monthly_sec = _monthly_reminder_section(all_bookings, this_month_start, today, MONTHLY_STUDIOS)

    # Booked section
    if upcoming_bookings:
        rows = ""
        tomorrow = today + timedelta(days=1)
        owner, _, repo_name = GITHUB_REPO.partition("/")
        for b in sorted(upcoming_bookings, key=lambda x: x.dt):
            title  = b.class_name.split(" | ", 1)[-1] if " | " in b.class_name else b.class_name
            studio = b.studio_name.replace("[solidcore] ", "").replace(", NY", "")
            cancel_btn = ""
            if b.attendance_id:
                # Build same-day alternatives — ALL Solidcore slots that day except the booked one
                day_muscles = focus_map.get(b.dt.date(), [])
                muscles_str = " + ".join(day_muscles)
                same_day_alts = []
                for s in slots:
                    if (s.date == b.dt.date()
                            and (s.dt.hour, s.dt.minute) != (b.dt.hour, b.dt.minute)):
                        same_day_alts.append({
                            "t":    s.time_str,
                            "s":    s.studio,
                            "i":    s.instructor,
                            "sp":   s.available_spots,
                            "cid":  s.wellhub_class_id,
                            "cgql": s.class_id_gql,
                            "pid":  s.partner_id,
                            "m":    muscles_str,
                        })
                same_day_alts.sort(key=lambda x: x["t"])
                import json as _json
                cp = urllib.parse.urlencode({
                    "attendance_id": b.attendance_id,
                    "studio":        studio,
                    "dt":            f"{b.dt.strftime('%a %b %-d')} {b.dt.strftime('%-I:%M %p')}",
                    "repo":          GITHUB_REPO,
                    "alts":          _json.dumps(same_day_alts, separators=(",", ":")),
                })
                cancel_url = f"https://{owner}.github.io/{repo_name}/cancel.html?{cp}"
                cancel_btn = f' <a href="{cancel_url}" style="font-size:11px;color:#dc2626;text-decoration:none;border:1px solid #dc2626;border-radius:4px;padding:2px 6px;white-space:nowrap">Cancel</a>'
            # Muscle focus + spots combined into one cell
            # Match by (date, hour, minute, studio_key) since booking class_id ≠ slot id
            def _sk(name: str) -> str:
                n = name.lower()
                if "chelsea" in n: return "chelsea"
                if "greenwich" in n: return "greenwich"
                return n.split()[0] if n.split() else n
            is_solidcore = "[solidcore]" in b.studio_name.lower()
            muscles = focus_map.get(b.dt.date(), []) if is_solidcore else []
            slot    = slot_by_id.get((b.dt.date(), b.dt.hour, b.dt.minute, _sk(b.studio_name)))
            muscle_line = (f'<span style="color:#059669;font-size:11px;font-weight:600">'
                           f'{" · ".join(muscles)}</span>' if muscles else '')
            # If slot not in schedule it's sold out (API only returns bookable slots)
            sp = slot.available_spots if slot else 0
            spots_line = (f'<span style="color:#6b7280;font-size:11px">'
                          f'({sp} spot{"s" if sp != 1 else ""})</span>')
            sep = '<br>' if muscle_line else ''
            focus_cell = muscle_line + sep + spots_line

            # Cancel deadline warning
            from src.config import CANCEL_WINDOWS
            from datetime import timedelta as _td
            sn_lower = b.studio_name.lower()
            cancel_hours = None
            for keyword, hours in CANCEL_WINDOWS.items():
                if keyword in sn_lower:
                    cancel_hours = hours
                    break
            cancel_warn = ""
            if cancel_hours:
                deadline = b.dt - _td(hours=cancel_hours)
                now_ny = datetime.now(tz=ZoneInfo("America/New_York"))
                if now_ny < deadline:
                    # Deadline is still in the future — show it
                    dl_str = deadline.strftime("%-I:%M %p") if deadline.date() == b.dt.date() else deadline.strftime("%a %-I:%M %p")
                    cancel_warn = (f'<br><span style="font-size:10px;color:#d97706;font-weight:600">'
                                   f'⚠️ Cancel by {dl_str}</span>')
                elif cancel_hours > 2:
                    # Past deadline — only badge for meaningful windows (≥ 4h); skip CorePower's 2h
                    cancel_warn = (f'<br><span style="font-size:10px;color:#dc2626;font-weight:600">'
                                   f'🚫 Late cancel window closed</span>')

            type_badge = _class_type_badge(slot.class_name) if slot and slot.class_name else ""
            type_str   = f"&nbsp;{type_badge}" if type_badge else ""
            rows += (
                f'<tr><td style="white-space:nowrap;color:#374151;font-weight:500">{b.dt.strftime("%a %b %-d")}</td>'
                f'<td style="white-space:nowrap;color:#6b7280">{b.dt.strftime("%-I:%M %p")}</td>'
                f'<td style="color:#2563eb;font-weight:500;white-space:nowrap">{studio}{cancel_warn}</td>'
                f'<td style="color:#111;width:50%;padding-left:24px">{title}{type_str}{cancel_btn}</td>'
                f'<td style="line-height:1.6;padding-left:32px;white-space:nowrap">{focus_cell}</td></tr>'
            )
        booked_tbl = (
            '<table><thead><tr><th>Date</th><th>Time</th><th>Studio</th>'
            '<th style="padding-left:24px;text-align:center">Class</th>'
            '<th style="padding-left:32px;white-space:nowrap">Muscle Focus</th></tr></thead>'
            f'<tbody>{rows}</tbody></table>'
        )
    else:
        booked_tbl = '<p class="empty">No classes booked yet.</p>'

    booked_sec = f"""
      <div class="sec">
        <p class="sec-title">📅 Your upcoming classes</p>
        {quota}
        {booked_tbl}
      </div>
      <div class="div"></div>"""

    # New day + other sections
    booked_dates_set_pre = {b.dt.date() for b in upcoming_bookings}
    new_day_empty_msg = (
        f"✓ Already booked on {new_day.strftime('%a %b %-d')} — no action needed."
        if new_day in booked_dates_set_pre
        else f"No matching classes on {new_day.strftime('%a %b %-d')} within 9am–7pm."
    )
    new_sec   = _match_section(new_day_matches,
                               f"🆕 New day: {new_day.strftime('%A, %b %-d')} (just opened)",
                               new_day_empty_msg)
    other_sec = _match_section(other_matches, "Other open days") if other_matches else ""

    booked_dates_set = booked_dates_set_pre
    # Show extra studios for next 3 days, only on days without a Solidcore booking
    extra_cutoff = today + timedelta(days=3)
    extra_upcoming = [s for s in extra_slots if today <= s.date <= extra_cutoff]
    extra_sec = _extra_section(extra_upcoming, booked_dates=booked_dates_set) if extra_upcoming else ""

    # All Solidcore classes — next 10 days, no filters
    all_slots_sec = _all_classes_section(slots, today, booked_dates_set, focus_map)

    # Travel section
    travel_sec = _travel_section(travel_city, travel_slots) if travel_city and travel_slots else ""

    quote_html = ""
    if upcoming_bookings:
        quote = _daily_quote(today, focus_map)
        quote_html = f"""<div style="background:#fdf2f8;text-align:center;padding:18px 20px 14px">
    <span style="font-size:26px;margin-right:8px">🍑</span><span style="font-size:22px;font-weight:900;color:#ec4899;letter-spacing:1px;text-transform:uppercase;font-style:italic;text-shadow:2px 2px 0px #fbcfe8">{quote}</span><span style="font-size:26px;margin-left:8px">🍑</span>
  </div>"""
    html = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><style>{CSS}</style></head>
<body><div class="wrap">
  <div class="hdr"><h1>🍑 Solidcore Tracker</h1><p>{datetime.now().strftime('%A, %B %-d, %Y')}</p></div>
  {quote_html}
  {monthly_sec}
  {booked_sec}
  {new_sec}
  {other_sec}
  {travel_sec}
  {extra_sec}
  {all_slots_sec}
  <div class="ftr">🍑 solidcore-tracker · muscle focus, instructor &amp; time (9am–7pm)</div>
</div></body></html>"""

    return subject, html


def _class_type_badge(class_name: str) -> str:
    """Extract class type from API name and return a styled badge, or '' for standard Signature50."""
    raw = class_name.split("|", 1)[-1].strip() if "|" in class_name else class_name
    type_part = raw.split(":")[0].strip() if ":" in raw else raw.strip()
    tl = type_part.lower()
    if "power30" in tl:
        return (f'<span style="background:#fee2e2;color:#991b1b;font-size:9px;font-weight:700;'
                f'padding:1px 5px;border-radius:3px;white-space:nowrap">⚡ Power30</span>')
    if "starter50" in tl or "intro" in tl:
        return (f'<span style="background:#fee2e2;color:#991b1b;font-size:9px;font-weight:700;'
                f'padding:1px 5px;border-radius:3px;white-space:nowrap">🚫 Intro</span>')
    if "focus50" in tl:
        return (f'<span style="background:#ede9fe;color:#5b21b6;font-size:9px;font-weight:700;'
                f'padding:1px 5px;border-radius:3px;white-space:nowrap">🎯 Focus50</span>')
    if "advanced50" in tl:
        return (f'<span style="background:#dbeafe;color:#1e40af;font-size:9px;font-weight:700;'
                f'padding:1px 5px;border-radius:3px;white-space:nowrap">🔥 Advanced</span>')
    if "off-peak" in tl:
        return (f'<span style="background:#f3f4f6;color:#6b7280;font-size:9px;font-weight:700;'
                f'padding:1px 5px;border-radius:3px;white-space:nowrap">Off-Peak</span>')
    return ""  # Standard Signature50 — no badge needed


def _match_section(matches: list[MatchedClass], title: str, empty_msg: str = "") -> str:
    pref   = [m for m in matches if m.preferred_time]
    backup = [m for m in matches if not m.preferred_time]

    if not matches:
        body = f'<p class="empty">{empty_msg}</p>' if empty_msg else ""
    else:
        body = ""
        if pref:
            body += _rows(pref, "pref")
        if backup:
            if pref:
                body += '<tr class="subhdr"><td colspan="6">⚡ Backup times — if preferred don\'t work</td></tr>'
            body += _rows(backup, "backup")
        body = (
            '<table><thead><tr><th>Date</th><th>Time</th><th>Studio</th>'
            '<th>Instructor</th><th>Muscle Focus</th><th></th></tr></thead>'
            f'<tbody>{body}</tbody></table>'
        )

    return f"""
      <div class="sec"><p class="sec-title">{title}</p>{body}</div>
      <div class="div"></div>"""


def _rows(matches: list[MatchedClass], kind: str) -> str:
    html = ""
    for m in matches:
        if kind == "pref":
            badge    = '<span class="badge bp">PREFERRED</span>'
            row_cls  = "r-pref"
        else:
            badge    = '<span class="badge bb">BACKUP</span>'
            row_cls  = "r-backup"
        target    = " + ".join(m.muscles)
        secondary = [mu for mu in m.all_muscles if mu not in m.muscles]
        sec_str   = (f'<br><span class="muscle-sec">+ {" + ".join(secondary)}</span>'
                     if secondary else "")
        s_color   = "#2563eb" if "Chelsea" in m.slot.studio else "#7c3aed"
        sp = m.slot.available_spots
        spots_str = (f'<br><span style="color:#6b7280;font-size:11px">({sp} spot{"s" if sp != 1 else ""})</span>'
                     if sp is not None else "")
        type_badge = _class_type_badge(m.slot.class_name)
        type_str   = f"<br>{type_badge}" if type_badge else ""
        html += (
            f'<tr class="{row_cls}">'
            f"<td style='white-space:nowrap'>{m.slot.date_str}</td>"
            f"<td style='white-space:nowrap'>{m.slot.time_str}<br>{badge}</td>"
            f'<td style="color:{s_color};font-weight:500">{m.slot.studio}</td>'
            f"<td>{m.slot.instructor}{type_str}</td>"
            f'<td><span class="muscle">{target}</span>{sec_str}{spots_str}</td>'
            f"<td>{_book_btn(m)}</td>"
            f"</tr>"
        )
    return html


def _book_btn(m: MatchedClass) -> str:
    owner, _, repo = GITHUB_REPO.partition("/")
    params = urllib.parse.urlencode({
        "class_id":     m.slot.wellhub_class_id,
        "class_id_gql": m.slot.class_id_gql,
        "partner_id":   m.slot.partner_id,
        "studio":       m.slot.studio,
        "instructor":   m.slot.instructor,
        "dt":           f"{m.slot.date_str} {m.slot.time_str}",
        "muscles":      " + ".join(m.all_muscles),
        "repo":         GITHUB_REPO,
    })
    url = f"https://{owner}.github.io/{repo}/book.html?{params}"
    return f'<a class="book-btn" href="{url}">Book →</a>'


# ── Extra studios section ──────────────────────────────────────────────────

def _monthly_reminder_section(all_bookings: list, month_start, today, monthly_studios: list) -> str:
    """Show a reminder pill for each monthly studio if not yet visited this month."""
    from src.config import MONTHLY_LIMITS
    labels = {"othership": "Othership", "stretch*d": "Stretch*d", "nofar": "Nofar"}
    items = []
    for keyword in monthly_studios:
        label = labels.get(keyword, keyword.title())
        monthly_limit = MONTHLY_LIMITS.get(keyword)
        month_visits = [
            b for b in all_bookings
            if b.completed and keyword in b.studio_name.lower()
            and month_start <= b.dt.date() <= today
        ]

        if monthly_limit is not None:
            # Merge API visits into persistent cache so visits never fall off the API window
            from src.state import merge_visits
            api_dates = [b.dt.date() for b in month_visits]
            all_dates = merge_visits(keyword, api_dates)
            count = len(all_dates)
            if count >= monthly_limit:
                bg, fg = "#fee2e2", "#991b1b"
                text = f"🚫 {label} — {count}/{monthly_limit} limit reached"
            elif count >= monthly_limit - 1:
                bg, fg = "#fef3c7", "#92400e"
                text = f"⚠️ {label} — {count}/{monthly_limit} this month"
            elif count > 0:
                bg, fg = "#d1fae5", "#065f46"
                text = f"✓ {label} — {count}/{monthly_limit} this month"
            else:
                bg, fg = "#fef3c7", "#92400e"
                text = f"⏰ {label} — 0/{monthly_limit} this month"
            badge = (f'<span style="background:{bg};color:{fg};font-size:11px;font-weight:700;'
                     f'padding:3px 10px;border-radius:20px">{text}</span>')
        else:
            # Binary done/not-done for studios without a monthly limit
            done = bool(month_visits)
            if done:
                badge = (f'<span style="background:#d1fae5;color:#065f46;font-size:11px;font-weight:700;'
                         f'padding:3px 10px;border-radius:20px">✓ {label} done</span>')
            else:
                badge = (f'<span style="background:#fef3c7;color:#92400e;font-size:11px;font-weight:700;'
                         f'padding:3px 10px;border-radius:20px">⏰ {label} — not yet this month</span>')
        items.append(badge)

    if not items:
        return ""
    pills = " ".join(items)
    return (f'<div class="sec" style="padding:12px 16px">'
            f'<p class="sec-title" style="margin-bottom:8px">🗓 Monthly check-ins</p>'
            f'<div style="display:flex;gap:8px;flex-wrap:wrap">{pills}</div>'
            f'</div><div class="div"></div>')


def _extra_section(slots: list, booked_dates: set | None = None) -> str:
    """Compact table of Nofar / CorePower Sculpt — preferred times first, max 3/day."""
    if not slots:
        return ""

    from src.config import PREFERRED_START_HOUR, PREFERRED_END_HOUR
    booked_dates = booked_dates or set()

    # Filter to unbooked days only, sort preferred first then backup
    filtered = [s for s in slots if s.date not in booked_dates]
    filtered.sort(key=lambda s: (s.studio, s.date, 0 if PREFERRED_START_HOUR <= s.dt.hour < PREFERRED_END_HOUR else 1, s.dt))

    # Max 3 per studio per day
    from collections import defaultdict
    counts: dict[tuple, int] = defaultdict(int)
    shown = []
    for s in filtered:
        key = (s.studio, s.date)
        if counts[key] < 3:
            shown.append(s)
            counts[key] += 1

    if not shown:
        return ""

    from collections import defaultdict as dd
    by_studio: dict[str, list] = dd(list)
    for s in shown:
        by_studio[s.studio].append(s)

    rows = ""
    for studio, studio_slots in by_studio.items():
        rows += (f'<tr><td colspan="4" style="padding:4px 8px 2px;font-size:9px;'
                 f'font-weight:700;letter-spacing:.8px;text-transform:uppercase;'
                 f'color:#9ca3af;background:#f9fafb;border-bottom:1px solid #e5e7eb">'
                 f'{studio}</td></tr>')
        for s in studio_slots:
            class_name = getattr(s, '_class_name', '') or s.studio
            is_pref = PREFERRED_START_HOUR <= s.dt.hour < PREFERRED_END_HOUR
            time_color = "#374151" if is_pref else "#9ca3af"
            instr = (f'&nbsp;<span style="color:#9ca3af;font-size:11px">· {s.instructor}</span>'
                     if s.instructor else '')
            owner, _, repo = GITHUB_REPO.partition("/")
            params = urllib.parse.urlencode({
                "class_id": s.wellhub_class_id, "class_id_gql": s.class_id_gql,
                "partner_id": s.partner_id, "studio": s.studio,
                "instructor": s.instructor,
                "dt": f"{s.date_str} {s.time_str}", "muscles": "", "repo": GITHUB_REPO,
            })
            book_url = f"https://{owner}.github.io/{repo}/book.html?{params}"
            btn = (f'<a href="{book_url}" style="display:inline-block;background:#111;color:#fff;'
                   f'padding:3px 9px;border-radius:5px;text-decoration:none;font-size:10px;'
                   f'font-weight:600;white-space:nowrap">Book →</a>')
            spots = getattr(s, "_available_spots", None)
            spots_str = ""
            if spots is not None:
                sc = "#059669" if spots >= 5 else ("#f59e0b" if spots >= 2 else "#ef4444")
                spots_str = (f'&nbsp;<span style="color:{sc};font-size:10px;font-weight:600">'
                             f'{spots} spot{"s" if spots != 1 else ""}</span>')
            rows += (
                f'<tr>'
                f'<td style="white-space:nowrap;padding:5px 8px;border-bottom:1px solid #f5f5f5;'
                f'font-family:-apple-system,BlinkMacSystemFont,sans-serif;font-size:11px;color:#6b7280">{s.date_str}</td>'
                f'<td style="white-space:nowrap;padding:5px 8px;border-bottom:1px solid #f5f5f5;'
                f'font-family:-apple-system,BlinkMacSystemFont,sans-serif;font-size:11px;color:{time_color}">{s.time_str}</td>'
                f'<td style="padding:5px 8px;border-bottom:1px solid #f5f5f5;'
                f'font-family:-apple-system,BlinkMacSystemFont,sans-serif;font-size:11px;color:#374151">{class_name}{instr}{spots_str}</td>'
                f'<td style="padding:5px 8px;border-bottom:1px solid #f5f5f5">{btn}</td>'
                f'</tr>'
            )

    return (
        f'<div style="padding:12px 28px 14px;font-family:-apple-system,BlinkMacSystemFont,sans-serif">'
        f'<p style="font-size:9px;font-weight:700;letter-spacing:1.2px;text-transform:uppercase;'
        f'color:#aaa;margin:0 0 8px">🔄 Also available — backup studios</p>'
        f'<table style="width:100%;border-collapse:collapse">'
        f'<thead><tr>'
        f'<th style="text-align:left;color:#aaa;font-weight:600;font-size:9px;text-transform:uppercase;letter-spacing:.5px;padding:4px 8px;border-bottom:1px solid #eee;font-family:-apple-system,BlinkMacSystemFont,sans-serif">Date</th>'
        f'<th style="text-align:left;color:#aaa;font-weight:600;font-size:9px;text-transform:uppercase;letter-spacing:.5px;padding:4px 8px;border-bottom:1px solid #eee;font-family:-apple-system,BlinkMacSystemFont,sans-serif">Time</th>'
        f'<th style="text-align:left;color:#aaa;font-weight:600;font-size:9px;text-transform:uppercase;letter-spacing:.5px;padding:4px 8px;border-bottom:1px solid #eee;font-family:-apple-system,BlinkMacSystemFont,sans-serif">Class</th>'
        f'<th style="border-bottom:1px solid #eee"></th>'
        f'</tr></thead>'
        f'<tbody>{rows}</tbody>'
        f'</table>'
        f'</div>'
        f'<div class="div"></div>'
    )


MUSCLE_QUOTES = {
    "Outer Glutes": [
        "🍑 OUTER GLUTES DAY — time to build that shelf, queen!",
        "💅 Side booty szn is TODAY. Show up.",
        "🔥 Those outer glutes aren't gonna grow by themselves, babe.",
        "👑 Outer glute day is basically a royal decree. ATTEND.",
        "✨ Outer glutes: the secret weapon. Deploy them.",
    ],
    "Center Glutes": [
        "🍑 CENTER GLUTES — the main character of your booty. Go!",
        "💥 Dead center, dead serious. Center glutes TODAY.",
        "👸 Your center glutes are calling. Pick UP.",
        "🔥 Center glutes: the foundation of every great booty. Build it.",
        "💪 Center stage belongs to your glutes today. Own it.",
    ],
    "Leg Wrap": [
        "⚡ LEG WRAP DAY — wrap it up and burn it DOWN.",
        "🦵 Legs, baby. Wrap 'em. Burn 'em. Slay.",
        "💅 Those legs aren't gonna wrap themselves. LET'S GO.",
        "👑 Leg wrap queen. That's YOU. Now move.",
        "🔥 Leg wrap day hits different. You already know.",
    ],
    "Hamstrings": [
        "🔥 HAMSTRING DAY — the back of your legs want ATTENTION.",
        "💪 Hamstrings: the unsung hero of a great booty. TODAY is their day.",
        "🦵 Back of the leg, front of the line. Hamstrings GO.",
        "✨ Strong hammies = strong everything. Show up.",
        "👸 Hamstrings deserve love too. Give it to them.",
    ],
    "Inner Thighs": [
        "💎 INNER THIGHS — squeeze squeeze squeeze, queen!",
        "🔥 Inner thigh day. Pretend there's a dollar bill between them.",
        "💅 Inner thighs: the VIP section of leg day. You're on the list.",
        "✨ Squeeze it like it owes you money. Inner thighs TODAY.",
        "👑 Inner thigh strength is quiet power. Build it.",
    ],
}

FALLBACK_QUOTES = [
    "🍑 Work that booty, queen!",
    "💅 Your glutes called. They said show UP.",
    "🔥 Sweat now, slay later.",
    "👑 No one built an empire by skipping leg day.",
    "💪 She believed she could, so she squatted.",
    "💃 Shake what solidcore gave ya.",
    "🔥 Pain is temporary. Glute gains are forever.",
    "👸 Queens don't skip. Queens book.",
    "💫 You didn't wake up to be mediocre, babe.",
    "💎 She's a ten. She also never misses solidcore.",
    "✨ Sore today, snatched tomorrow.",
    "🌟 Hot girl walk? Try hot girl SOLIDCORE.",
    "🎀 Pretty girls lift heavy. It's science.",
    "💥 Your future booty is thanking you right now.",
]


def _daily_quote(today, focus_map: dict | None = None) -> str:
    import hashlib
    # Use TODAY's muscle focus — email arrives in the morning, quote matches today's vibe
    muscles = (focus_map or {}).get(today, [])
    # Find first muscle that has a dedicated quote bank
    quotes = None
    for muscle in muscles:
        if muscle in MUSCLE_QUOTES:
            quotes = MUSCLE_QUOTES[muscle]
            break
    if not quotes:
        quotes = FALLBACK_QUOTES
    idx = int(hashlib.md5(str(today).encode()).hexdigest(), 16) % len(quotes)
    return quotes[idx]


def _all_classes_section(slots: list, today, booked_dates: set, focus_map: dict) -> str:
    """All available Solidcore classes for the next 10 days — no instructor/muscle filter."""
    from src.config import BACKUP_START_HOUR, BACKUP_END_HOUR, TARGET_MUSCLES
    from datetime import timedelta
    from collections import defaultdict

    cutoff = today + timedelta(days=10)
    window = [s for s in slots
              if today <= s.date <= cutoff
              and BACKUP_START_HOUR <= s.dt.hour < BACKUP_END_HOUR]
    window.sort(key=lambda s: (s.date, s.dt))

    if not window:
        return ""

    by_day: dict = defaultdict(list)
    for s in window:
        by_day[s.date].append(s)

    owner, _, repo = GITHUB_REPO.partition("/")
    rows = ""
    for d in sorted(by_day):
        day_muscles = focus_map.get(d, [])
        target_hit  = any(m in TARGET_MUSCLES for m in day_muscles)
        muscle_str  = " · ".join(day_muscles) if day_muscles else "—"
        muscle_color = "#059669" if target_hit else "#9ca3af"
        is_booked   = d in booked_dates
        day_label   = d.strftime("%a %b %-d")
        booked_tag  = (' <span style="font-size:9px;background:#dbeafe;color:#1e40af;'
                       'padding:1px 5px;border-radius:3px;font-weight:700">BOOKED</span>'
                       if is_booked else "")
        rows += (f'<tr><td colspan="5" style="padding:6px 8px 3px;font-size:11px;font-weight:700;'
                 f'letter-spacing:.5px;background:#f9fafb;border-top:2px solid #e5e7eb;'
                 f'border-bottom:1px solid #e5e7eb;color:#374151">'
                 f'{day_label}{booked_tag}'
                 f'<span style="font-weight:400;color:{muscle_color};margin-left:10px;font-size:10px">'
                 f'{muscle_str}</span></td></tr>')
        for s in by_day[d]:
            s_color    = "#2563eb" if "Chelsea" in s.studio else "#7c3aed"
            sp         = s.available_spots
            spots_str  = (f'<span style="color:#6b7280;font-size:11px">({sp} spot{"s" if sp != 1 else ""})</span>'
                          if sp is not None else "")
            type_badge = _class_type_badge(s.class_name)
            type_str   = f"&nbsp;{type_badge}" if type_badge else ""
            params = urllib.parse.urlencode({
                "class_id": s.wellhub_class_id, "class_id_gql": s.class_id_gql,
                "partner_id": s.partner_id, "studio": s.studio,
                "instructor": s.instructor,
                "dt": f"{s.date_str} {s.time_str}",
                "muscles": " · ".join(day_muscles),
                "repo": GITHUB_REPO,
            })
            book_url = f"https://{owner}.github.io/{repo}/book.html?{params}"
            btn = f'<a class="book-btn" href="{book_url}">Book →</a>'
            rows += (
                f'<tr style="background:#fff">'
                f'<td style="white-space:nowrap;padding:6px 8px;border-bottom:1px solid #f5f5f5;color:#374151">{s.time_str}</td>'
                f'<td style="padding:6px 8px;border-bottom:1px solid #f5f5f5;color:{s_color};font-weight:500;white-space:nowrap">{s.studio}</td>'
                f'<td style="padding:6px 8px;border-bottom:1px solid #f5f5f5;color:#111">{s.instructor}{type_str}</td>'
                f'<td style="padding:6px 8px;border-bottom:1px solid #f5f5f5">{spots_str}</td>'
                f'<td style="padding:6px 8px;border-bottom:1px solid #f5f5f5">{btn}</td>'
                f'</tr>'
            )

    return f"""
      <div class="sec">
        <p class="sec-title">📋 All Solidcore classes — next 10 days</p>
        <table>
          <thead><tr>
            <th>Time</th><th>Studio</th><th>Instructor</th><th>Spots</th><th></th>
          </tr></thead>
          <tbody>{rows}</tbody>
        </table>
      </div>
      <div class="div"></div>"""


def _travel_section(city_name: str, slots: list) -> str:
    """Compact table of Solidcore classes in the travel city — next 3 days."""
    if not slots:
        return ""

    from collections import defaultdict
    by_day: dict = defaultdict(list)
    for s in slots:
        by_day[s.date].append(s)

    owner, _, repo = GITHUB_REPO.partition("/")
    rows = ""
    for d in sorted(by_day):
        day_label = d.strftime("%a %b %-d")
        rows += (
            f'<tr><td colspan="4" style="padding:6px 8px 3px;font-size:11px;font-weight:700;'
            f'letter-spacing:.5px;background:#f0f9ff;border-top:2px solid #bae6fd;'
            f'border-bottom:1px solid #bae6fd;color:#0369a1">'
            f'{day_label}</td></tr>'
        )
        for s in by_day[d]:
            sp = s.available_spots
            sc = "#059669" if sp >= 5 else ("#f59e0b" if sp >= 2 else "#ef4444")
            spots_str = (f'<span style="color:{sc};font-size:10px;font-weight:600">'
                         f'{sp} spot{"s" if sp != 1 else ""}</span>' if sp is not None else "")
            instr = (f'<span style="color:#9ca3af;font-size:11px"> · {s.instructor}</span>'
                     if s.instructor else "")
            params = urllib.parse.urlencode({
                "class_id": s.wellhub_class_id, "class_id_gql": s.class_id_gql,
                "partner_id": s.partner_id, "studio": s.studio,
                "instructor": s.instructor,
                "dt": f"{s.date_str} {s.time_str}", "muscles": "", "repo": GITHUB_REPO,
            })
            book_url = f"https://{owner}.github.io/{repo}/book.html?{params}"
            btn = (f'<a href="{book_url}" style="display:inline-block;background:#0369a1;color:#fff;'
                   f'padding:3px 9px;border-radius:5px;text-decoration:none;font-size:10px;'
                   f'font-weight:600;white-space:nowrap">Book →</a>')
            rows += (
                f'<tr>'
                f'<td style="white-space:nowrap;padding:5px 8px;border-bottom:1px solid #f5f5f5;'
                f'font-family:-apple-system,BlinkMacSystemFont,sans-serif;font-size:11px;color:#374151">{s.time_str}</td>'
                f'<td style="padding:5px 8px;border-bottom:1px solid #f5f5f5;'
                f'font-family:-apple-system,BlinkMacSystemFont,sans-serif;font-size:11px;color:#0369a1;font-weight:500">{s.studio}{instr}</td>'
                f'<td style="padding:5px 8px;border-bottom:1px solid #f5f5f5">{spots_str}</td>'
                f'<td style="padding:5px 8px;border-bottom:1px solid #f5f5f5">{btn}</td>'
                f'</tr>'
            )

    return (
        f'<div style="padding:12px 28px 14px;font-family:-apple-system,BlinkMacSystemFont,sans-serif;background:#f0f9ff">'
        f'<p style="font-size:9px;font-weight:700;letter-spacing:1.2px;text-transform:uppercase;'
        f'color:#0369a1;margin:0 0 8px">✈️ Solidcore in {city_name}</p>'
        f'<table style="width:100%;border-collapse:collapse">'
        f'<thead><tr>'
        f'<th style="text-align:left;color:#7dd3fc;font-weight:600;font-size:9px;text-transform:uppercase;letter-spacing:.5px;padding:4px 8px;border-bottom:1px solid #bae6fd;font-family:-apple-system,BlinkMacSystemFont,sans-serif">Time (local)</th>'
        f'<th style="text-align:left;color:#7dd3fc;font-weight:600;font-size:9px;text-transform:uppercase;letter-spacing:.5px;padding:4px 8px;border-bottom:1px solid #bae6fd;font-family:-apple-system,BlinkMacSystemFont,sans-serif">Studio &amp; Instructor</th>'
        f'<th style="text-align:left;color:#7dd3fc;font-weight:600;font-size:9px;text-transform:uppercase;letter-spacing:.5px;padding:4px 8px;border-bottom:1px solid #bae6fd;font-family:-apple-system,BlinkMacSystemFont,sans-serif">Spots</th>'
        f'<th style="border-bottom:1px solid #bae6fd"></th>'
        f'</tr></thead>'
        f'<tbody>{rows}</tbody>'
        f'</table>'
        f'</div>'
        f'<div class="div"></div>'
    )


def _send(to_email: str, subject: str, html_body: str) -> None:
    if not SMTP_USER or not SMTP_PASSWORD:
        log.warning("SMTP credentials not set — printing to stdout")
        print(f"\nSUBJECT: {subject}\n{html_body}\n")
        return
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"]    = SMTP_USER
    msg["To"]      = to_email
    msg.attach(MIMEText(html_body, "html"))
    with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as smtp:
        smtp.ehlo(); smtp.starttls()
        smtp.login(SMTP_USER, SMTP_PASSWORD)
        smtp.sendmail(SMTP_USER, to_email, msg.as_string())
    log.info("Email sent to %s", to_email)
