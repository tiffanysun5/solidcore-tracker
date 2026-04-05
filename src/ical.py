"""
Generate an iCalendar (.ics) file from upcoming Wellhub bookings.
Hosted on GitHub Pages so any calendar app (Google, Apple, Outlook) can
subscribe to the URL and stay in sync automatically.
"""

from __future__ import annotations

from datetime import timedelta
from zoneinfo import ZoneInfo

NY = ZoneInfo("America/New_York")

STUDIO_ADDRESSES = {
    "[solidcore] Chelsea, NY":           "155 W 23rd St, New York, NY 10011",
    "[solidcore] Greenwich Village, NY": "37 W 8th St, New York, NY 10011",
}


def generate_ics(bookings) -> str:
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//Solidcore Tracker//EN",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        "X-WR-CALNAME:Solidcore Classes",
        "X-WR-TIMEZONE:America/New_York",
    ]

    for b in bookings:
        dt_start = b.dt
        dt_end   = dt_start + timedelta(minutes=b.duration_mins)

        # Clean up class name
        title = b.class_name
        if " | " in title:
            title = title.split(" | ", 1)[1]
        studio_short = b.studio_name.replace("[solidcore] ", "").replace(", NY", "")
        address = STUDIO_ADDRESSES.get(b.studio_name, b.studio_name)

        def fmt(dt):
            return dt.strftime("%Y%m%dT%H%M%S")

        lines += [
            "BEGIN:VEVENT",
            f"UID:{b.attendance_id}@solidcore-tracker",
            f"DTSTART;TZID=America/New_York:{fmt(dt_start)}",
            f"DTEND;TZID=America/New_York:{fmt(dt_end)}",
            f"SUMMARY:[solidcore] {title}",
            f"LOCATION:{address}",
            f"DESCRIPTION:Studio: {studio_short}\\nBooked via Wellhub",
            "STATUS:CONFIRMED",
            "END:VEVENT",
        ]

    lines.append("END:VCALENDAR")
    return "\r\n".join(lines) + "\r\n"
