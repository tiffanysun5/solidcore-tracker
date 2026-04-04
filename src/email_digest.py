"""
Build and send the daily email digest.

Email shows:
  • Matched classes grouped into preferred (11am–2pm) and other
  • Per-class Book button → Cloudflare Worker confirmation page
  • Full muscle focus pair for each day (e.g. "Leg Wrap + Triceps")

Sending uses Gmail SMTP with an App Password (SMTP_PASSWORD env var).
"""

from __future__ import annotations

import logging
import os
import smtplib
import urllib.parse
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from src.filters import MatchedClass

log = logging.getLogger(__name__)

SMTP_HOST       = os.getenv("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT       = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER       = os.getenv("SMTP_USER", "")
SMTP_PASSWORD   = os.getenv("SMTP_PASSWORD", "")
GITHUB_REPO     = os.getenv("GITHUB_REPO", "tiffanysun/solidcore-tracker")


def send_digest(matches: list[MatchedClass], to_email: str) -> None:
    if not matches:
        log.info("No matches — skipping email")
        return
    subject, html_body = _build_email(matches)
    _send(to_email, subject, html_body)


def _build_email(matches: list[MatchedClass]) -> tuple[str, str]:
    preferred = [m for m in matches if m.preferred_time]
    other     = [m for m in matches if not m.preferred_time]

    subject = (
        f"[Solidcore] {len(matches)} matching class{'es' if len(matches) != 1 else ''} "
        f"({len(preferred)} preferred)"
    )

    rows_preferred = _render_rows(preferred, highlight=True)
    rows_other     = _render_rows(other, highlight=False)

    def section(title: str, rows: str) -> str:
        if not rows:
            return ""
        return f"""
        <div class="section">
          <p class="section-title">{title}</p>
          <table>
            <thead><tr>
              <th>Date</th><th>Time</th><th>Studio</th>
              <th>Instructor</th><th>Muscle Focus</th><th></th>
            </tr></thead>
            <tbody>{rows}</tbody>
          </table>
        </div>
        <div class="divider"></div>"""

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
  .header p {{ margin: 6px 0 0; font-size: 13px; opacity: .7; }}
  .section {{ padding: 20px 28px; }}
  .section-title {{ font-size: 11px; font-weight: 700; letter-spacing: 1px;
                    text-transform: uppercase; color: #888; margin: 0 0 12px; }}
  table {{ width: 100%; border-collapse: collapse; font-size: 13px; }}
  th {{ text-align: left; color: #666; font-weight: 600; font-size: 11px;
        text-transform: uppercase; letter-spacing: .5px; padding: 6px 8px;
        border-bottom: 2px solid #f0f0f0; white-space: nowrap; }}
  td {{ padding: 10px 8px; border-bottom: 1px solid #f5f5f5; vertical-align: middle; }}
  .pref {{ background: #fffbeb; }}
  .pref td:first-child {{ border-left: 3px solid #f59e0b; }}
  .badge {{ display: inline-block; font-size: 10px; font-weight: 700;
            padding: 2px 6px; border-radius: 4px; letter-spacing: .5px; }}
  .badge-pref {{ background: #fef3c7; color: #92400e; }}
  .badge-other {{ background: #f3f4f6; color: #6b7280; }}
  .muscle-target {{ color: #059669; font-weight: 600; }}
  .muscle-secondary {{ color: #6b7280; font-size: 12px; }}
  .studio-chelsea {{ color: #2563eb; font-weight: 500; }}
  .studio-gv {{ color: #7c3aed; font-weight: 500; }}
  .book-btn {{ display: inline-block; background: #111; color: #fff !important;
               padding: 6px 14px; border-radius: 6px; text-decoration: none;
               font-size: 12px; font-weight: 600; white-space: nowrap; }}
  .book-btn:hover {{ background: #333; }}
  .no-worker {{ font-size: 11px; color: #aaa; font-family: monospace; }}
  .divider {{ height: 1px; background: #f0f0f0; margin: 0 28px; }}
  .footer {{ padding: 16px 28px; font-size: 11px; color: #aaa; }}
</style>
</head>
<body>
<div class="container">
  <div class="header">
    <h1>Solidcore Class Tracker</h1>
    <p>{datetime.now().strftime('%A, %B %-d, %Y')} · {len(matches)} match{'es' if len(matches) != 1 else ''} found</p>
  </div>

  {section('⭐ Preferred time window (11am – 2pm)', rows_preferred)}
  {section('Other times', rows_other)}

  <div class="footer">
    solidcore-tracker · filtered by muscle focus, instructor &amp; time preference
  </div>
</div>
</body>
</html>"""

    return subject, html


def _render_rows(matches: list[MatchedClass], highlight: bool) -> str:
    html = ""
    for m in matches:
        studio_class = "studio-chelsea" if "Chelsea" in m.slot.studio else "studio-gv"
        badge = (
            '<span class="badge badge-pref">PREFERRED</span>'
            if highlight else
            '<span class="badge badge-other">other</span>'
        )

        # Show matched target muscle(s) + secondary muscle
        target_muscles = " + ".join(m.muscles)
        secondary = [mu for mu in m.all_muscles if mu not in m.muscles]
        secondary_str = (
            f'<br><span class="muscle-secondary">+ {" + ".join(secondary)}</span>'
            if secondary else ""
        )

        book_cell = _book_button(m)

        html += (
            f'<tr class="{"pref" if highlight else ""}">'
            f"<td>{m.slot.date_str}</td>"
            f"<td style='white-space:nowrap'>{m.slot.time_str}<br>{badge}</td>"
            f'<td class="{studio_class}">{m.slot.studio}</td>'
            f"<td>{m.slot.instructor}</td>"
            f'<td><span class="muscle-target">{target_muscles}</span>{secondary_str}</td>'
            f"<td>{book_cell}</td>"
            f"</tr>"
        )
    return html


def _book_button(m: MatchedClass) -> str:
    """Return a per-class Book button linking to the GitHub Pages confirmation page."""
    # Derive GitHub Pages URL from repo name: "owner/repo" → "owner.github.io/repo"
    owner, _, repo_name = GITHUB_REPO.partition("/")
    pages_base = f"https://{owner}.github.io/{repo_name}"

    muscles_display = " + ".join(m.all_muscles)
    params = urllib.parse.urlencode({
        "class_id":   m.slot.wellhub_class_id,
        "studio":     m.slot.studio,
        "instructor": m.slot.instructor,
        "dt":         f"{m.slot.date_str} {m.slot.time_str}",
        "muscles":    muscles_display,
        "repo":       GITHUB_REPO,
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

    log.info("Sending digest to %s via %s:%d", to_email, SMTP_HOST, SMTP_PORT)
    with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as smtp:
        smtp.ehlo()
        smtp.starttls()
        smtp.login(SMTP_USER, SMTP_PASSWORD)
        smtp.sendmail(SMTP_USER, to_email, msg.as_string())
    log.info("Email sent successfully")
