#!/usr/bin/env python3
"""
Booking script — called by the GitHub Actions `book.yml` workflow.

Usage:
  python book.py --ids "abc123,def456"

Reads WELLHUB_EMAIL and WELLHUB_PASSWORD from environment (GitHub Secrets).
Attempts to book each class ID in sequence and reports results.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger(__name__)


def main() -> None:
    parser = argparse.ArgumentParser(description="Book Solidcore classes via Wellhub")
    parser.add_argument(
        "--ids",
        required=True,
        help='Comma-separated Wellhub class IDs to book, e.g. "abc123,def456"',
    )
    parser.add_argument(
        "--headless",
        action="store_true",
        default=True,
        help="Run browser headless (default: True for CI)",
    )
    args = parser.parse_args()

    email    = os.environ.get("WELLHUB_EMAIL", "")
    password = os.environ.get("WELLHUB_PASSWORD", "")

    if not email or not password:
        log.error("WELLHUB_EMAIL and WELLHUB_PASSWORD must be set")
        sys.exit(1)

    class_ids = [cid.strip() for cid in args.ids.split(",") if cid.strip()]
    if not class_ids:
        log.error("No class IDs provided")
        sys.exit(1)

    log.info("Attempting to book %d class(es): %s", len(class_ids), ", ".join(class_ids))

    # Import here so the module is only loaded when booking
    from src.wellhub_api import book_class

    results: dict[str, bool] = {}
    for class_id in class_ids:
        log.info("Booking class %s ...", class_id)
        success = book_class(email, password, class_id, headless=args.headless)
        results[class_id] = success
        status = "✓ booked" if success else "✗ FAILED"
        log.info("  %s → %s", class_id, status)

    # Summary
    booked  = [cid for cid, ok in results.items() if ok]
    failed  = [cid for cid, ok in results.items() if not ok]
    log.info("Done. Booked: %d / %d", len(booked), len(class_ids))

    if failed:
        log.warning("Failed IDs: %s", ", ".join(failed))
        # Write failed IDs to a file for GitHub Actions step output
        with open("booking_failures.txt", "w") as f:
            f.write("\n".join(failed))
        sys.exit(1)

    # Write success output
    with open("booking_results.json", "w") as f:
        json.dump(results, f, indent=2)


if __name__ == "__main__":
    main()
