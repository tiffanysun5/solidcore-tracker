"""
Cross-reference Wellhub class slots with muscle-focus data and apply all filters:
  1. Muscle focus must match TARGET_MUSCLES (Center Glutes, Outer Glutes, Leg Wrap)
  2. Instructor must be in the approved list for that studio
  3. Time window: 11am–2pm → "preferred", outside → "other"

Returns a sorted list of MatchedClass objects ready for the email digest.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, datetime

from src.config import STUDIOS, TARGET_MUSCLES, PREFERRED_START_HOUR, PREFERRED_END_HOUR
from src.muscle_focus import muscles_for_date
from src.wellhub_api import ClassSlot

log = logging.getLogger(__name__)


@dataclass
class MatchedClass:
    slot: ClassSlot
    muscles: list[str]          # matched target muscles for that day
    all_muscles: list[str]      # full muscle focus list for that day
    preferred_time: bool        # True if 11am–2pm

    @property
    def time_label(self) -> str:
        return "PREFERRED" if self.preferred_time else "other"

    def to_dict(self) -> dict:
        d = self.slot.to_dict()
        d.update({
            "muscles": self.muscles,
            "all_muscles": self.all_muscles,
            "preferred_time": self.preferred_time,
            "time_label": self.time_label,
        })
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "MatchedClass":
        return cls(
            slot=ClassSlot.from_dict(d),
            muscles=d["muscles"],
            all_muscles=d["all_muscles"],
            preferred_time=d["preferred_time"],
        )


def apply_filters(
    slots: list[ClassSlot],
    focus_map: dict[date, list[str]],
) -> list[MatchedClass]:
    """
    Apply all three filters and return matched classes sorted by datetime.
    """
    matched: list[MatchedClass] = []

    for slot in slots:
        studio_cfg = STUDIOS.get(slot.studio)
        if studio_cfg is None:
            log.debug("Unknown studio %r — skipping", slot.studio)
            continue

        # 1. Instructor filter
        if not _instructor_matches(slot.instructor, studio_cfg["instructors"]):
            log.debug(
                "Instructor %r not in approved list for %s — skipping",
                slot.instructor, slot.studio,
            )
            continue

        # 2. Muscle focus filter
        day_muscles = muscles_for_date(focus_map, slot.date)
        matched_muscles = _matching_muscles(day_muscles)
        if not matched_muscles:
            log.debug(
                "No target muscles on %s (got %r) — skipping",
                slot.date, day_muscles,
            )
            continue

        # 3. Time preference flag (not a filter — all times are shown)
        preferred = _is_preferred_time(slot.dt)

        slot.muscles = matched_muscles
        matched.append(MatchedClass(
            slot=slot,
            muscles=matched_muscles,
            all_muscles=day_muscles,
            preferred_time=preferred,
        ))

    matched.sort(key=lambda m: m.slot.dt)
    log.info("Filter result: %d matching classes from %d slots", len(matched), len(slots))
    return matched


def _instructor_matches(instructor: str, approved: set[str]) -> bool:
    """
    Case-insensitive prefix match to handle slight name variations.
    E.g. "Maya P" matches "Maya P." and "maya p." matches "Maya P."
    """
    instructor_norm = instructor.strip().lower().rstrip(".")
    for approved_name in approved:
        if instructor_norm == approved_name.lower().rstrip("."):
            return True
        # Partial: first name + last initial
        if instructor_norm.startswith(approved_name.lower().split(".")[0].rstrip()):
            return True
    return False


def _matching_muscles(day_muscles: list[str]) -> list[str]:
    """Return TARGET_MUSCLES that appear in today's muscle focus list."""
    day_lower = {m.lower() for m in day_muscles}
    return [t for t in TARGET_MUSCLES if t.lower() in day_lower]


def _is_preferred_time(dt: datetime) -> bool:
    return PREFERRED_START_HOUR <= dt.hour < PREFERRED_END_HOUR
