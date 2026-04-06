"""
Wellhub API client — direct HTTP/GraphQL, no browser needed.

Reverse-engineered from mitmproxy capture of the Wellhub iOS app.
All calls go to: https://mobile-api.gympass.com/enduser/v1/frontdoor (GraphQL)
Auth:            https://identity.gympass.com (Keycloak, refresh token flow)

Tokens are persisted to tokens.json and auto-refreshed when expired.
"""

from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

import requests

from src.config import STUDIOS, BOOKING_WINDOW_DAYS

log = logging.getLogger(__name__)

# ── Constants ──────────────────────────────────────────────────────────────

TOKEN_URL    = "https://identity.gympass.com/auth/realms/master/protocol/openid-connect/token"
GRAPHQL_URL  = "https://mobile-api.gympass.com/enduser/v1/frontdoor"
TOKENS_FILE  = Path(__file__).parent.parent / "tokens.json"

CLIENT_ID    = "mobile-sso"
PRODUCT_ID   = "6bf65f35-8e38-4788-ba90-b98709a1fa8e"

# NYC coords (used as device location)
LAT = 40.7317
LNG = -73.9925

BASE_HEADERS = {
    "user-agent":        "Mozilla/5.0 (iPhone; CPU iPhone OS 18_6_2 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148",
    "x-device-os":       "iOS",
    "x-device-os-version": "18.6.2",
    "x-device-brand":    "Apple",
    "x-device-model":    "iPhone17,1",
    "x-device-id":       "DAC2CA4E24754CDBB5422602B394797A",
    "x-anchor":          "HVHTGqQlhrwKg9wThyr_K1zhJ72zCzhqG6QviwBmTzc",
    "app-version":       "10.45.9",
    "timezone":          "America/New_York",
    "accept":            "*/*",
    "accept-language":   "en-US",
    "device-session-id": "1775396154529",
}


# ── Token management ───────────────────────────────────────────────────────

class TokenStore:
    def __init__(self):
        self._data: dict = {}
        self._load()

    def _load(self):
        # Try file first, then env var
        if TOKENS_FILE.exists():
            self._data = json.loads(TOKENS_FILE.read_text())
        elif os.getenv("WELLHUB_REFRESH_TOKEN"):
            self._data = {"refresh_token": os.getenv("WELLHUB_REFRESH_TOKEN")}

    def _save(self):
        TOKENS_FILE.parent.mkdir(exist_ok=True)
        TOKENS_FILE.write_text(json.dumps(self._data, indent=2))

    @property
    def refresh_token(self) -> str:
        return self._data.get("refresh_token", "")

    @property
    def access_token(self) -> str:
        return self._data.get("access_token", "")

    @property
    def expires_at(self) -> float:
        return self._data.get("expires_at", 0.0)

    def is_access_valid(self) -> bool:
        return bool(self.access_token) and time.time() < self.expires_at - 60

    def refresh(self) -> str:
        """Exchange refresh token for a new access token. Returns access token."""
        if not self.refresh_token:
            raise RuntimeError("No refresh token available. Re-run mitmproxy capture.")

        log.info("Refreshing Wellhub access token")
        resp = requests.post(
            TOKEN_URL,
            data={
                "grant_type":    "refresh_token",
                "client_id":     CLIENT_ID,
                "refresh_token": self.refresh_token,
            },
            headers={**BASE_HEADERS, "content-type": "application/x-www-form-urlencoded"},
            timeout=15,
        )
        resp.raise_for_status()
        r = resp.json()

        self._data.update({
            "access_token":  r["access_token"],
            "refresh_token": r.get("refresh_token", self.refresh_token),
            "expires_at":    time.time() + r.get("expires_in", 3600),
        })
        self._save()
        log.info("Token refreshed, expires in %ds", r.get("expires_in", 3600))
        return self._data["access_token"]

    def get_access_token(self) -> str:
        if not self.is_access_valid():
            return self.refresh()
        return self.access_token


_token_store = TokenStore()


# ── GraphQL helpers ────────────────────────────────────────────────────────

def _gql(operations: list[dict]) -> list[dict]:
    """POST one or more GraphQL operations to the frontdoor endpoint."""
    token = _token_store.get_access_token()
    resp = requests.post(
        GRAPHQL_URL,
        json=operations,
        headers={
            **BASE_HEADERS,
            "content-type":  "application/json",
            "authorization": f"Bearer {token}",
        },
        timeout=20,
    )
    resp.raise_for_status()
    return resp.json()


# ── ClassSlot (reuse same dataclass shape as old wellhub.py) ──────────────

@dataclass
class ClassSlot:
    wellhub_class_id: str        # slot ID (used for booking)
    studio: str
    instructor: str
    dt: datetime
    booked: bool = False
    muscles: list[str] = field(default_factory=list)
    class_id_gql: str = ""       # classId from partnerClassSchedule (needed for bookingAttendance)
    partner_id: str = ""         # partnerId (per-studio constant)

    @property
    def date(self) -> date:
        return self.dt.date()

    @property
    def time_str(self) -> str:
        return self.dt.strftime("%-I:%M %p")

    @property
    def date_str(self) -> str:
        return self.dt.strftime("%a %b %-d")

    def to_dict(self) -> dict:
        return {
            "id": self.wellhub_class_id,
            "studio": self.studio,
            "instructor": self.instructor,
            "datetime": self.dt.isoformat(),
            "booked": self.booked,
            "muscles": self.muscles,
            "class_id_gql": self.class_id_gql,
            "partner_id": self.partner_id,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "ClassSlot":
        return cls(
            wellhub_class_id=d["id"],
            studio=d["studio"],
            instructor=d["instructor"],
            dt=datetime.fromisoformat(d["datetime"]),
            booked=d.get("booked", False),
            muscles=d.get("muscles", []),
            class_id_gql=d.get("class_id_gql", ""),
            partner_id=d.get("partner_id", ""),
        )


# ── Schedule query ─────────────────────────────────────────────────────────

SCHEDULE_QUERY = (
    "query partnerClassSchedule($partnerId: ID!, $filters: PartnerClassScheduleFilters!, $deviceLocation: DeviceLocationV2) {\n"
    "  partnerClassSchedule(\n"
    "    input: {partnerId: $partnerId, filters: $filters, deviceLocation: $deviceLocation}\n"
    "  ) {\n"
    "    items {\n"
    "      id\n"
    "      classId\n"
    "      name\n"
    "      date\n"
    "      duration\n"
    "      virtual\n"
    "      instructors {\n"
    "        name\n"
    "        __typename\n"
    "      }\n"
    "      restrictionGroup\n"
    "      availableSpots\n"
    "      isDisabled\n"
    "      formattedHour\n"
    "      featureTag {\n"
    "        translationKey\n"
    "        slug\n"
    "        primaryColor\n"
    "        parameter\n"
    "        __typename\n"
    "      }\n"
    "      __typename\n"
    "    }\n"
    "    __typename\n"
    "  }\n"
    "}"
)

def get_schedule(email: str = "", password: str = "", headless: bool = True) -> list[ClassSlot]:
    """Fetch Solidcore classes for the next BOOKING_WINDOW_DAYS from both studios."""
    slots: list[ClassSlot] = []
    today = datetime.now(timezone.utc).date()
    cutoff = today + timedelta(days=BOOKING_WINDOW_DAYS)

    for studio_name, studio_cfg in STUDIOS.items():
        partner_id = studio_cfg["partner_id"]
        log.info("Fetching schedule for %s (partner %s)", studio_name, partner_id)

        # Fetch one day at a time (matches app behaviour, avoids large responses)
        current = today
        while current <= cutoff:
            # Date window: midnight ET to midnight ET next day in UTC
            start = datetime(current.year, current.month, current.day, 4, 0, 0, tzinfo=timezone.utc)
            end   = start + timedelta(hours=23, minutes=59, seconds=59)

            try:
                results = _gql([{
                    "operationName": "partnerClassSchedule",
                    "variables": {
                        "partnerId": partner_id,
                        "filters": {
                            "startDate": start.strftime("%Y-%m-%dT%H:%M:%S.000Z"),
                            "endDate":   end.strftime("%Y-%m-%dT%H:%M:%S.999Z"),
                        },
                        "deviceLocation": {
                            "coordinates": [LAT, LNG],
                            "type": "shared",
                        },
                    },
                    "query": SCHEDULE_QUERY,
                }])

                items = (results[0].get("data", {})
                         .get("partnerClassSchedule", {})
                         .get("items", []))

                for item in items:
                    if item.get("isDisabled"):
                        continue  # no spots
                    instructors = item.get("instructors", [])
                    instructor = instructors[0]["name"] if instructors else "Unknown"
                    # Strip title suffix e.g. "Maya P. - Senior Master Coach" → "Maya P."
                    instructor = instructor.split(" - ")[0].strip()

                    dt_raw = item.get("date", "")
                    try:
                        dt = datetime.fromisoformat(dt_raw.replace("Z", "+00:00"))
                        # Convert to ET (UTC-4 during EDT, UTC-5 during EST)
                        from zoneinfo import ZoneInfo
                        dt = dt.astimezone(ZoneInfo("America/New_York"))
                    except Exception:
                        continue

                    slots.append(ClassSlot(
                        wellhub_class_id=item["id"],
                        studio=studio_name,
                        instructor=instructor,
                        dt=dt,
                        class_id_gql=str(item.get("classId", "")),
                        partner_id=studio_cfg["partner_id"],
                    ))

            except Exception as exc:
                log.error("Error fetching %s for %s: %s", current, studio_name, exc)

            current += timedelta(days=1)

        log.info("  %s: %d bookable slots", studio_name, sum(1 for s in slots if s.studio == studio_name))

    return slots


# ── Booking ────────────────────────────────────────────────────────────────

BOOKING_MUTATION = """
mutation bookingAttendance($input: BookingAttendanceRequest!, $isBookingGeofenceEnabled: Boolean!) {
  bookingAttendance(input: $input) {
    uniqueAttendanceIdentifier
    partnerGeofence @include(if: $isBookingGeofenceEnabled) {
      radiusInMeters
      partnerId
      longitude
      latitude
      classOccurDate
      classDuration
      __typename
    }
    restriction {
      metadata
      title {
        key
        params
        namespace
        __typename
      }
      message {
        key
        params
        namespace
        __typename
      }
      button {
        label {
          value {
            ... on Translation {
              key
              params
              namespace
              __typename
            }
            __typename
          }
          accessibilityHint {
            ... on Translation {
              key
              params
              namespace
              __typename
            }
            __typename
          }
          __typename
        }
        __typename
      }
      trackEventType
      action
      route
      secondaryAction {
        action
        label {
          value {
            ... on Translation {
              key
              params
              namespace
              __typename
            }
            __typename
          }
          accessibilityHint {
            ... on Translation {
              key
              params
              namespace
              __typename
            }
            __typename
          }
          __typename
        }
        enabled
        route {
          name
          params
          __typename
        }
        __typename
      }
      __typename
    }
    __typename
  }
}
"""

def book_class(
    class_id: str = "",
    class_id_gql: str = "",
    partner_id: str = "",
    # legacy kwargs ignored
    email: str = "", password: str = "", headless: bool = True,
) -> bool:
    """
    Book a class slot.
    class_id       = slot ID (the `id` from partnerClassSchedule)
    class_id_gql   = classId from the same query (pass through from ClassSlot)
    partner_id     = partner UUID (per-studio constant from STUDIOS config)

    If class_id_gql / partner_id are not supplied, falls back to slot-details lookup.
    """
    log.info("Booking slot %s (classId=%s partner=%s)", class_id, class_id_gql, partner_id)

    if not class_id_gql or not partner_id:
        log.info("classId/partnerId not provided — fetching via slot details")
        slot_details = _get_slot_details(class_id)
        if slot_details:
            class_id_gql = class_id_gql or slot_details.get("classId", "")
            partner_id   = partner_id   or slot_details.get("partnerId", "")

    if not class_id_gql or not partner_id:
        log.error("Cannot book slot %s — missing classId or partnerId", class_id)
        return False

    try:
        results = _gql([{
            "operationName": "bookingAttendance",
            "variables": {
                "isBookingGeofenceEnabled": True,
                "input": {
                    "slotId":    class_id,
                    "classId":   class_id_gql,
                    "productId": PRODUCT_ID,
                    "partnerId": partner_id,
                    "fingerprint": {
                        "version":          "10.45.9",
                        "ip_address":       "::2600:4041:5ee7:8a00:3449:d6ae",
                        "mac_address":      "02:00:00:00:00:00",
                        "device_os":        "ios",
                        "os_version":       "18.6.2",
                        "device_model_id":  "iPhone17,1",
                        "device_model":     "iPhone 16 Pro",
                        "firebase_instance_id": "DAC2CA4E24754CDBB5422602B394797A",
                        "last_valid_latitude":  "undefined",
                        "last_valid_longitute": "undefined",
                        "mocked_location":  "undefined",
                    },
                    "latitude":  LAT,
                    "longitude": LNG,
                },
            },
            "query": BOOKING_MUTATION,
        }])

        data = results[0].get("data", {}).get("bookingAttendance", {})
        uid  = data.get("uniqueAttendanceIdentifier")
        restriction = data.get("restriction")

        if uid and not restriction:
            log.info("Booking confirmed. uniqueAttendanceIdentifier: %s", uid)
            return True
        elif restriction:
            title = restriction.get("title", {}).get("key", "unknown")
            msg   = restriction.get("message", {}).get("key", "")
            log.error("Booking restricted: %s — %s", title, msg)
            return False
        else:
            log.error("Unexpected booking response: %s", results)
            return False

    except Exception as exc:
        log.error("Booking error for slot %s: %s", class_id, exc)
        return False


SLOT_DETAILS_QUERY = """
query classSlotDetailsQuery($input: ClassSlotDetailsInput!) {
  classSlotDetails(input: $input) {
    slot {
      id
      classId
      partner { id }
    }
  }
}
"""

# ── Already-booked dates ───────────────────────────────────────────────────

CHECKIN_BOOKING_QUERY = """
query attendanceCheckinBooking($input: AttendanceCheckinBookingInput) {
  attendanceCheckinBooking(input: $input) {
    uniqueAttendanceIdentifier
    status
    class {
      slotId
      occurDate
    }
  }
}
"""

PROFILE_SCHEDULE_QUERY = "query profilePerformance($settings: JSONObject, $variables: JSONObject, $isFamilyMember: Boolean!, $includeCheckInBookingHistory: Boolean!, $maxChallengesSize: Int, $challengesSettings: JSONObject, $badgesSettings: JSONObject) @flow(name: \"profile\") {\n  profilePerformance(settings: $settings) {\n    header {\n      title\n      tag {\n        textTag {\n          key\n          params\n          __typename\n        }\n        events {\n          clickstream {\n            name\n            params\n            __typename\n          }\n          __typename\n        }\n        __typename\n      }\n      subtitle {\n        key\n        params\n        __typename\n      }\n      __typename\n    }\n    sections {\n      ...StatisticsFragment\n      ...StreaksFragment\n      ...ClassScheduleFragment\n      ...FavoritesFragment\n      ...RecentActivitiesFragment @skip(if: $includeCheckInBookingHistory)\n      ...ActivatedAppsFragment\n      ...FamilyMemberFragment @include(if: $isFamilyMember)\n      ...EligibleChallengesFragment\n      ...WellhubAiEntrypointFragment\n      ...BadgesFragment\n      ...CheckInBookingHistoryFragment @include(if: $includeCheckInBookingHistory)\n      __typename\n    }\n    __typename\n  }\n}\n\nfragment StatisticsFragment on StatisticsProfilePerformance {\n  title {\n    key\n    params\n    __typename\n  }\n  sectionData {\n    checkInCount {\n      value\n      events {\n        clickstream {\n          name\n          params\n          __typename\n        }\n        __typename\n      }\n      __typename\n    }\n    statisticsEvents: events {\n      pageview {\n        name\n        params\n        __typename\n      }\n      __typename\n    }\n    __typename\n  }\n  __typename\n}\n\nfragment StreaksFragment on StreaksProfilePerformance {\n  sectionData {\n    ... on StreaksSuccess {\n      visualState\n      streakCount\n      progressFilled\n      progressTotal\n      __typename\n    }\n    __typename\n  }\n  __typename\n}\n\nfragment ClassScheduleFragment on ClassScheduleProfilePerformance {\n  title {\n    key\n    params\n    __typename\n  }\n  sectionData {\n    ... on ClassScheduleSuccess {\n      cards {\n        small\n        details {\n          name\n          place\n          time\n          __typename\n        }\n        date {\n          day\n          dayOfWeek\n          month\n          __typename\n        }\n        exploreRedirect {\n          startDate\n          endDate\n          __typename\n        }\n        link {\n          label {\n            key\n            params\n            __typename\n          }\n          __typename\n        }\n        uniqueAttendanceIdentifier\n        type\n        events {\n          clickstream {\n            name\n            params\n            __typename\n          }\n          __typename\n        }\n        __typename\n      }\n      events {\n        pageview {\n          name\n          params\n          __typename\n        }\n        __typename\n      }\n      __typename\n    }\n    __typename\n  }\n  __typename\n}\n\nfragment FavoritesFragment on FavoritesProfilePerformance {\n  title {\n    key\n    params\n    __typename\n  }\n  sectionData {\n    ... on ListFavoritesSuccess {\n      favorites {\n        partnerId\n        name\n        logo\n        variant\n        events {\n          clickstream {\n            name\n            params\n            __typename\n          }\n          __typename\n        }\n        __typename\n      }\n      favoritesEvents: events {\n        pageview {\n          name\n          params\n          __typename\n        }\n        __typename\n      }\n      __typename\n    }\n    __typename\n  }\n  __typename\n}\n\nfragment RecentActivitiesFragment on RecentActivitiesProfilePerformance {\n  title {\n    key\n    params\n    __typename\n  }\n  sectionData(variables: $variables) {\n    ... on RecentActivitiesSuccess {\n      recentItems: items {\n        id\n        type {\n          attendanceType\n          iconType\n          description {\n            key\n            params\n            __typename\n          }\n          __typename\n        }\n        avatarUrl\n        partnerId\n        title\n        subtitle\n        datetime\n        events {\n          clickstream {\n            name\n            params\n            __typename\n          }\n          __typename\n        }\n        ratingLink {\n          label {\n            key\n            __typename\n          }\n          events {\n            clickstream {\n              name\n              params\n              __typename\n            }\n            __typename\n          }\n          __typename\n        }\n        productId\n        isPersonalTrainer\n        partnerType\n        transactionalId\n        __typename\n      }\n      recentEvents: events {\n        pageview {\n          name\n          params\n          __typename\n        }\n        __typename\n      }\n      __typename\n    }\n    __typename\n  }\n  __typename\n}\n\nfragment ActivatedAppsFragment on ActivatedAppsProfilePerformance {\n  title {\n    key\n    params\n    __typename\n  }\n  sectionData {\n    title {\n      key\n      params\n      __typename\n    }\n    description {\n      key\n      params\n      __typename\n    }\n    activatedAppsItems: items {\n      id\n      name\n      slug\n      logoUrl\n      mainCategory\n      events {\n        clickstream {\n          name\n          params\n          __typename\n        }\n        __typename\n      }\n      __typename\n    }\n    action {\n      label {\n        key\n        params\n        __typename\n      }\n      events {\n        clickstream {\n          name\n          params\n          __typename\n        }\n        __typename\n      }\n      __typename\n    }\n    activatedAppsEvents: events {\n      pageview {\n        name\n        params\n        __typename\n      }\n      __typename\n    }\n    __typename\n  }\n  __typename\n}\n\nfragment FamilyMemberFragment on FamilyMemberProfilePerformance {\n  title {\n    key\n    params\n    __typename\n  }\n  sectionData {\n    hasAvailable\n    fmSubscriptionsAvailable\n    __typename\n  }\n  __typename\n}\n\nfragment EligibleChallengesFragment on ListEligibleChallengesProfilePerformance {\n  title {\n    key\n    params\n    __typename\n  }\n  sectionData(\n    maxChallengesSize: $maxChallengesSize\n    challengesSettings: $challengesSettings\n  ) {\n    ... on ListEligibleChallengesSuccess {\n      eligibleChallenges {\n        challengeId\n        imageUrl\n        promotedBy\n        creatorName\n        dateStatus {\n          label {\n            ... on Label {\n              value\n              __typename\n            }\n            ... on Translation {\n              key\n              params\n              __typename\n            }\n            __typename\n          }\n          __typename\n        }\n        translatableTitle {\n          ... on Label {\n            value\n            __typename\n          }\n          ... on Translation {\n            key\n            __typename\n          }\n          __typename\n        }\n        status {\n          label {\n            key\n            params\n            __typename\n          }\n          value\n          variant\n          __typename\n        }\n        __typename\n      }\n      showBanner\n      ...HighlightedChallengeFragment\n      ...ParticipatingChallengesFragment\n      ...NextMovesChallengesFragment\n      __typename\n    }\n    __typename\n  }\n  __typename\n}\n\nfragment HighlightedChallengeFragment on ListEligibleChallengesSuccess {\n  highlightedChallenge {\n    challengeId\n    translatableTitle {\n      ... on Label {\n        value\n        __typename\n      }\n      ... on Translation {\n        key\n        __typename\n      }\n      __typename\n    }\n    imageUrl\n    promotedBy\n    creatorName\n    goal\n    totalParticipants\n    type\n    metric\n    isNewChallenge\n    __typename\n  }\n  __typename\n}\n\nfragment ParticipatingChallengesFragment on ListEligibleChallengesSuccess {\n  participatingChallenges {\n    challengeId\n    translatableTitle {\n      ... on Label {\n        value\n        __typename\n      }\n      ... on Translation {\n        key\n        __typename\n      }\n      __typename\n    }\n    avatarUrl\n    promotedBy\n    creatorName\n    status\n    dateStatus {\n      daysLeft\n      hoursLeft\n      __typename\n    }\n    goal\n    currentScore\n    metric\n    progressPercentage\n    goalAchieved\n    progressBarColors {\n      initialColor\n      finalColor\n      __typename\n    }\n    __typename\n  }\n  showParticipatingSeeAll\n  __typename\n}\n\nfragment NextMovesChallengesFragment on ListEligibleChallengesSuccess {\n  nextMovesChallenges {\n    challengeId\n    translatableTitle {\n      ... on Label {\n        value\n        __typename\n      }\n      ... on Translation {\n        key\n        __typename\n      }\n      __typename\n    }\n    avatarUrl\n    promotedBy\n    creatorName\n    status\n    isNewChallenge\n    dateStatus {\n      daysLeft\n      hoursLeft\n      __typename\n    }\n    __typename\n  }\n  __typename\n}\n\nfragment WellhubAiEntrypointFragment on WellhubAiEntrypointProfilePerformance {\n  title {\n    key\n    __typename\n  }\n  sectionData {\n    isAvailable\n    __typename\n  }\n  __typename\n}\n\nfragment BadgesFragment on BadgesProfilePerformance {\n  title {\n    key\n    __typename\n  }\n  sectionData(badgesSettings: $badgesSettings) {\n    isAvailable\n    badges {\n      id\n      title\n      imageUrl\n      __typename\n    }\n    __typename\n  }\n  __typename\n}\n\nfragment CheckInBookingHistoryActionNavigationFragment on CheckInBookingHistoryActionNavigation {\n  label {\n    ...TextFragment\n    __typename\n  }\n  methodType\n  screenName\n  icon\n  enabled\n  trackData {\n    name\n    params\n    __typename\n  }\n  params\n  __typename\n}\n\nfragment CheckInBookingHistoryActionGoBackFragment on CheckInBookingHistoryActionGoBack {\n  label {\n    ...TextFragment\n    __typename\n  }\n  enabled\n  trackData {\n    name\n    params\n    __typename\n  }\n  __typename\n}\n\nfragment TextFragment on Text {\n  __typename\n  value {\n    __typename\n    ... on Translation {\n      __typename\n      namespace\n      key\n      params\n    }\n    ... on Label {\n      __typename\n      value\n    }\n  }\n  accessibilityHint {\n    __typename\n    ... on Translation {\n      __typename\n      namespace\n      key\n      params\n    }\n    ... on Label {\n      __typename\n      value\n    }\n  }\n  accessibilityLabel {\n    __typename\n    ... on Translation {\n      __typename\n      namespace\n      key\n      params\n    }\n    ... on Label {\n      __typename\n      value\n    }\n  }\n  accessibilityRole\n}\n\nfragment CheckInBookingHistoryItemFragment on CheckInBookingHistoryItem {\n  id\n  actionItem {\n    ...CheckInBookingHistoryActionGoBackFragment\n    ...CheckInBookingHistoryActionNavigationFragment\n    __typename\n  }\n  actionLink {\n    ...CheckInBookingHistoryActionGoBackFragment\n    ...CheckInBookingHistoryActionNavigationFragment\n    __typename\n  }\n  actionAvatar {\n    ...CheckInBookingHistoryActionNavigationFragment\n    __typename\n  }\n  attendance {\n    id\n    name {\n      ...TextFragment\n      __typename\n    }\n    icon\n    __typename\n  }\n  date {\n    icon\n    text {\n      ...TextFragment\n      __typename\n    }\n    __typename\n  }\n  product {\n    name {\n      ...TextFragment\n      __typename\n    }\n    __typename\n  }\n  partner {\n    name {\n      ...TextFragment\n      __typename\n    }\n    logo\n    __typename\n  }\n  tag {\n    label {\n      ...TextFragment\n      __typename\n    }\n    type\n    __typename\n  }\n  __typename\n}\n\nfragment CheckInBookingHistoryFragment on CheckInBookingHistoryProfilePerformance {\n  title {\n    key\n    params\n    namespace\n    __typename\n  }\n  sectionData(settings: $variables) {\n    items {\n      ...CheckInBookingHistoryItemFragment\n      __typename\n    }\n    __typename\n  }\n  __typename\n}"

PROFILE_VARS = {'settings': {'stats': True, 'streaks': False, 'schedule': True, 'badges': True, 'challenge_list': True, 'wellhub_ai_entrypoint': True, 'activated_apps': True, 'favorites': True, 'recent': True, 'checkin_booking_history': True}, 'variables': {'enable_recents': True, 'minutes_to_rate': 125, 'days_to_expiration': 7, 'recents': {'enable': True, 'minutes_to_rate': 125, 'days_to_expiration': 7, 'days_to_renew': 90}, 'stimulus': {'enable': True, 'minutes_to_rate': 125, 'days_to_expiration': 7, 'days_to_renew': 90}}, 'isFamilyMember': True, 'includeCheckInBookingHistory': True, 'maxChallengesSize': 3, 'challengesSettings': {'enableHighlightedChallenge': True, 'participatingMaxSize': 3, 'maxDaysDiffForChallengesEnded': 3, 'enableChallengeProfileSections': True, 'nextMovesMaxSize': 5, 'daysAfterChallengeStart': 4}, 'badgesSettings': {'enableBadgesCarousel': True, 'maxBadgesSize': 5}}
@dataclass
class WellhubBooking:
    attendance_id: str
    class_name: str
    studio_name: str   # e.g. "[solidcore] Chelsea, NY"
    dt: datetime       # full datetime in ET
    duration_mins: int = 50
    class_id: str = ""
    completed: bool = False   # True = past check-in, False = upcoming reserved


def _parse_time_str(time_str: str) -> tuple[int, int] | None:
    """Parse '12:00 PM' or '11:05 AM' → (hour24, minute). Returns None on failure."""
    import re
    m = re.match(r'(\d+):(\d+)\s*(AM|PM)', time_str.strip(), re.I)
    if not m:
        return None
    h, mi, ampm = int(m.group(1)), int(m.group(2)), m.group(3).upper()
    if ampm == "PM" and h != 12:
        h += 12
    elif ampm == "AM" and h == 12:
        h = 0
    return h, mi


def _label_value(node: dict) -> str:
    """Extract string from a TextFragment { value { ... on Label { value } } } node."""
    try:
        v = node["value"]
        if isinstance(v, dict):
            return v.get("value", "") or ""
        return str(v)
    except Exception:
        return ""


def get_upcoming_bookings() -> list[WellhubBooking]:
    """
    Return upcoming RESERVED bookings + recent Solidcore completed check-ins
    from the same profilePerformance call (used for quota calculation).
    """
    import calendar as cal_mod
    from zoneinfo import ZoneInfo

    ny  = ZoneInfo("America/New_York")
    now = datetime.now(tz=ny)
    abbr_map = {m.upper(): i for i, m in enumerate(cal_mod.month_abbr) if m}

    try:
        results = _gql([{
            "operationName": "profilePerformance",
            "variables": PROFILE_VARS,
            "query": PROFILE_SCHEDULE_QUERY,
        }])
        sections = (results[0].get("data", {})
                    .get("profilePerformance", {})
                    .get("sections", []))

        bookings: list[WellhubBooking] = []

        for section in sections:
            typename = section.get("__typename", "")

            # ── Upcoming reserved classes ──────────────────────────────────
            if typename == "ClassScheduleProfilePerformance":
                cards = (section.get("sectionData", {}) or {}).get("cards", []) or []
                for card in cards:
                    uid = card.get("uniqueAttendanceIdentifier")
                    if not uid or card.get("type") != "ReservedClassScheduleCard":
                        continue
                    details   = card.get("details") or {}
                    date_info = card.get("date") or {}
                    day       = int(date_info.get("day", 0))
                    month_str = date_info.get("month", "")
                    time_str  = details.get("time", "")
                    if not (day and month_str and time_str):
                        continue
                    month_num = abbr_map.get(month_str[:3].upper(), 0)
                    if not month_num:
                        continue
                    parsed = _parse_time_str(time_str)
                    if not parsed:
                        continue
                    h, mi = parsed
                    try:
                        candidate = datetime(now.year, month_num, day, tzinfo=ny)
                        if candidate.date() < now.date():
                            candidate = datetime(now.year + 1, month_num, day, tzinfo=ny)
                        dt = candidate.replace(hour=h, minute=mi, second=0, microsecond=0)
                    except Exception:
                        continue
                    params   = card.get("events", {}).get("clickstream", {}).get("params", {})
                    class_id = str(params.get("class_id", ""))
                    bookings.append(WellhubBooking(
                        attendance_id=uid,
                        class_name=details.get("name", ""),
                        studio_name=details.get("place", ""),
                        dt=dt,
                        class_id=class_id,
                        completed=False,
                    ))

            # ── Completed check-in history (for accurate weekly quota) ──────
            elif typename == "CheckInBookingHistoryProfilePerformance":
                items = (section.get("sectionData", {}) or {}).get("items", []) or []
                for item in items:
                    # Partner name tells us if it's solidcore
                    partner_node = (item.get("partner") or {}).get("name") or {}
                    partner_name = _label_value(partner_node)
                    if "[solidcore]" not in partner_name.lower():
                        continue  # skip non-Solidcore check-ins for quota

                    # Date text: "Apr 3 • 11:05 AM"
                    date_node = (item.get("date") or {}).get("text") or {}
                    date_text = _label_value(date_node)  # e.g. "Apr 3 • 11:05 AM"
                    if not date_text or "•" not in date_text:
                        continue

                    date_part, _, time_part = date_text.partition("•")
                    date_part = date_part.strip()   # "Apr 3"
                    time_part = time_part.strip()   # "11:05 AM"

                    # Parse "Apr 3"
                    import re
                    dm = re.match(r'([A-Za-z]+)\s+(\d+)', date_part)
                    if not dm:
                        continue
                    month_num = abbr_map.get(dm.group(1)[:3].upper(), 0)
                    day       = int(dm.group(2))
                    if not month_num or not day:
                        continue

                    parsed = _parse_time_str(time_part)
                    if not parsed:
                        continue
                    h, mi = parsed

                    # Infer year: assume recent past (within last 6 months)
                    try:
                        candidate = datetime(now.year, month_num, day, h, mi, tzinfo=ny)
                        if candidate > now:
                            candidate = datetime(now.year - 1, month_num, day, h, mi, tzinfo=ny)
                    except Exception:
                        continue

                    uid        = str(item.get("id", ""))
                    # product.name has the class name; attendance is a list so skip it
                    product_node = (item.get("product") or {}).get("name") or {}
                    class_name   = _label_value(product_node) or partner_name

                    bookings.append(WellhubBooking(
                        attendance_id=uid,
                        class_name=class_name,
                        studio_name=partner_name,
                        dt=candidate,
                        completed=True,
                    ))

        upcoming  = [b for b in bookings if not b.completed]
        completed = [b for b in bookings if b.completed]
        log.info("Found %d upcoming bookings + %d recent Solidcore check-ins",
                 len(upcoming), len(completed))
        return bookings

    except Exception as exc:
        log.warning("Could not fetch bookings: %s", exc)
        return []


def get_booked_dates() -> set[date]:
    """Return calendar dates (ET) with an upcoming RESERVED Wellhub booking."""
    bookings = get_upcoming_bookings()
    booked = {b.dt.date() for b in bookings if not b.completed}
    log.info("Already booked on %d date(s): %s", len(booked), sorted(booked))
    return booked


def _get_slot_details(slot_id: str) -> Optional[dict]:
    try:
        results = _gql([{
            "operationName": "classSlotDetailsQuery",
            "variables": {
                "input": {
                    "slotId": slot_id,
                    "uniqueAttendanceIdentifier": None,
                    "latitude":  LAT,
                    "longitude": LNG,
                }
            },
            "query": SLOT_DETAILS_QUERY,
        }])
        slot = results[0].get("data", {}).get("classSlotDetails", {}).get("slot", {})
        return {
            "classId":   slot.get("classId"),
            "partnerId": slot.get("partner", {}).get("id"),
        }
    except Exception as exc:
        log.error("Slot details error: %s", exc)
        return None
