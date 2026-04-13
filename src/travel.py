"""
Travel detection — check Google Calendar ICS for travel dates, then fetch
Solidcore class slots in the travel city.

Primary:  fetch GOOGLE_CALENDAR_ICS_URL (GitHub secret) and scan VEVENT blocks
          for city names from config.TRAVEL_CITIES in title/location/description.
Fallback: use hardcoded_windows from config.TRAVEL_CITIES.
"""

from __future__ import annotations

import logging
import os
import re
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

log = logging.getLogger(__name__)


# ── ICS helpers ──────────────────────────────────────────────────────────────

def _parse_ics_date(val: str) -> date | None:
    """Parse DTSTART / DTEND / DATE value to a Python date."""
    val = val.split(";")[-1]  # strip params like TZID=...
    val = val.strip()
    try:
        if len(val) == 8:                          # DATE: 20260418
            return datetime.strptime(val, "%Y%m%d").date()
        if val.endswith("Z"):                       # UTC datetime
            return datetime.strptime(val, "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc).date()
        if "T" in val:                              # local datetime (no tz)
            return datetime.strptime(val[:15], "%Y%m%dT%H%M%S").date()
    except Exception:
        pass
    return None


def _unfold_ics(text: str) -> str:
    """Unfold continuation lines (RFC 5545 §3.1)."""
    return re.sub(r"\r?\n[ \t]", "", text)


def _detect_city_from_ics(ics_text: str, today: date) -> str | None:
    """
    Return the name of a TRAVEL_CITIES key if today falls within any ICS event
    whose SUMMARY, LOCATION, or DESCRIPTION contains the city name (case-insensitive).
    Returns None if no match.
    """
    from src.config import TRAVEL_CITIES

    text = _unfold_ics(ics_text)

    # Split into VEVENT blocks
    events = re.findall(r"BEGIN:VEVENT(.*?)END:VEVENT", text, re.DOTALL)
    city_names = list(TRAVEL_CITIES.keys())

    for event in events:
        # Extract fields
        def _field(name: str) -> str:
            # Match "NAME..." line then take everything after the first ":"
            m = re.search(rf"^{name}[^:\r\n]*:(.+)$", event, re.MULTILINE | re.IGNORECASE)
            return m.group(1).strip() if m else ""

        summary     = _field("SUMMARY")
        location    = _field("LOCATION")
        description = _field("DESCRIPTION")
        dtstart_raw = _field("DTSTART")
        dtend_raw   = _field("DTEND")

        haystack = f"{summary} {location} {description}".lower()

        matched_city = None
        for city in city_names:
            if city.lower() in haystack:
                matched_city = city
                break

        if not matched_city:
            continue

        start = _parse_ics_date(dtstart_raw)
        end   = _parse_ics_date(dtend_raw)
        if not start:
            continue
        # All-day DTEND is exclusive (e.g. end=Apr 22 means last day is Apr 21)
        # For datetime-based events treat end as inclusive
        if end and end != start:
            last_day = end - timedelta(days=1) if len(dtend_raw.strip()) == 8 else end
        else:
            last_day = start

        if start <= today <= last_day:
            log.info("ICS travel match: city=%s event='%s' %s–%s", matched_city, summary, start, last_day)
            return matched_city

    return None


def get_travel_city(today: date) -> str | None:
    """
    Return the name of the travel city for today, or None if at home.
    Tries ICS first; falls back to hardcoded windows.
    """
    from src.config import TRAVEL_CITIES

    ics_url = os.getenv("GOOGLE_CALENDAR_ICS_URL", "").strip()
    if ics_url:
        try:
            import requests
            resp = requests.get(ics_url, timeout=15)
            resp.raise_for_status()
            city = _detect_city_from_ics(resp.text, today)
            if city:
                return city
            log.info("ICS fetched but no travel event found for %s", today)
        except Exception as exc:
            log.warning("Could not fetch/parse ICS: %s — falling back to hardcoded windows", exc)
    else:
        log.info("GOOGLE_CALENDAR_ICS_URL not set — using hardcoded travel windows")

    # Hardcoded fallback
    for city, cfg in TRAVEL_CITIES.items():
        for start_str, end_str in cfg.get("hardcoded_windows", []):
            start = date.fromisoformat(start_str)
            end   = date.fromisoformat(end_str)
            if start <= today <= end:
                log.info("Hardcoded window match: city=%s (%s–%s)", city, start, end)
                return city

    return None


# ── Slot fetching ────────────────────────────────────────────────────────────

def get_travel_slots(city_name: str, today: date, days: int = 3) -> list:
    """
    Fetch Solidcore class slots in the travel city for `days` days starting today.
    Returns a list of ClassSlot objects (same type as get_schedule).
    """
    from src.config import TRAVEL_CITIES, BACKUP_START_HOUR, BACKUP_END_HOUR
    from src.wellhub_api import ClassSlot, _gql, SCHEDULE_QUERY  # type: ignore[attr-defined]

    cfg      = TRAVEL_CITIES.get(city_name, {})
    partners = cfg.get("partners", {})
    tz_name  = cfg.get("timezone", "America/New_York")
    city_tz  = ZoneInfo(tz_name)

    slots: list[ClassSlot] = []
    cutoff = today + timedelta(days=days - 1)

    for studio_label, partner_id in partners.items():
        current = today
        while current <= cutoff:
            start_utc = datetime(current.year, current.month, current.day, 4, 0, 0, tzinfo=timezone.utc)
            end_utc   = start_utc + timedelta(hours=23, minutes=59, seconds=59)
            try:
                results = _gql([{
                    "operationName": "partnerClassSchedule",
                    "variables": {
                        "partnerId": partner_id,
                        "filters": {
                            "startDate": start_utc.strftime("%Y-%m-%dT%H:%M:%S.000Z"),
                            "endDate":   end_utc.strftime("%Y-%m-%dT%H:%M:%S.999Z"),
                        },
                        "deviceLocation": {"coordinates": [41.8781, -87.6298] if "Chicago" in city_name else [42.3601, -71.0589], "type": "shared"},
                    },
                    "query": SCHEDULE_QUERY,
                }])
                items = (results[0].get("data", {})
                         .get("partnerClassSchedule", {})
                         .get("items", []))
                for item in items:
                    if item.get("isDisabled"):
                        continue
                    instructors = item.get("instructors", [])
                    instructor  = (instructors[0]["name"].split(" - ")[0].strip()
                                   if instructors else "")
                    dt_raw = item.get("date", "")
                    try:
                        dt = datetime.fromisoformat(dt_raw.replace("Z", "+00:00"))
                        dt = dt.astimezone(city_tz)
                    except Exception:
                        continue
                    if not (BACKUP_START_HOUR <= dt.hour < BACKUP_END_HOUR):
                        continue
                    slots.append(ClassSlot(
                        wellhub_class_id = item.get("id", ""),
                        class_id_gql     = str(item.get("classId", "")),
                        partner_id       = partner_id,
                        studio           = studio_label,
                        instructor       = instructor,
                        dt               = dt,
                        available_spots  = item.get("availableSpots", 0),
                    ))
            except Exception as exc:
                log.debug("Travel fetch error %s %s %s: %s", city_name, studio_label, current, exc)
            current += timedelta(days=1)

    slots.sort(key=lambda s: (s.date, s.dt))
    log.info("Travel slots for %s: %d", city_name, len(slots))
    return slots
