"""
Send an iMessage digest via macOS Messages app using AppleScript.
Only works on macOS — silently skipped on Linux (GitHub Actions).
"""

from __future__ import annotations

import logging
import os
import platform
import subprocess
import urllib.parse

from src.filters import MatchedClass

log = logging.getLogger(__name__)

PHONE_NUMBER = "+15167105653"
GITHUB_REPO  = os.getenv("APP_REPO", "tiffanysun5/solidcore-tracker")


def send_imessage(matches: list[MatchedClass]) -> None:
    if platform.system() != "Darwin":
        log.info("Not on macOS — skipping iMessage")
        return
    if not matches:
        return

    preferred = [m for m in matches if m.preferred_time]
    other     = [m for m in matches if not m.preferred_time]

    lines = [f"🏋️ Solidcore — {len(matches)} class{'es' if len(matches) != 1 else ''}"]

    if preferred:
        lines.append("\n⭐ Preferred (11am–2pm)")
        for m in preferred:
            lines.append(_class_block(m))

    if other:
        lines.append("\nOther times")
        for m in other:
            lines.append(_class_block(m))

    _send(PHONE_NUMBER, "\n".join(lines))


def _class_block(m: MatchedClass) -> str:
    muscles = " + ".join(m.all_muscles)
    return (
        f"{m.slot.date_str} · {m.slot.time_str} · {m.slot.studio}\n"
        f"{m.slot.instructor} · {muscles}\n"
        f"{_book_url(m)}"
    )


def _book_url(m: MatchedClass) -> str:
    owner, _, repo_name = GITHUB_REPO.partition("/")
    base   = f"https://{owner}.github.io/{repo_name}/book.html"
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
    return f"{base}?{params}"


def _send(phone: str, message: str) -> None:
    # Escape for AppleScript: backslash and double-quote
    safe = message.replace("\\", "\\\\").replace('"', '\\"')
    script = f'''
        tell application "Messages"
            set targetService to first service whose service type is iMessage
            set targetBuddy to buddy "{phone}" of targetService
            send "{safe}" to targetBuddy
        end tell
    '''
    try:
        result = subprocess.run(
            ["osascript", "-e", script],
            capture_output=True, text=True, timeout=15
        )
        if result.returncode == 0:
            log.info("iMessage sent to %s", phone)
        else:
            log.warning("iMessage failed: %s", result.stderr.strip())
    except subprocess.TimeoutExpired:
        log.warning("iMessage timed out")
    except FileNotFoundError:
        log.warning("osascript not found — skipping iMessage")
