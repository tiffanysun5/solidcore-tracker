"""
Central config — studios, instructors, muscle targets, time prefs.
"""

STUDIOS = {
    "Chelsea": {
        "address": "155 W 23rd St",
        "partner_id": "05d7c377-69fa-40a5-9a05-aaa21e2f9d8c",
        "instructors": {"Maya P.", "Katie D.", "John B.", "Jaime F.", "Robert C.", "Sydney S.", "Will T."},
    },
    "Greenwich Village": {
        "address": "37 W 8th St",
        "partner_id": "688587f9-f40d-43dc-ac8e-2922c1a12915",
        # Senior Master Coaches only
        "instructors": {"Angie M.", "Bryce A.", "Matt C.", "Payton B.", "Sara I."},
    },
}

TARGET_MUSCLES = {"Center Glutes", "Outer Glutes", "Leg Wrap"}

# Classes starting between 11:00 and 13:59 are "preferred"
PREFERRED_START_HOUR = 11
PREFERRED_END_HOUR   = 14   # exclusive

# Backup window: 9am–7pm (anything outside this is excluded entirely)
BACKUP_START_HOUR = 9
BACKUP_END_HOUR   = 19  # exclusive (7pm cutoff)

BOOKING_WINDOW_DAYS = 14
WEEKLY_CLASS_LIMIT  = 4   # max solidcore (premium) classes per week

# Cancellation penalty windows (hours before class — cancel after this = late cancel / lost check-in)
# Used to show a warning badge in the booked section of the email.
CANCEL_WINDOWS: dict[str, int] = {
    "solidcore": 12,   # Solidcore: 12h free cancel window
    "nofar":     24,   # Nofar Method: 24h free cancel window
    "corepower": 2,    # CorePower: 2h free cancel window
}

# Extra studios shown as backup at bottom of email — standard (1/day) classes, not counted in quota.
EXTRA_STUDIOS = {
    "Nofar Method - Flatiron": {
        "partner_id": "0a283587-673b-4cea-9796-68b5bf387ae1",
        "class_filter": None,
    },
    "CorePower Yoga Sculpt - Flatiron":          {"partner_id": "f2140a07-8621-45b5-96c7-2f57233cdd4e", "class_filter": "yoga sculpt"},
    "CorePower Yoga Sculpt - Greenwich Village": {"partner_id": "7b892807-f83e-477a-9e33-1f193b1d2684", "class_filter": "yoga sculpt"},
}

# Monthly once-per-month studios — reminder shown in email if not yet visited this month.
# Matched against studio name in Wellhub check-in history (case-insensitive substring).
MONTHLY_STUDIOS = ["othership", "stretch*d", "nofar"]

# Per-studio monthly class limits.  Tracked in the email's monthly section.
# late cancels count (they consume a Wellhub check-in just like attendance).
MONTHLY_LIMITS: dict[str, int] = {
    "nofar": 6,
}

NOTIFY_EMAIL = "tiffanysun27@gmail.com"

# Travel cities — partner IDs for Solidcore locations in each city.
# Timezone is the local tz used to display class times.
# Hardcoded travel windows (date strings) are used as fallback when
# GOOGLE_CALENDAR_ICS_URL secret is not set.
TRAVEL_CITIES: dict[str, dict] = {
    "Chicago": {
        "timezone": "America/Chicago",
        "partners": {
            "River North":    "c1b09896-3bd0-4d08-b89e-d7d9408275fb",
            "Streeterville":  "90202013-f8b0-4623-9b4d-9abb72bd87be",
            "West Loop":      "5d57bda0-ccb8-4ad1-a262-8080e727cb75",
            "Wicker Park":    "5c16faa7-2f41-4a18-a878-6220681b0f68",
            "Boystown":       "5c45a8f9-adcb-4985-aabc-96b00234298f",
            "Lincoln Park":   "ce72eb32-7e9f-4b8b-a7e7-8f8c7ef4861a",
        },
        "hardcoded_windows": [],
    },
    "Boston": {
        "timezone": "America/New_York",
        "partners": {
            "Fenway":            "ac500bc5-8488-4a41-ac5d-7e96466aba01",
            "Boston SE":         "84749896-1bf6-4169-8f5a-1b7fbdb101fe",
            "North Station":     "a03f9fae-b2fe-49f7-b773-62f5c6506f59",
            "Seaport":           "07bbd946-312d-4dc6-ace2-9c4ff7ff385b",
            "Arsenal Yards":     "41624ab6-f7c3-417d-a704-2c856f6cbb0c",
            "Chestnut Hill":     "d16af206-af1a-4cd9-9c87-013de5c25fec",
            "Dedham":            "5f3a0666-85d6-42d2-a9e9-1f5700f91486",
            "Hingham":           "9b2de8de-da34-4e8b-8f08-a8972eeda332",
            "Burlington":        "ed6ffbb6-e93c-4747-bc7c-388a79f9eac1",
        },
        "hardcoded_windows": [
            ("2026-04-25", "2026-04-25"),
        ],
    },
}
