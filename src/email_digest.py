"""
Build and send the daily email digest.

Layout:
  1. YOUR WEEK  — classes already booked in Wellhub
  2. NEW DAY    — the day that just opened (today + 14), with Book buttons
  3. OTHER OPEN DAYS — any other unbooked days with matching classes + Book buttons
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


def send_digest(
    matches:  list[MatchedClass],
    bookings: list,                 # list[WellhubBooking]
    new_day:  date,
    to_email: str,
) -> None:
    subject, html_body = _build_email(matches, bookings, new_day)
    _send(to_email, subject, html_body)


def _build_email(
    matches:  list[MatchedClass],
    bookings: list,
    new_day:  date,
) -> tuple[str, str]:

    new_day_matches = [m for m in matches if m.slot.date == new_day]
    other_matches   = [m for m in matches if m.slot.date != new_day]

    # Subject line
    new_count = len(new_day_matches)
    subject = (
        f"[Solidcore] {new_day.strftime('%a %b %-d')} — "
        f"{new_count} new class{'es' if new_count != 1 else ''} available"
        + (f"  ·  {len(other_matches)} other open day{'s' if len(other_matches) != 1 else ''}"
           if other_matches else "")
    )

    # ── Already-booked section + weekly quota ────────────────────────────
    from zoneinfo import ZoneInfo
    ny = ZoneInfo("America/New_York")
    today = datetime.now(tz=ny).date()

    # Week boundaries (Mon–Sun)
    this_mon = today - timedelta(days=today.weekday())
    this_sun = this_mon + timedelta(days=6)
    next_mon = this_sun + timedelta(days=1)
    next_sun = next_mon + timedelta(days=6)

    WEEKLY_LIMIT = 4

    def week_count(bookings, mon, sun):
        return sum(1 for b in bookings if mon <= b.dt.date() <= sun)

    this_week_used = week_count(bookings, this_mon, this_sun)
    next_week_used = week_count(bookings, next_mon, next_sun)
    this_week_left = WEEKLY_LIMIT - this_week_used
    next_week_left = WEEKLY_LIMIT - next_week_used

    def quota_pill(used, left):
        color = "#059669" if left > 1 else ("#f59e0b" if left == 1 else "#ef4444")
        return (f'<span style="display:inline-block;background:{color};color:#fff;'
                f'font-size:11px;font-weight:700;padding:3px 10px;border-radius:20px;'
                f'letter-spacing:.3px">{left} of {WEEKLY_LIMIT} left</span>')

    quota_html = (
        f'<div style="margin-bottom:14px;display:flex;gap:16px;flex-wrap:wrap">'
        f'<span style="font-size:13px;color:#555">This week ({this_mon.strftime("%-d %b")}–{this_sun.strftime("%-d %b")}): '
        f'{quota_pill(this_week_used, this_week_left)}</span>'
        f'<span style="font-size:13px;color:#555">Next week ({next_mon.strftime("%-d %b")}–{next_sun.strftime("%-d %b")}): '
        f'{quota_pill(next_week_used, next_week_left)}</span>'
        f'</div>'
    )

    booked_rows = ""
    for b in sorted(bookings, key=lambda x: x.dt):
        title = b.class_name.split(" | ", 1)[-1] if " | " in b.class_name else b.class_name
        studio_short = b.studio_name.replace("[solidcore] ", "").replace(", NY", "")
        booked_rows += (
            f'<tr>'
            f'<td style="white-space:nowrap;color:#374151;font-weight:500">'
            f'{b.dt.strftime("%a %b %-d")}</td>'
            f'<td style="white-space:nowrap;color:#6b7280">{b.dt.strftime("%-I:%M %p")}</td>'
            f'<td style="color:#2563eb;font-weight:500">{studio_short}</td>'
            f'<td style="color:#111">{title}</td>'
            f'</tr>'
        )

    booked_section = f"""
        <div class="section">
          <p class="section-title">📅 Your upcoming classes</p>
          {quota_html}
          {'<table><thead><tr><th>Date</th><th>Time</th><th>Studio</th><th>Class</th></tr></thead><tbody>' + booked_rows + '</tbody></table>' if booked_rows else '<p class="empty">No classes booked yet.</p>'}
        </div>
        <div class="divider"></div>"""

    # ── New-day section ────────────────────────────────────────────────────
    new_day_section = _render_match_section(
        new_day_matches,
        title=f"🆕 New day: {new_day.strftime('%A, %b %-d')} (just opened)",
        empty_msg=f"No matching classes on {new_day.strftime('%a %b %-d')} — muscle focus or instructors don't match.",
    )

    # ── Other open days section ────────────────────────────────────────────
    other_section = ""
    if other_matches:
        other_section = _render_match_section(
            other_matches,
            title="Other open days",
        )

    html = f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<style>
  body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
         background: #f5f5f5; margin: 0; padding: 20px; color: #222; }}
  .container {{ max-width: 680px; margin: 0 auto; background: #fff;
               border-radius: 12px; overflow: hidden; box-shadow: 0 2px 8px rgba(0,0,0,.1); }}
  .header {{ background: #111; color: #fff; padding: 24px 28px; }}
  .header h1 {{ margin: 0; font-size: 22px; letter-spacing: -0.3px; }}
  .header p  {{ margin: 6px 0 0; font-size: 13px; opacity: .7; }}
  .section {{ padding: 20px 28px; }}
  .section-title {{ font-size: 11px; font-weight: 700; letter-spacing: 1px;
                    text-transform: uppercase; color: #888; margin: 0 0 12px; }}
  table {{ width: 100%; border-collapse: collapse; font-size: 13px; }}
  th {{ text-align: left; color: #666; font-weight: 600; font-size: 11px;
        text-transform: uppercase; letter-spacing: .5px; padding: 6px 8px;
        border-bottom: 2px solid #f0f0f0; white-space: nowrap; }}
  td {{ padding: 10px 8px; border-bottom: 1px solid #f5f5f5; vertical-align: middle; }}
  .pref td:first-child {{ border-left: 3px solid #f59e0b; }}
  .pref {{ background: #fffbeb; }}
  .badge {{ display: inline-block; font-size: 10px; font-weight: 700;
            padding: 2px 6px; border-radius: 4px; letter-spacing: .5px; }}
  .badge-pref  {{ background: #fef3c7; color: #92400e; }}
  .badge-other {{ background: #f3f4f6; color: #6b7280; }}
  .muscle-target    {{ color: #059669; font-weight: 600; }}
  .muscle-secondary {{ color: #6b7280; font-size: 12px; }}
  .empty {{ color: #aaa; font-size: 13px; font-style: italic; padding: 8px 0; }}
  .book-btn {{ display: inline-block; background: #111; color: #fff !important;
               padding: 6px 14px; border-radius: 6px; text-decoration: none;
               font-size: 12px; font-weight: 600; white-space: nowrap; }}
  .book-btn:hover {{ background: #333; }}
  .divider {{ height: 1px; background: #f0f0f0; margin: 0 28px; }}
  .footer  {{ padding: 16px 28px; font-size: 11px; color: #aaa; }}
</style>
</head>
<body>
<div class="container">
  <div class="header">
    <h1>Solidcore Tracker</h1>
    <p>{datetime.now().strftime('%A, %B %-d, %Y')}</p>
  </div>

  {booked_section}
  {new_day_section}
  <div class="divider"></div>
  {other_section}

  <div class="footer">
    solidcore-tracker · filtered by muscle focus, instructor &amp; time
  </div>
</div>
</body>
</html>"""

    return subject, html


def _render_match_section(
    matches: list[MatchedClass],
    title: str,
    empty_msg: str = "",
) -> str:
    preferred = [m for m in matches if m.preferred_time]
    other     = [m for m in matches if not m.preferred_time]

    body = ""
    if not matches:
        body = f'<p class="empty">{empty_msg}</p>' if empty_msg else ""
    else:
        if preferred:
            body += _render_rows(preferred, highlight=True)
        if other:
            body += _render_rows(other, highlight=False)

    return f"""
        <div class="section">
          <p class="section-title">{title}</p>
          {'<table><thead><tr><th>Date</th><th>Time</th><th>Studio</th><th>Instructor</th><th>Muscle Focus</th><th></th></tr></thead><tbody>' + body + '</tbody></table>' if matches else body}
        </div>
        <div class="divider"></div>"""


def _render_rows(matches: list[MatchedClass], highlight: bool) -> str:
    html = ""
    for m in matches:
        badge = ('<span class="badge badge-pref">PREFERRED</span>'
                 if highlight else
                 '<span class="badge badge-other">other</span>')
        target = " + ".join(m.muscles)
        secondary = [mu for mu in m.all_muscles if mu not in m.muscles]
        secondary_str = (f'<br><span class="muscle-secondary">+ {" + ".join(secondary)}</span>'
                         if secondary else "")
        studio_color = "color:#2563eb;font-weight:500" if "Chelsea" in m.slot.studio else "color:#7c3aed;font-weight:500"

        html += (
            f'<tr class="{"pref" if highlight else ""}">'
            f"<td style='white-space:nowrap'>{m.slot.date_str}</td>"
            f"<td style='white-space:nowrap'>{m.slot.time_str}<br>{badge}</td>"
            f'<td style="{studio_color}">{m.slot.studio}</td>'
            f"<td>{m.slot.instructor}</td>"
            f'<td><span class="muscle-target">{target}</span>{secondary_str}</td>'
            f"<td>{_book_button(m)}</td>"
            f"</tr>"
        )
    return html


def _book_button(m: MatchedClass) -> str:
    owner, _, repo_name = GITHUB_REPO.partition("/")
    pages_base = f"https://{owner}.github.io/{repo_name}"
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
    url = f"{pages_base}/book.html?{params}"
    return f'<a class="book-btn" href="{url}">Book →</a>'


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
        smtp.ehlo()
        smtp.starttls()
        smtp.login(SMTP_USER, SMTP_PASSWORD)
        smtp.sendmail(SMTP_USER, to_email, msg.as_string())
    log.info("Email sent to %s", to_email)
