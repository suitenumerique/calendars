"""Tests for subscription sync service."""

# pylint: disable=missing-class-docstring,missing-function-docstring,protected-access

from unittest.mock import MagicMock, patch

import pytest

from core.factories import UserFactory
from core.models import Channel
from core.services.subscription_sync_service import SubscriptionSyncService
from core.services.url_validation import URLValidationError

VALID_ICS = (
    b"BEGIN:VCALENDAR\r\nVERSION:2.0\r\nPRODID:-//Test//Test//EN\r\n"
    b"BEGIN:VEVENT\r\nUID:event-1@test\r\nDTSTART:20260101T100000Z\r\n"
    b"DTEND:20260101T110000Z\r\nSUMMARY:Test Event\r\n"
    b"END:VEVENT\r\nEND:VCALENDAR"
)

VALID_ICS_TWO_EVENTS = (
    b"BEGIN:VCALENDAR\r\nVERSION:2.0\r\nPRODID:-//Test//Test//EN\r\n"
    b"BEGIN:VEVENT\r\nUID:event-1@test\r\nDTSTART:20260101T100000Z\r\n"
    b"DTEND:20260101T110000Z\r\nSUMMARY:Test Event\r\n"
    b"END:VEVENT\r\n"
    b"BEGIN:VEVENT\r\nUID:event-2@test\r\nDTSTART:20260102T100000Z\r\n"
    b"DTEND:20260102T110000Z\r\nSUMMARY:Test Event 2\r\n"
    b"END:VEVENT\r\nEND:VCALENDAR"
)


class TestParseIcsEvents:
    def test_parses_single_event(self):
        service = SubscriptionSyncService()
        events = service._parse_ics_events(VALID_ICS)
        assert "event-1@test" in events
        assert "BEGIN:VCALENDAR" in events["event-1@test"]
        assert "BEGIN:VEVENT" in events["event-1@test"]

    def test_parses_multiple_events(self):
        service = SubscriptionSyncService()
        events = service._parse_ics_events(VALID_ICS_TWO_EVENTS)
        assert len(events) == 2
        assert "event-1@test" in events
        assert "event-2@test" in events


class TestEventsDiffer:
    def test_identical_events(self):
        service = SubscriptionSyncService()
        cal = (
            "BEGIN:VCALENDAR\r\nVERSION:2.0\r\n"
            "BEGIN:VEVENT\r\nUID:test@test\r\nSUMMARY:Test\r\n"
            "END:VEVENT\r\nEND:VCALENDAR"
        )
        assert not service._events_differ(cal, cal)

    def test_different_summary(self):
        service = SubscriptionSyncService()
        old = (
            "BEGIN:VCALENDAR\r\nVERSION:2.0\r\n"
            "BEGIN:VEVENT\r\nUID:test@test\r\nSUMMARY:Old\r\n"
            "END:VEVENT\r\nEND:VCALENDAR"
        )
        new = (
            "BEGIN:VCALENDAR\r\nVERSION:2.0\r\n"
            "BEGIN:VEVENT\r\nUID:test@test\r\nSUMMARY:New\r\n"
            "END:VEVENT\r\nEND:VCALENDAR"
        )
        assert service._events_differ(old, new)


@pytest.mark.django_db
class TestSyncChannel:
    @patch("core.services.subscription_sync_service.fetch_ics")
    @patch("core.services.subscription_sync_service.cache")
    def test_304_skips_sync(self, mock_cache, mock_fetch):
        """304 Not Modified should update last_sync_at without touching events."""
        mock_cache.add.return_value = True  # Lock acquired
        mock_fetch.return_value = (304, None, '"old-etag"', "old-date")

        user = UserFactory()
        channel = Channel.objects.create(
            name="Test Sub",
            type="ical-subscription",
            user=user,
            caldav_path="/calendars/users/test@test.com/uuid/",
            settings={
                "source_url": "https://example.com/cal.ics",
                "sync_interval": 300,
                "last_sync_status": "ok",
                "error_count": 0,
                "etag": '"old-etag"',
                "last_modified": "old-date",
            },
        )

        service = SubscriptionSyncService()
        result = service.sync_channel(str(channel.pk))

        assert result is True
        channel.refresh_from_db()
        assert channel.settings["last_sync_status"] == "ok"
        assert channel.settings["last_sync_at"] is not None

    @patch("core.services.subscription_sync_service.fetch_ics")
    @patch("core.services.subscription_sync_service.cache")
    def test_error_increments_count(self, mock_cache, mock_fetch):
        """Fetch error should increment error_count."""
        mock_cache.add.return_value = True
        mock_fetch.side_effect = URLValidationError("timeout")

        user = UserFactory()
        channel = Channel.objects.create(
            name="Test Sub",
            type="ical-subscription",
            user=user,
            caldav_path="/calendars/users/test@test.com/uuid/",
            settings={
                "source_url": "https://example.com/cal.ics",
                "sync_interval": 300,
                "last_sync_status": "ok",
                "error_count": 0,
                "etag": "",
                "last_modified": "",
            },
        )

        service = SubscriptionSyncService()
        result = service.sync_channel(str(channel.pk))

        assert result is False
        channel.refresh_from_db()
        assert channel.settings["error_count"] == 1
        assert channel.settings["last_sync_status"] == "error"
        assert "timeout" in channel.settings["last_sync_error"]
        assert channel.is_active is True  # not stopped yet

    @patch("core.services.subscription_sync_service.fetch_ics")
    @patch("core.services.subscription_sync_service.cache")
    def test_three_strikes_auto_stop(self, mock_cache, mock_fetch):
        """After 3 consecutive errors, channel should be deactivated."""
        mock_cache.add.return_value = True
        mock_fetch.side_effect = URLValidationError("server error")

        user = UserFactory()
        channel = Channel.objects.create(
            name="Test Sub",
            type="ical-subscription",
            user=user,
            caldav_path="/calendars/users/test@test.com/uuid/",
            settings={
                "source_url": "https://example.com/cal.ics",
                "sync_interval": 300,
                "last_sync_status": "error",
                "error_count": 2,  # Already 2 errors
                "etag": "",
                "last_modified": "",
            },
        )

        service = SubscriptionSyncService()
        result = service.sync_channel(str(channel.pk))

        assert result is False
        channel.refresh_from_db()
        assert channel.settings["error_count"] == 3
        assert channel.is_active is False  # auto-stopped

    @patch("core.services.subscription_sync_service.cache")
    def test_lock_prevents_overlap(self, mock_cache):
        """If lock is already held, sync should skip."""
        mock_cache.add.return_value = False  # Lock NOT acquired

        user = UserFactory()
        channel = Channel.objects.create(
            name="Test Sub",
            type="ical-subscription",
            user=user,
            caldav_path="/calendars/users/test@test.com/uuid/",
            settings={
                "source_url": "https://example.com/cal.ics",
                "sync_interval": 300,
                "last_sync_status": "ok",
                "error_count": 0,
                "etag": "",
                "last_modified": "",
            },
        )

        service = SubscriptionSyncService()
        result = service.sync_channel(str(channel.pk))

        assert result is True  # Skipped, not an error

    @patch("core.services.subscription_sync_service.cache")
    def test_inactive_channel_skipped(self, mock_cache):
        """Inactive channel should not be synced."""
        mock_cache.add.return_value = True

        user = UserFactory()
        channel = Channel.objects.create(
            name="Test Sub",
            type="ical-subscription",
            user=user,
            is_active=False,
            caldav_path="/calendars/users/test@test.com/uuid/",
            settings={
                "source_url": "https://example.com/cal.ics",
                "sync_interval": 300,
                "last_sync_status": "error",
                "error_count": 3,
                "etag": "",
                "last_modified": "",
            },
        )

        service = SubscriptionSyncService()
        result = service.sync_channel(str(channel.pk))

        assert result is False

    @patch("core.services.subscription_sync_service.fetch_ics")
    @patch("core.services.subscription_sync_service.cache")
    def test_sync_survives_channel_deletion(self, mock_cache, mock_fetch):
        """If channel is deleted during sync, save should not crash."""
        mock_cache.add.return_value = True

        user = UserFactory()
        channel = Channel.objects.create(
            name="Test Sub",
            type="ical-subscription",
            user=user,
            caldav_path="/calendars/users/test@test.com/uuid/",
            settings={
                "source_url": "https://example.com/cal.ics",
                "sync_interval": 300,
                "last_sync_status": "ok",
                "error_count": 0,
                "etag": '"etag"',
                "last_modified": "date",
            },
        )

        service = SubscriptionSyncService()
        channel_id = str(channel.pk)

        # Delete the row *during* sync, after the channel has already
        # been loaded into memory — this exercises the real race that
        # _save_channel's existence check is meant to handle, unlike a
        # pre-sync delete which only hits the "not found" branch.
        def delete_during_fetch(*_args, **_kwargs):
            Channel.objects.filter(pk=channel.pk).delete()
            return (304, None, '"etag"', "date")

        mock_fetch.side_effect = delete_during_fetch

        result = service.sync_channel(channel_id)

        # _save_channel's existence check must catch the deletion and
        # propagate False up through sync_channel.
        assert result is False


EMPTY_ICS = (
    b"BEGIN:VCALENDAR\r\nVERSION:2.0\r\nPRODID:-//Test//Test//EN\r\nEND:VCALENDAR"
)

LATIN1_ICS = (
    "BEGIN:VCALENDAR\r\nVERSION:2.0\r\nPRODID:-//Test//Test//EN\r\n"
    "BEGIN:VEVENT\r\nUID:latin1-event@test\r\n"
    "DTSTART:20260101T100000Z\r\nDTEND:20260101T110000Z\r\n"
    "SUMMARY:R\u00e9union d'\u00e9quipe\r\n"
    "LOCATION:Caf\u00e9 des Arts\r\n"
    "END:VEVENT\r\nEND:VCALENDAR"
).encode("latin-1")


class TestEmptyIcsProtection:
    """Tests for empty ICS protection (#7)."""

    def test_empty_ics_refuses_to_delete_all(self):
        """Sync with 0 new events but existing events should raise."""
        service = SubscriptionSyncService()

        # Mock existing events in SabreDAV
        mock_event = MagicMock()
        mock_event.icalendar_component.get.return_value = "existing-uid"
        mock_event.url.path = "/calendars/users/test/uuid/existing.ics"
        mock_event.data = "BEGIN:VCALENDAR\r\nEND:VCALENDAR"

        mock_calendar = MagicMock()
        mock_calendar.events.return_value = [mock_event]

        mock_client = MagicMock()
        mock_client.calendar.return_value = mock_calendar

        with patch.object(service._http, "get_dav_client", return_value=mock_client):
            with pytest.raises(ValueError, match="refusing to delete all events"):
                service._sync_events(
                    MagicMock(), "/calendars/users/test/uuid/", EMPTY_ICS
                )

    def test_empty_ics_on_empty_calendar_ok(self):
        """Sync with 0 new events and 0 existing events should not raise."""
        service = SubscriptionSyncService()

        mock_calendar = MagicMock()
        mock_calendar.events.return_value = []

        mock_client = MagicMock()
        mock_client.calendar.return_value = mock_calendar

        with patch.object(service._http, "get_dav_client", return_value=mock_client):
            result = service._sync_events(
                MagicMock(), "/calendars/users/test/uuid/", EMPTY_ICS
            )

        assert result.created == 0
        assert result.deleted == 0
        assert result.unchanged == 0


class TestIcsEncodingFallback:
    """Tests for non-UTF-8 ICS encoding (#9)."""

    def test_normalize_utf8_unchanged(self):
        """Valid UTF-8 data should pass through unchanged."""
        result = SubscriptionSyncService._normalize_ics_encoding(VALID_ICS)
        assert result == VALID_ICS

    def test_normalize_latin1_to_utf8(self):
        """Latin-1 encoded ICS should be converted to UTF-8."""
        result = SubscriptionSyncService._normalize_ics_encoding(LATIN1_ICS)
        # Should now be valid UTF-8
        decoded = result.decode("utf-8")
        assert "Réunion" in decoded
        assert "Café" in decoded

    def test_parse_latin1_ics(self):
        """Latin-1 ICS with accented characters should parse correctly."""
        service = SubscriptionSyncService()
        events = service._parse_ics_events(LATIN1_ICS)
        assert "latin1-event@test" in events
        assert "union" in events["latin1-event@test"]  # Réunion
