"""Service for syncing external calendar subscriptions.

State is owned by SabreDAV: one ``SUBSCRIPTION`` principal per unique
source URL, its owner calendar, and sync state in ``propertystorage``.
Django only coordinates — it fetches the ICS, parses events, diffs
against the current SabreDAV contents, applies the batch via the
internal API, and posts the sync result.
"""

# pylint: disable=broad-exception-caught,import-outside-toplevel

import logging
import re
import secrets
import urllib.parse
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Optional

from django.core.cache import cache

import icalendar

from core.services.caldav_service import CalDAVHTTPClient
from core.services.url_validation import URLValidationError, fetch_ics

logger = logging.getLogger(__name__)

MAX_CONSECUTIVE_ERRORS = 3
SYNC_LOCK_TIMEOUT = 120  # seconds


@contextmanager
def _subscription_sync_lock(subscription_id: str):
    """Tokenized per-subscription sync lock.

    Yields True if the lock was acquired, False if another worker already
    holds it. Only the worker that wrote the lock token deletes it, so a
    finally block running after the TTL expired cannot evict a second
    worker's lease.
    """
    lock_key = f"sync_lock:sub:{subscription_id}"
    token = secrets.token_hex(16)
    acquired = cache.add(lock_key, token, timeout=SYNC_LOCK_TIMEOUT)
    try:
        yield acquired
    finally:
        if acquired and cache.get(lock_key) == token:
            cache.delete(lock_key)


# Reject UIDs containing path traversal characters or null bytes.
# All other characters are percent-encoded when used in CalDAV paths.
UNSAFE_UID_RE = re.compile(r"[/\\\x00]|\.\.")


@dataclass
class SyncResult:
    """Result of a subscription sync operation."""

    created: int = 0
    updated: int = 0
    deleted: int = 0
    unchanged: int = 0
    errors: list[str] = field(default_factory=list)


class _SystemUser:
    """Minimal stand-in for the sync worker.

    The internal API dispatcher short-circuits all ``internal-api/``
    paths before the regular CalDAV auth runs, so it never reads
    ``user.email`` / ``user.organization_id`` from the request. But
    ``CalDAVHTTPClient.build_base_headers`` asserts both are set before
    attaching them. We pass a synthetic object carrying placeholder
    values so the header-building contract is satisfied — the CalDAV
    side ignores them for internal API calls.
    """

    def __init__(self):
        self.email = "sync-worker@subscriptions.internal"
        self.organization_id = "subscriptions"
        self.organization = None


class SubscriptionSyncService:
    """Syncs shared subscription calendars via SabreDAV's internal API."""

    def __init__(self):
        self._http = CalDAVHTTPClient()
        self._system_user = _SystemUser()

    # ------------------------------------------------------------------
    # Entry points
    # ------------------------------------------------------------------

    def sync_subscription(self, subscription_id: str) -> bool:
        """Sync a single subscription. Returns True on success, False on error."""
        with _subscription_sync_lock(subscription_id) as acquired:
            if not acquired:
                logger.info("Sync already running for %s, skipping", subscription_id)
                return True
            return self._do_sync(subscription_id)

    def apply_initial_sync(  # noqa: PLR0913  # pylint: disable=too-many-arguments
        self,
        user,
        *,
        subscription_id: str,
        caldav_path: str,
        ics_data: bytes,
        etag: str,
        last_modified: str,
    ) -> None:
        """Synchronous initial sync right after subscribe, reusing the
        ICS data fetched during URL validation.

        ``user`` is unused for SabreDAV writes (the internal API path
        takes the subscription_id directly) but kept in the signature
        for symmetry with the previous API.
        """
        del user, caldav_path  # unused — kept for call-site compatibility

        with _subscription_sync_lock(subscription_id):
            try:
                result = self._sync_events(subscription_id, ics_data)
            except Exception as exc:  # noqa: BLE001
                self._post_sync_result(
                    subscription_id,
                    status="error",
                    error_message=str(exc)[:500],
                    error_count=1,
                )
                return

            self._post_sync_result(
                subscription_id,
                status="ok",
                etag=etag,
                last_modified=last_modified,
                error_count=0,
                error_message=(
                    f"{len(result.errors)} event error(s)" if result.errors else ""
                ),
            )

    # ------------------------------------------------------------------
    # Core sync loop
    # ------------------------------------------------------------------

    def _do_sync(self, subscription_id: str) -> bool:
        """Inner sync logic (lock already held)."""
        info = self._fetch_subscription_info(subscription_id)
        if info is None:
            logger.warning("Subscription %s not found", subscription_id)
            return False

        source_url = info.get("source_url", "")
        if not source_url:
            logger.warning("Subscription %s has no source_url", subscription_id)
            return False

        try:
            status_code, ics_data, new_etag, new_last_modified = fetch_ics(
                source_url,
                etag=info.get("etag", ""),
                last_modified=info.get("last_modified", ""),
            )
        except URLValidationError as exc:
            return self._handle_error(subscription_id, info, str(exc))

        if status_code == 304:
            self._post_sync_result(
                subscription_id,
                status="ok",
                etag=info.get("etag", ""),
                last_modified=info.get("last_modified", ""),
                error_count=0,
                error_message="",
            )
            return True

        try:
            result = self._sync_events(subscription_id, ics_data)
        except Exception as exc:
            logger.exception("Sync events failed for %s", subscription_id)
            return self._handle_error(subscription_id, info, f"Sync failed: {exc}")

        self._post_sync_result(
            subscription_id,
            status="ok",
            etag=new_etag,
            last_modified=new_last_modified,
            error_count=0,
            error_message=(
                f"{len(result.errors)} event error(s)" if result.errors else ""
            ),
        )
        logger.info(
            "Synced %s: +%d ~%d -%d =%d errors=%d",
            subscription_id,
            result.created,
            result.updated,
            result.deleted,
            result.unchanged,
            len(result.errors),
        )
        return True

    def _handle_error(self, subscription_id: str, info: dict, error_msg: str) -> bool:
        """Increment error count and auto-stop after 3 strikes."""
        error_count = int(info.get("error_count", 0)) + 1
        new_status = "stopped" if error_count >= MAX_CONSECUTIVE_ERRORS else "error"
        self._post_sync_result(
            subscription_id,
            status=new_status,
            error_message=error_msg[:500],
            error_count=error_count,
        )
        if new_status == "stopped":
            logger.warning(
                "Subscription %s auto-stopped after %d errors",
                subscription_id,
                error_count,
            )
        return False

    # ------------------------------------------------------------------
    # Internal API wrappers
    # ------------------------------------------------------------------

    def _fetch_subscription_info(self, subscription_id: str) -> Optional[dict]:
        resp = self._http.internal_request(
            "GET",
            self._system_user,
            f"internal-api/subscriptions/{subscription_id}/",
        )
        if resp.status_code == 404:
            return None
        if resp.status_code != 200:
            raise RuntimeError(
                f"Internal API returned {resp.status_code} for subscription info"
            )
        return resp.json()

    def _post_sync_result(  # noqa: PLR0913  # pylint: disable=too-many-arguments
        self,
        subscription_id: str,
        *,
        status: str,
        etag: Optional[str] = None,
        last_modified: Optional[str] = None,
        error_count: Optional[int] = None,
        error_message: Optional[str] = None,
    ) -> None:
        payload: dict = {"status": status}
        if etag is not None:
            payload["etag"] = etag
        if last_modified is not None:
            payload["last_modified"] = last_modified
        if error_count is not None:
            payload["error_count"] = error_count
        if error_message is not None:
            payload["error_message"] = error_message

        try:
            self._http.internal_request(
                "POST",
                self._system_user,
                f"internal-api/subscriptions/{subscription_id}/sync-result/",
                json=payload,
            )
        except Exception:
            logger.exception("Failed to post sync result for %s", subscription_id)

    def _fetch_existing_events(self, subscription_id: str) -> dict[str, dict]:
        """Return ``{uid: {"uri", "data"}}`` for current events."""
        resp = self._http.internal_request(
            "GET",
            self._system_user,
            f"internal-api/subscriptions/{subscription_id}/events/",
        )
        if resp.status_code != 200:
            raise RuntimeError(
                f"list events returned {resp.status_code}: {resp.text[:200]}"
            )
        data = resp.json()
        existing: dict[str, dict] = {}
        for event in data.get("events", []):
            uid = event.get("uid") or ""
            if not uid:
                continue
            existing[uid] = {
                "uri": event.get("uri", ""),
                "data": event.get("ics", ""),
            }
        return existing

    def _apply_events_batch(
        self,
        subscription_id: str,
        upserts: list[dict],
        deletes: list[str],
    ) -> dict:
        if not upserts and not deletes:
            return {"created": 0, "updated": 0, "deleted": 0, "errors": []}
        resp = self._http.internal_request(
            "POST",
            self._system_user,
            f"internal-api/subscriptions/{subscription_id}/events-batch/",
            json={"upsert": upserts, "delete": deletes},
        )
        if resp.status_code != 200:
            raise RuntimeError(
                f"events-batch returned {resp.status_code}: {resp.text[:200]}"
            )
        return resp.json()

    # ------------------------------------------------------------------
    # Diff + batch application
    # ------------------------------------------------------------------

    def _sync_events(self, subscription_id: str, ics_data: bytes) -> SyncResult:
        """Diff-sync events from ICS data into the subscription calendar."""
        result = SyncResult()

        new_events = self._parse_ics_events(ics_data)
        new_uids = set(new_events.keys())

        existing = self._fetch_existing_events(subscription_id)
        existing_uids = set(existing.keys())

        # Guard against empty source wiping all events.
        if not new_uids and existing_uids:
            raise ValueError(
                f"Source returned 0 events but calendar has {len(existing_uids)}"
                " — refusing to delete all events (possible source error)"
            )

        to_create = new_uids - existing_uids
        to_maybe_update = new_uids & existing_uids
        to_delete = existing_uids - new_uids

        upserts: list[dict] = []
        for uid in to_create:
            if UNSAFE_UID_RE.search(uid):
                result.errors.append(f"Skipped {uid!r}: unsafe UID characters")
                continue
            safe_uid = urllib.parse.quote(uid, safe="@._-")
            upserts.append(
                {
                    "uid": uid,
                    "uri": f"{safe_uid}.ics",
                    "ics": new_events[uid],
                }
            )

        for uid in to_maybe_update:
            if not self._events_differ(existing[uid]["data"], new_events[uid]):
                result.unchanged += 1
                continue
            upserts.append(
                {
                    "uid": uid,
                    "uri": existing[uid]["uri"],
                    "ics": new_events[uid],
                }
            )

        delete_uris = [existing[uid]["uri"] for uid in to_delete]

        batch = self._apply_events_batch(subscription_id, upserts, delete_uris)
        result.created = int(batch.get("created", 0))
        result.updated = int(batch.get("updated", 0))
        result.deleted = int(batch.get("deleted", 0))
        result.errors.extend(batch.get("errors", []))

        return result

    # ------------------------------------------------------------------
    # ICS parsing / diffing — unchanged from the previous implementation.
    # ------------------------------------------------------------------

    @staticmethod
    def _normalize_ics_encoding(ics_data: bytes) -> bytes:
        """Ensure ICS data is valid UTF-8, falling back to latin-1."""
        try:
            ics_data.decode("utf-8")
            return ics_data
        except UnicodeDecodeError:
            logger.warning("ICS data is not valid UTF-8, trying latin-1 fallback")
            return ics_data.decode("latin-1").encode("utf-8")

    @staticmethod
    def _parse_ics_events(ics_data: bytes) -> dict[str, str]:
        """Parse ICS data and return a dict of UID -> complete VCALENDAR string.

        Each event is wrapped in its own VCALENDAR for individual PUT.
        Recurring-event override instances share a UID and are kept
        grouped under that UID.
        """
        ics_data = SubscriptionSyncService._normalize_ics_encoding(ics_data)
        cal = icalendar.Calendar.from_ical(ics_data)
        events: dict[str, str] = {}

        timezones = [
            component for component in cal.walk() if component.name == "VTIMEZONE"
        ]

        grouped: dict[str, list] = {}
        for component in cal.walk("VEVENT"):
            uid = str(component.get("uid", ""))
            if not uid:
                continue
            SubscriptionSyncService._cap_infinite_rrule(component)
            grouped.setdefault(uid, []).append(component)

        for uid, components in grouped.items():
            single_cal = icalendar.Calendar()
            single_cal.add("prodid", cal.get("prodid", "-//La Suite//Calendars//FR"))
            single_cal.add("version", "2.0")
            for tz in timezones:
                single_cal.add_component(tz)
            for component in components:
                single_cal.add_component(component)
            events[uid] = single_cal.to_ical().decode("utf-8")

        return events

    # SabreDAV limit for recurring event instances
    MAX_RRULE_INSTANCES = 3500

    @staticmethod
    def _cap_infinite_rrule(component):
        """Add COUNT to RRULEs with no COUNT or UNTIL.

        SabreDAV rejects recurring events that generate more than 3500
        instances. We cap at ``MAX_RRULE_INSTANCES - 1`` to stay clear
        of the limit.
        """
        rrule = component.get("rrule")
        if not rrule:
            return
        has_count = "COUNT" in rrule
        has_until = "UNTIL" in rrule
        if has_count or has_until:
            return
        try:
            rrule["COUNT"] = [SubscriptionSyncService.MAX_RRULE_INSTANCES - 1]
            logger.info(
                "Capped infinite RRULE for event %s with COUNT=%d",
                component.get("uid", "?"),
                SubscriptionSyncService.MAX_RRULE_INSTANCES - 1,
            )
        except Exception:  # noqa: BLE001
            logger.warning(
                "Failed to cap RRULE for event %s",
                component.get("uid", "?"),
            )

    VOLATILE_PROPS = {"DTSTAMP", "LAST-MODIFIED", "SEQUENCE", "CREATED"}

    @staticmethod
    def _serialize_property(value) -> tuple:
        """Serialize a property value with its parameters for comparison."""
        params = getattr(value, "params", None) or {}
        sorted_params = tuple(sorted((k, str(v)) for k, v in params.items()))
        try:
            serialized = value.to_ical()
            if isinstance(serialized, bytes):
                serialized = serialized.decode("utf-8", errors="replace")
        except Exception:  # noqa: BLE001
            serialized = str(value)
        return serialized, sorted_params

    @staticmethod
    def _serialize_subcomponent(subcomponent) -> tuple:
        name = getattr(subcomponent, "name", "")
        props = tuple(
            sorted(
                (k, SubscriptionSyncService._serialize_property(v))
                for k, v in subcomponent.items()
                if k not in SubscriptionSyncService.VOLATILE_PROPS
            )
        )
        return (name, props)

    @staticmethod
    def _event_props(component) -> tuple:
        props = tuple(
            sorted(
                (k, SubscriptionSyncService._serialize_property(v))
                for k, v in component.items()
                if k not in SubscriptionSyncService.VOLATILE_PROPS
            )
        )
        subcomponents = tuple(
            sorted(
                SubscriptionSyncService._serialize_subcomponent(sub)
                for sub in component.subcomponents
            )
        )
        return (props, subcomponents)

    @staticmethod
    def _events_differ(existing_data: str, new_data: str) -> bool:
        """Whether two VCALENDAR strings differ in anything that matters."""
        try:
            existing_cal = icalendar.Calendar.from_ical(existing_data)
            new_cal = icalendar.Calendar.from_ical(new_data)

            existing_events = list(existing_cal.walk("VEVENT"))
            new_events = list(new_cal.walk("VEVENT"))

            if len(existing_events) != len(new_events):
                return True

            def _keyed(events):
                return {
                    str(
                        ev.get("RECURRENCE-ID", "")
                    ): SubscriptionSyncService._event_props(ev)
                    for ev in events
                }

            return _keyed(existing_events) != _keyed(new_events)
        except Exception:  # noqa: BLE001
            return True
