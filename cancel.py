"""
Cancel a Wellhub booking.

Usage:
  python cancel.py --ids "attendance_id:slot_id"

The ids argument is formatted as "uniqueAttendanceIdentifier:slotId".
class_id_gql and partner_id are fetched automatically via slot details lookup.
"""

import argparse
import json
import logging
import sys

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
log = logging.getLogger(__name__)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--ids", required=True,
                        help="attendance_id:slot_id (colon-separated)")
    args = parser.parse_args()

    attendance_id = args.ids.strip()
    log.info("Cancelling: attendance_id=%s", attendance_id)

    from src.wellhub_api import cancel_class
    ok = cancel_class(attendance_id=attendance_id)

    result = {"success": ok, "attendance_id": attendance_id}
    with open("cancel_result.json", "w") as f:
        json.dump(result, f, indent=2)

    if ok:
        log.info("✅ Cancellation successful")
    else:
        log.error("❌ Cancellation failed")
        sys.exit(1)


if __name__ == "__main__":
    main()
