"""Service for syncing external calendar subscriptions.

Implements diff-based sync: compares UIDs from the external ICS with
existing events in the SabreDAV calendar, then creates/updates/deletes
as needed.
"""

# pylint: disable=broad-exception-caught,import-outside-toplevel,protected-access

import logging
import re
import secrets
import urllib.parse
from contextlib import contextmanager
from dataclasses import dataclass, field

from django.core.cache import cache
from django.utils import timezone

import icalendar

from core.services.caldav_service import CalDAVClient, CalDAVHTTPClient
from core.services.url_validation import URLValidationError, fetch_ics

logger = logging.getLogger(__name__)

MAX_CONSECUTIVE_ERRORS = 3
SYNC_LOCK_TIMEOUT = 120  # seconds


@contextmanager
def _channel_sync_lock(channel_id: str):
    """Tokenized per-channel sync lock.

    Yields True if the lock was acquired, False if another worker already
    holds it. Only the worker that wrote the lock token deletes it, so a
    finally block running after the TTL expired cannot evict a second
    worker's lease.
    """
    lock_key = f"sync_lock:{channel_id}"
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


@dataclass
class _SyncContext:
    """Per-sync state shared between the create/update/delete helpers."""

    user: object
    caldav_path: str
    new_events: dict[str, str]
    existing: dict[str, dict]


class SubscriptionSyncService:
    """Syncs external ICS subscriptions into SabreDAV calendars."""

    def __init__(self):
        self._http = CalDAVHTTPClient()
        self._caldav = CalDAVClient()

    def purge_events(self, user, caldav_path: str) -> int:
        """Delete all events from a SabreDAV calendar.

        Returns the number of deleted events.
        """
        client = self._http.get_dav_client(user)
        calendar_url = self._caldav._calendar_url(caldav_path)  # noqa: SLF001
        calendar = client.calendar(url=calendar_url)

        deleted = 0
        for event in calendar.events():
            uid = str(event.icalendar_component.get("uid", ""))
            if uid:
                try:
                    self._caldav.delete_event(user, caldav_path, uid)
                    deleted += 1
                except Exception:  # noqa: BLE001
                    logger.warning("Failed to delete event %s during purge", uid)
        return deleted

    def sync_channel(self, channel_id: str) -> bool:
        """Sync a single subscription channel.

        Acquires a Redis lock to prevent concurrent syncs on the same
        channel. Handles 304/200/error cases and updates channel
        settings accordingly.

        Returns True if sync completed (success or 304), False on error.
        """
        with _channel_sync_lock(channel_id) as acquired:
            if not acquired:
                logger.info("Sync already running for channel %s, skipping", channel_id)
                return True
            return self._do_sync(channel_id)

    def _do_sync(self, channel_id: str) -> bool:
        """Inner sync logic (lock already held)."""
        # Local import avoids a circular dependency with core.models.
        from core.models import Channel  # noqa: PLC0415

        try:
            channel = Channel.objects.get(
                pk=channel_id, type="ical-subscription", is_active=True
            )
        except Channel.DoesNotExist:
            logger.warning("Channel %s not found or inactive", channel_id)
            return False

        source_url = channel.settings.get("source_url", "")
        etag = channel.settings.get("etag", "")
        last_modified = channel.settings.get("last_modified", "")

        # Fetch ICS
        try:
            status_code, ics_data, new_etag, new_last_modified = fetch_ics(
                source_url, etag=etag, last_modified=last_modified
            )
        except URLValidationError as exc:
            return self._handle_error(channel, str(exc))

        now = timezone.now().isoformat()

        if status_code == 304:
            channel.settings["last_sync_at"] = now
            channel.settings["last_sync_status"] = "ok"
            channel.settings["last_sync_error"] = ""
            channel.settings["error_count"] = 0
            return self._save_channel(channel)

        # 200 — diff sync
        try:
            result = self._sync_events(channel.user, channel.caldav_path, ics_data)
        except Exception as exc:
            logger.exception("Sync events failed for channel %s", channel_id)
            return self._handle_error(channel, f"Sync failed: {exc}")

        # Success — update channel settings
        channel.settings["etag"] = new_etag
        channel.settings["last_modified"] = new_last_modified
        channel.settings["last_sync_at"] = now
        if result.errors:
            channel.settings["last_sync_status"] = "ok"
            channel.settings["last_sync_error"] = f"{len(result.errors)} event error(s)"
        else:
            channel.settings["last_sync_status"] = "ok"
            channel.settings["last_sync_error"] = ""
        channel.settings["error_count"] = 0
        if not self._save_channel(channel):
            return False

        logger.info(
            "Synced channel %s: +%d ~%d -%d =%d errors=%d",
            channel_id,
            result.created,
            result.updated,
            result.deleted,
            result.unchanged,
            len(result.errors),
        )
        return True

    def _handle_error(self, channel, error_msg: str) -> bool:
        """Handle a sync error: increment count, auto-stop after 3."""
        error_count = channel.settings.get("error_count", 0) + 1
        channel.settings["error_count"] = error_count
        channel.settings["last_sync_status"] = "error"
        channel.settings["last_sync_error"] = error_msg[:500]
        channel.settings["last_sync_at"] = timezone.now().isoformat()

        if error_count >= MAX_CONSECUTIVE_ERRORS:
            channel.is_active = False
            logger.warning(
                "Channel %s auto-stopped after %d consecutive errors",
                channel.pk,
                error_count,
            )

        self._save_channel(channel)
        return False

    @staticmethod
    def _save_channel(channel) -> bool:
        """Save channel settings, handling deletion race condition."""
        # Local import avoids a circular dependency with core.models.
        from core.models import Channel  # noqa: PLC0415

        fields = ["settings", "updated_at"]
        if not channel.is_active:
            fields.append("is_active")
        try:
            # Re-check the channel still exists before saving
            if not Channel.objects.filter(pk=channel.pk).exists():
                logger.info(
                    "Channel %s was deleted during sync, skipping save",
                    channel.pk,
                )
                return False
            # auto_now=True is not honoured with update_fields, set manually
            channel.updated_at = timezone.now()
            channel.save(update_fields=fields)
            return True
        except Exception:  # noqa: BLE001
            logger.warning(
                "Failed to save channel %s (likely deleted during sync)",
                channel.pk,
            )
            return False

    def sync_events(
        self,
        user,
        caldav_path: str,
        ics_data: bytes,
        channel_id: str | None = None,
    ) -> SyncResult:
        """Public entry point for syncing ICS data into a SabreDAV calendar.

        When ``channel_id`` is provided, acquires the same per-channel
        lock used by :meth:`sync_channel` so request-thread syncs cannot
        interleave SabreDAV writes with scheduler-driven syncs on the
        same calendar.
        """
        if channel_id is None:
            return self._sync_events(user, caldav_path, ics_data)

        with _channel_sync_lock(channel_id) as acquired:
            if not acquired:
                # Another worker is already syncing this channel — skip
                # to avoid interleaving. The caller can retry later.
                logger.info(
                    "Sync already running for channel %s, skipping sync_events",
                    channel_id,
                )
                return SyncResult()
            return self._sync_events(user, caldav_path, ics_data)

    def _sync_events(self, user, caldav_path: str, ics_data: bytes) -> SyncResult:
        """Diff-sync events from ICS data into a SabreDAV calendar."""
        result = SyncResult()

        new_events = self._parse_ics_events(ics_data)
        new_uids = set(new_events.keys())

        existing = self._fetch_existing_events(user, caldav_path)
        existing_uids = set(existing.keys())

        # Guard against empty source wiping all events (server error / maintenance)
        if not new_uids and existing_uids:
            raise ValueError(
                f"Source returned 0 events but calendar has {len(existing_uids)}"
                " — refusing to delete all events (possible source error)"
            )

        ctx = _SyncContext(
            user=user,
            caldav_path=caldav_path,
            new_events=new_events,
            existing=existing,
        )
        self._create_events(ctx, new_uids - existing_uids, result)
        self._update_events(ctx, new_uids & existing_uids, result)
        self._delete_events(ctx, existing_uids - new_uids, result)

        return result

    def _fetch_existing_events(self, user, caldav_path: str) -> dict[str, dict]:
        """Return ``{uid: {"href", "data"}}`` for events currently in SabreDAV."""
        client = self._http.get_dav_client(user)
        calendar_url = self._caldav._calendar_url(caldav_path)  # noqa: SLF001
        calendar = client.calendar(url=calendar_url)

        existing: dict[str, dict] = {}
        try:
            for event in calendar.events():
                uid = str(event.icalendar_component.get("uid", ""))
                if uid:
                    existing[uid] = {
                        "href": str(event.url.path),
                        "data": event.data,
                    }
        except Exception:
            logger.exception("Failed to list existing events in %s", caldav_path)
            raise
        return existing

    def _create_events(
        self,
        ctx: _SyncContext,
        uids_to_create: set[str],
        result: SyncResult,
    ) -> None:
        for uid in uids_to_create:
            if UNSAFE_UID_RE.search(uid):
                result.errors.append(f"Skipped {uid!r}: unsafe UID characters")
                continue
            safe_uid = urllib.parse.quote(uid, safe="@._-")
            try:
                success = self._http.put_event(
                    ctx.user,
                    f"{ctx.caldav_path}{safe_uid}.ics",
                    ctx.new_events[uid],
                )
            except Exception as exc:  # noqa: BLE001
                result.errors.append(f"Create {uid}: {exc}")
                continue
            if success:
                result.created += 1
            else:
                result.errors.append(f"Create {uid}: PUT rejected by server")

    def _update_events(
        self,
        ctx: _SyncContext,
        uids_to_check: set[str],
        result: SyncResult,
    ) -> None:
        for uid in uids_to_check:
            if not self._events_differ(ctx.existing[uid]["data"], ctx.new_events[uid]):
                result.unchanged += 1
                continue
            try:
                success = self._http.put_event(
                    ctx.user,
                    ctx.existing[uid]["href"],
                    ctx.new_events[uid],
                )
            except Exception as exc:  # noqa: BLE001
                result.errors.append(f"Update {uid}: {exc}")
                continue
            if success:
                result.updated += 1
            else:
                result.errors.append(f"Update {uid}: PUT rejected by server")

    def _delete_events(
        self,
        ctx: _SyncContext,
        uids_to_delete: set[str],
        result: SyncResult,
    ) -> None:
        for uid in uids_to_delete:
            try:
                self._caldav.delete_event(ctx.user, ctx.caldav_path, uid)
                result.deleted += 1
            except ValueError:
                # Event already deleted externally — desired state achieved
                result.deleted += 1
            except Exception as exc:  # noqa: BLE001
                result.errors.append(f"Delete {uid}: {exc}")

    @staticmethod
    def _normalize_ics_encoding(ics_data: bytes) -> bytes:
        """Ensure ICS data is valid UTF-8.

        Some legacy ICS producers use Latin-1 or Windows-1252 encoding.
        Re-encode to UTF-8 if needed.
        """
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
        """
        ics_data = SubscriptionSyncService._normalize_ics_encoding(ics_data)
        cal = icalendar.Calendar.from_ical(ics_data)
        events = {}

        # Extract VTIMEZONE components to include with each event
        timezones = []
        for component in cal.walk():
            if component.name == "VTIMEZONE":
                timezones.append(component)

        # Group VEVENTs by UID (recurring events may have override instances
        # sharing the same UID, distinguished by RECURRENCE-ID)
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
        instances (MaxInstancesExceededException). We add COUNT=3499
        to stay safely under the limit.
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

    # Properties that change on every export without meaningful data change
    VOLATILE_PROPS = {"DTSTAMP", "LAST-MODIFIED", "SEQUENCE", "CREATED"}

    @staticmethod
    def _serialize_property(value) -> tuple:
        """Serialize a property value with its parameters for comparison.

        Returns a tuple ``(serialized_value, sorted_params)`` so two
        properties compare equal iff their value *and* parameter set
        (e.g. ``ATTENDEE;PARTSTAT=ACCEPTED``) are identical.
        """
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
        """Serialize a subcomponent (e.g. VALARM) for comparison."""
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
        """Extract comparable representation of a VEVENT.

        Includes property parameters (so ``ATTENDEE;PARTSTAT=ACCEPTED``
        differs from ``ATTENDEE;PARTSTAT=DECLINED``) and subcomponents
        like ``VALARM`` so alarm edits trigger an update.
        """
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
        """Compare two VCALENDAR strings to detect meaningful changes.

        Compares the VEVENT components property-by-property, ignoring
        volatile properties (DTSTAMP, LAST-MODIFIED, SEQUENCE, CREATED)
        that change on every export without real data change.
        """
        try:
            existing_cal = icalendar.Calendar.from_ical(existing_data)
            new_cal = icalendar.Calendar.from_ical(new_data)

            existing_events = list(existing_cal.walk("VEVENT"))
            new_events = list(new_cal.walk("VEVENT"))

            if len(existing_events) != len(new_events):
                return True

            # Group by RECURRENCE-ID to handle reordered override instances
            def _keyed(events):
                return {
                    str(
                        ev.get("RECURRENCE-ID", "")
                    ): SubscriptionSyncService._event_props(ev)
                    for ev in events
                }

            return _keyed(existing_events) != _keyed(new_events)
        except Exception:  # noqa: BLE001
            # If we can't parse, assume different to be safe
            return True
