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
        "instructors": {"Jordan A.", "Payton B.", "Matthew C.", "Sara I.", "Bryce A.", "Sydney S."},
    },
}

TARGET_MUSCLES = {"Center Glutes", "Outer Glutes", "Leg Wrap"}

# Classes starting between 11:00 and 13:59 are "preferred"
PREFERRED_START_HOUR = 11
PREFERRED_END_HOUR   = 14   # exclusive

BOOKING_WINDOW_DAYS = 14

NOTIFY_EMAIL = "tiffanysun27@gmail.com"
