"""
Send an iMessage digest via macOS Messages app using AppleScript.
Only works on macOS — silently skipped on Linux (GitHub Actions).
"""

from __future__ import annotations

import logging
import platform
import subprocess

from src.filters import MatchedClass

log = logging.getLogger(__name__)

PHONE_NUMBER = "+15167105653"


def send_imessage(matches: list[MatchedClass]) -> None:
    if platform.system() != "Darwin":
        log.info("Not on macOS — skipping iMessage")
        return
    if not matches:
        return

    message = _build_message(matches)
    _send(PHONE_NUMBER, message)


def _build_message(matches: list[MatchedClass]) -> str:
    preferred = [m for m in matches if m.preferred_time]
    other     = [m for m in matches if not m.preferred_time]

    lines = [f"🏋️ Solidcore — {len(matches)} matching class{'es' if len(matches) != 1 else ''}"]

    if preferred:
        lines.append("\n⭐ Preferred (11am–2pm):")
        for m in preferred:
            muscles = " + ".join(m.all_muscles)
            lines.append(f"  {m.slot.date_str} {m.slot.time_str} · {m.slot.studio[:7]} · {m.slot.instructor} · {muscles}")

    if other:
        lines.append("\nOther times:")
        for m in other:
            muscles = " + ".join(m.all_muscles)
            lines.append(f"  {m.slot.date_str} {m.slot.time_str} · {m.slot.studio[:7]} · {m.slot.instructor} · {muscles}")

    lines.append("\nCheck email to book →")
    return "\n".join(lines)


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
