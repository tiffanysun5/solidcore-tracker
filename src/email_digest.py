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
) -> None:
    subject, html_body = _build_email(matches, all_bookings, upcoming_bookings, new_day,
                                      extra_slots or [])
    _send(to_email, subject, html_body)


def _build_email(
    matches:           list[MatchedClass],
    all_bookings:      list,
    upcoming_bookings: list,
    new_day:           date,
    extra_slots:       list | None = None,
) -> tuple[str, str]:
    extra_slots = extra_slots or []

    from zoneinfo import ZoneInfo
    ny    = ZoneInfo("America/New_York")
    today = datetime.now(tz=ny).date()

    new_day_matches = [m for m in matches if m.slot.date == new_day]
    other_matches   = [m for m in matches if m.slot.date != new_day]

    # Subject
    nc = len(new_day_matches)
    subject = (
        f"[Solidcore] {new_day.strftime('%a %b %-d')} — "
        f"{nc} new class{'es' if nc != 1 else ''} available"
        + (f"  ·  {len(other_matches)} other open day{'s' if len(other_matches) != 1 else ''}"
           if other_matches else "")
    )

    # Weekly quota — solidcore only (premium class limit is 4/week)
    solidcore_bookings = [b for b in all_bookings if "[solidcore]" in b.studio_name.lower()]
    this_mon = today - timedelta(days=today.weekday())
    this_sun = this_mon + timedelta(days=6)
    next_mon = this_sun + timedelta(days=1)
    next_sun = next_mon + timedelta(days=6)
    LIMIT = 4

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
                cp = urllib.parse.urlencode({
                    "attendance_id": b.attendance_id,
                    "studio":        studio,
                    "dt":            f"{b.dt.strftime('%a %b %-d')} {b.dt.strftime('%-I:%M %p')}",
                    "repo":          GITHUB_REPO,
                })
                cancel_url = f"https://{owner}.github.io/{repo_name}/cancel.html?{cp}"
                cancel_btn = f' <a href="{cancel_url}" style="font-size:11px;color:#dc2626;text-decoration:none;border:1px solid #dc2626;border-radius:4px;padding:2px 6px;white-space:nowrap">Cancel</a>'
            rows += (
                f'<tr><td style="white-space:nowrap;color:#374151;font-weight:500">{b.dt.strftime("%a %b %-d")}</td>'
                f'<td style="white-space:nowrap;color:#6b7280">{b.dt.strftime("%-I:%M %p")}</td>'
                f'<td style="color:#2563eb;font-weight:500">{studio}</td>'
                f'<td style="color:#111">{title}{cancel_btn}</td></tr>'
            )
        booked_tbl = (
            '<table><thead><tr><th>Date</th><th>Time</th><th>Studio</th><th>Class</th></tr></thead>'
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
    new_sec   = _match_section(new_day_matches,
                               f"🆕 New day: {new_day.strftime('%A, %b %-d')} (just opened)",
                               f"No matching classes on {new_day.strftime('%a %b %-d')} within 9am–7pm.")
    other_sec = _match_section(other_matches, "Other open days") if other_matches else ""

    booked_dates_set = {b.dt.date() for b in upcoming_bookings}
    # Show extra studios for TODAY only (as a same-day backup option)
    extra_today = [s for s in extra_slots if s.date == today]
    extra_sec = _extra_section(extra_today, booked_dates=booked_dates_set) if extra_today else ""

    html = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><style>{CSS}</style></head>
<body><div class="wrap">
  <div class="hdr"><h1>Solidcore Tracker</h1><p>{datetime.now().strftime('%A, %B %-d, %Y')}</p></div>
  {monthly_sec}
  {booked_sec}
  {new_sec}
  {other_sec}
  {extra_sec}
  <div class="ftr">solidcore-tracker · muscle focus, instructor &amp; time (9am–7pm)</div>
</div></body></html>"""

    return subject, html


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
        html += (
            f'<tr class="{row_cls}">'
            f"<td style='white-space:nowrap'>{m.slot.date_str}</td>"
            f"<td style='white-space:nowrap'>{m.slot.time_str}<br>{badge}</td>"
            f'<td style="color:{s_color};font-weight:500">{m.slot.studio}</td>'
            f"<td>{m.slot.instructor}</td>"
            f'<td><span class="muscle">{target}</span>{sec_str}</td>'
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
    labels = {"othership": "Othership", "stretch": "Stretch*d"}
    items = []
    for keyword in monthly_studios:
        done = any(
            keyword in b.studio_name.lower() and month_start <= b.dt.date() <= today
            for b in all_bookings if b.completed
        )
        label = labels.get(keyword, keyword.title())
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
        rows += (f'<tr><td colspan="4" style="padding:5px 8px 3px;font-size:10px;'
                 f'font-weight:700;letter-spacing:.8px;text-transform:uppercase;'
                 f'color:#6b7280;background:#f9fafb;border-bottom:1px solid #e5e7eb">'
                 f'{studio}</td></tr>')
        for s in studio_slots:
            class_name = getattr(s, '_class_name', '') or s.studio
            is_pref = PREFERRED_START_HOUR <= s.dt.hour < PREFERRED_END_HOUR
            time_color = "#111" if is_pref else "#6b7280"
            instr = (f'  <span style="color:#9ca3af;font-size:11px">· {s.instructor}</span>'
                     if s.instructor else '')
            owner, _, repo = GITHUB_REPO.partition("/")
            params = urllib.parse.urlencode({
                "class_id": s.wellhub_class_id, "class_id_gql": s.class_id_gql,
                "partner_id": s.partner_id, "studio": s.studio,
                "instructor": s.instructor,
                "dt": f"{s.date_str} {s.time_str}", "muscles": "", "repo": GITHUB_REPO,
            })
            book_url = f"https://{owner}.github.io/{repo}/book.html?{params}"
            btn = f'<a class="book-btn" href="{book_url}">Book →</a>'
            rows += (
                f'<tr>'
                f"<td style='white-space:nowrap;padding:7px 8px;border-bottom:1px solid #f5f5f5'>{s.date_str}</td>"
                f"<td style='white-space:nowrap;padding:7px 8px;border-bottom:1px solid #f5f5f5;color:{time_color}'>{s.time_str}</td>"
                f"<td style='padding:7px 8px;border-bottom:1px solid #f5f5f5;color:#111'>{class_name}{instr}</td>"
                f"<td style='padding:7px 8px;border-bottom:1px solid #f5f5f5'>{btn}</td>"
                f'</tr>'
            )

    return f"""
      <div class="sec">
        <p class="sec-title">🔄 Also available — backup studios</p>
        <table>
          <thead><tr><th>Date</th><th>Time</th><th>Class</th><th></th></tr></thead>
          <tbody>{rows}</tbody>
        </table>
      </div>
      <div class="div"></div>"""


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
