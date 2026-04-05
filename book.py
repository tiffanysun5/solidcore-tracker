#!/usr/bin/env python3
"""
Booking script — called by GitHub Actions book.yml workflow.

Usage:
  python book.py --ids "209250916,208540617"

Reads WELLHUB_REFRESH_TOKEN from environment (GitHub Secret).
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger(__name__)

# Load .env if present (local runs)
_env = Path(".env")
if _env.exists():
    for line in _env.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, _, v = line.partition("=")
            os.environ.setdefault(k.strip(), v.strip())


def main() -> None:
    parser = argparse.ArgumentParser(description="Book Solidcore classes via Wellhub API")
    parser.add_argument("--ids", required=True,
                        help='Comma-separated Wellhub slot IDs, e.g. "209250916,208540617"')
    args = parser.parse_args()

    if not os.environ.get("WELLHUB_REFRESH_TOKEN"):
        log.error("WELLHUB_REFRESH_TOKEN must be set")
        sys.exit(1)

    class_ids = [cid.strip() for cid in args.ids.split(",") if cid.strip()]
    if not class_ids:
        log.error("No class IDs provided")
        sys.exit(1)

    log.info("Booking %d class(es): %s", len(class_ids), ", ".join(class_ids))

    from src.wellhub_api import book_class

    results: dict[str, bool] = {}
    for class_id in class_ids:
        log.info("Booking slot %s ...", class_id)
        success = book_class(class_id=class_id)
        results[class_id] = success
        log.info("  %s → %s", class_id, "✓ booked" if success else "✗ FAILED")

    booked = [cid for cid, ok in results.items() if ok]
    failed = [cid for cid, ok in results.items() if not ok]
    log.info("Done. Booked: %d / %d", len(booked), len(class_ids))

    with open("booking_results.json", "w") as f:
        json.dump(results, f, indent=2)

    if failed:
        with open("booking_failures.txt", "w") as f:
            f.write("\n".join(failed))
        log.warning("Failed IDs: %s", ", ".join(failed))
        sys.exit(1)


if __name__ == "__main__":
    main()
