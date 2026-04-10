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
MONTHLY_STUDIOS = ["othership", "stretch"]

NOTIFY_EMAIL = "tiffanysun27@gmail.com"
