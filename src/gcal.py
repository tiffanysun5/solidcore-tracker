"""
Google Calendar sync for Wellhub Solidcore bookings.

Keeps the user's primary Google Calendar in sync with their Wellhub reservations:
- Creates events for new bookings
- Deletes events when classes are cancelled in Wellhub
- Idempotent: safe to re-run multiple times

Auth: OAuth2 with offline access. Needs three env vars:
  GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET, GOOGLE_REFRESH_TOKEN

Setup: run  python setup_gcal.py  once to get the refresh token.
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

log = logging.getLogger(__name__)

SCOPES        = ["https://www.googleapis.com/auth/calendar.events"]
CALENDAR_ID   = "primary"
SOURCE_KEY    = "source"
SOURCE_VAL    = "solidcore-tracker"
ATTEND_KEY    = "attendanceId"
COLOR_ID      = "2"   # Sage green
NY            = ZoneInfo("America/New_York")

STUDIO_ADDRESSES = {
    "[solidcore] Chelsea, NY":           "155 W 23rd St, New York, NY 10011",
    "[solidcore] Greenwich Village, NY": "37 W 8th St, New York, NY 10011",
}


def _build_service():
    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import Request
    from googleapiclient.discovery import build

    creds = Credentials(
        token=None,
        refresh_token=os.environ["GOOGLE_REFRESH_TOKEN"],
        client_id=os.environ["GOOGLE_CLIENT_ID"],
        client_secret=os.environ["GOOGLE_CLIENT_SECRET"],
        token_uri="https://oauth2.googleapis.com/token",
        scopes=SCOPES,
    )
    creds.refresh(Request())
    return build("calendar", "v3", credentials=creds, cache_discovery=False)


def get_existing_events(service) -> dict[str, str]:
    """Return {attendanceId: eventId} for all solidcore-tracker events."""
    result: dict[str, str] = {}
    page_token = None
    while True:
        resp = service.events().list(
            calendarId=CALENDAR_ID,
            privateExtendedProperty=f"{SOURCE_KEY}={SOURCE_VAL}",
            maxResults=250,
            pageToken=page_token,
            showDeleted=False,
        ).execute()
        for event in resp.get("items", []):
            aid = (event.get("extendedProperties") or {}).get("private", {}).get(ATTEND_KEY)
            if aid:
                result[aid] = event["id"]
        page_token = resp.get("nextPageToken")
        if not page_token:
            break
    log.info("Found %d existing solidcore calendar events", len(result))
    return result


def _make_event(booking) -> dict:
    dt_end = booking.dt + timedelta(minutes=booking.duration_mins)
    address = STUDIO_ADDRESSES.get(booking.studio_name, booking.studio_name)
    # Clean up class name: "Studio 1 | Signature50: Full Body" → "Signature50: Full Body"
    title = booking.class_name
    if " | " in title:
        title = title.split(" | ", 1)[1]
    studio_short = booking.studio_name.replace("[solidcore] ", "").replace(", NY", "")
    return {
        "summary": f"[solidcore] {title}",
        "location": address,
        "description": f"Studio: {studio_short}\nBooked via Wellhub",
        "start": {"dateTime": booking.dt.isoformat(), "timeZone": "America/New_York"},
        "end":   {"dateTime": dt_end.isoformat(),    "timeZone": "America/New_York"},
        "colorId": COLOR_ID,
        "extendedProperties": {
            "private": {
                SOURCE_KEY: SOURCE_VAL,
                ATTEND_KEY: booking.attendance_id,
            }
        },
        "reminders": {"useDefault": True},
    }


def sync_calendar(bookings) -> tuple[int, int]:
    """
    Sync bookings to Google Calendar.
    Returns (created, deleted) counts.
    """
    service = _build_service()
    existing = get_existing_events(service)

    current_ids = {b.attendance_id for b in bookings}

    created = 0
    for booking in bookings:
        if booking.attendance_id not in existing:
            event = _make_event(booking)
            service.events().insert(calendarId=CALENDAR_ID, body=event).execute()
            log.info("Created event: %s on %s", booking.class_name, booking.dt.strftime("%a %b %-d %-I:%M %p"))
            created += 1

    deleted = 0
    for aid, event_id in existing.items():
        if aid not in current_ids:
            service.events().delete(calendarId=CALENDAR_ID, eventId=event_id).execute()
            log.info("Deleted cancelled event: %s", aid)
            deleted += 1

    log.info("Calendar sync done: %d created, %d deleted", created, deleted)
    return created, deleted
