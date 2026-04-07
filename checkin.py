"""
Auto check-in for Wellhub/Solidcore.

Triggered by iOS Shortcut location automation (arriving within ~400m of studio).
Uses attendanceCheckinBooking to find today's upcoming class, then calls the
check-in mutation.

NOTE: The check-in mutation name is not yet known — needs mitmproxy capture
of the Wellhub app's check-in tap. Replace the CHECKIN_MUTATION stub below
once captured.
"""

import json
import logging
import sys
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
log = logging.getLogger(__name__)

NY = ZoneInfo("America/New_York")

CHECKIN_BOOKING_QUERY = """
query attendanceCheckinBooking($input: AttendanceCheckinBookingInput) {
  attendanceCheckinBooking(input: $input) {
    uniqueAttendanceIdentifier
    status
    class { slotId occurDate }
  }
}
"""

# ── TODO: Replace with real mutation once captured via mitmproxy ──────────────
# When you tap check-in in the Wellhub app, capture the network request.
# It will show the mutation name (e.g. "attendanceCheckin") and its input type.
# Paste both here.
CHECKIN_MUTATION = None   # e.g. """mutation attendanceCheckin(...) { ... }"""
# ─────────────────────────────────────────────────────────────────────────────


def get_todays_checkin_booking():
    """Find today's booked class that is ready to check in (status != COMPLETED)."""
    from src.wellhub_api import _gql
    now = datetime.now(tz=NY)

    results = _gql([{
        "operationName": "attendanceCheckinBooking",
        "variables": {"input": {"showAllWalkInStatus": True, "inComponentFeedback": True}},
        "query": CHECKIN_BOOKING_QUERY,
    }])
    bookings = results[0].get("data", {}).get("attendanceCheckinBooking", []) or []

    for cb in bookings:
        status = cb.get("status", "")
        occur  = cb.get("class", {}).get("occurDate", "")
        if not occur:
            continue
        dt = datetime.fromisoformat(occur.replace("Z", "+00:00")).astimezone(NY)
        if dt.date() == now.date() and status != "COMPLETED":
            log.info("Found today's check-in booking: uid=%s status=%s dt=%s",
                     cb["uniqueAttendanceIdentifier"], status, dt)
            return cb
        elif dt.date() == now.date():
            log.info("Today's booking already COMPLETED (already checked in): %s",
                     cb["uniqueAttendanceIdentifier"])
            return cb  # still return so caller can report

    log.info("No check-in booking found for today")
    return None


def do_checkin(uid: str, slot_id: str) -> bool:
    """Call the check-in mutation. Replace stub once mutation is known."""
    if CHECKIN_MUTATION is None:
        log.error(
            "Check-in mutation not yet known. "
            "Capture it via mitmproxy (tap check-in in the Wellhub app) "
            "and update CHECKIN_MUTATION in checkin.py."
        )
        return False

    from src.wellhub_api import _gql, LAT, LNG
    # TODO: fill in correct input fields once mutation is known
    results = _gql([{
        "operationName": "attendanceCheckin",   # update name if different
        "variables": {
            "input": {
                "uniqueAttendanceIdentifier": uid,
                "slotId": slot_id,
                "latitude": LAT,
                "longitude": LNG,
            }
        },
        "query": CHECKIN_MUTATION,
    }])
    data   = results[0].get("data", {})
    errors = results[0].get("errors")
    if errors:
        log.error("Check-in errors: %s", errors)
        return False
    log.info("Check-in response: %s", data)
    return True


def main():
    cb = get_todays_checkin_booking()

    result = {"success": False, "status": "no_booking"}

    if cb:
        uid     = cb["uniqueAttendanceIdentifier"]
        slot_id = str(cb["class"]["slotId"])
        status  = cb.get("status", "")

        if status == "COMPLETED":
            log.info("Already checked in.")
            result = {"success": True, "status": "already_checked_in", "uid": uid}
        else:
            ok = do_checkin(uid, slot_id)
            result = {"success": ok, "status": "checked_in" if ok else "failed", "uid": uid}

    with open("checkin_result.json", "w") as f:
        json.dump(result, f, indent=2)

    if result["success"]:
        log.info("✅ Check-in result: %s", result["status"])
    else:
        log.error("❌ Check-in result: %s", result["status"])
        if result["status"] != "no_booking":
            sys.exit(1)


if __name__ == "__main__":
    main()
