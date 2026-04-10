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

    # Each entry is either:
    #   "slotId"                          (legacy — slot details lookup)
    #   "slotId:classId:partnerId"        (preferred — no extra API call)
    raw_ids = [cid.strip() for cid in args.ids.split(",") if cid.strip()]
    if not raw_ids:
        log.error("No class IDs provided")
        sys.exit(1)

    # Parse each entry
    parsed = []
    for raw in raw_ids:
        parts = raw.split(":")
        slot_id      = parts[0]
        class_id_gql = parts[1] if len(parts) > 1 else ""
        partner_id   = parts[2] if len(parts) > 2 else ""
        parsed.append((slot_id, class_id_gql, partner_id))

    log.info("Booking %d class(es)", len(parsed))

    from src.wellhub_api import book_class

    results: dict[str, dict] = {}
    failure_reasons: list[str] = []

    for slot_id, class_id_gql, partner_id in parsed:
        log.info("Booking slot %s ...", slot_id)
        try:
            ok = book_class(
                class_id=slot_id,
                class_id_gql=class_id_gql,
                partner_id=partner_id,
            )
            results[slot_id] = {"success": ok, "reason": None}
            log.info("  %s → %s", slot_id, "✓ booked" if ok else "✗ FAILED")
            if not ok:
                failure_reasons.append(f"{slot_id}: unexpected failure (no restriction returned)")
        except RuntimeError as re:
            key = getattr(re, "restriction_key", str(re))
            msg = getattr(re, "restriction_msg", "")
            results[slot_id] = {"success": False, "reason": key, "msg": msg}
            human = key.split(".")[-2] if "." in key else key  # e.g. "usage_exceeds_plan"
            log.error("  %s → ✗ RESTRICTED: %s (%s)", slot_id, human, msg)
            failure_reasons.append(f"{slot_id}: {human} — {msg}")

    booked = [cid for cid, r in results.items() if r["success"]]
    failed = [cid for cid, r in results.items() if not r["success"]]
    log.info("Done. Booked: %d / %d", len(booked), len(parsed))

    with open("booking_results.json", "w") as f:
        json.dump(results, f, indent=2)

    if failed:
        with open("booking_failures.txt", "w") as f:
            f.write("\n".join(failure_reasons))
        log.warning("Failed IDs: %s", ", ".join(failed))
        sys.exit(1)


if __name__ == "__main__":
    main()
