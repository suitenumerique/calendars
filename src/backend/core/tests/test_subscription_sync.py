"""Tests for subscription sync service.

The sync engine (ICS parsing, diffing, RRULE capping, encoding
normalisation) is exercised directly. State-layer calls into the
SabreDAV internal API are mocked.
"""

# pylint: disable=missing-class-docstring,missing-function-docstring,protected-access

from unittest.mock import patch

import pytest

from core.services.subscription_sync_service import (
    SubscriptionSyncService,
    _SystemUser,
)
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

LATIN1_ICS = (
    "BEGIN:VCALENDAR\r\nVERSION:2.0\r\nPRODID:-//Test//Test//EN\r\n"
    "BEGIN:VEVENT\r\nUID:latin1-event@test\r\n"
    "DTSTART:20260101T100000Z\r\nDTEND:20260101T110000Z\r\n"
    "SUMMARY:R\u00e9union d'\u00e9quipe\r\n"
    "END:VEVENT\r\nEND:VCALENDAR"
).encode("latin-1")


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


class TestIcsEncodingFallback:
    def test_normalize_utf8_unchanged(self):
        result = SubscriptionSyncService._normalize_ics_encoding(VALID_ICS)
        assert result == VALID_ICS

    def test_normalize_latin1_to_utf8(self):
        result = SubscriptionSyncService._normalize_ics_encoding(LATIN1_ICS)
        decoded = result.decode("utf-8")
        assert "Réunion" in decoded

    def test_parse_latin1_ics(self):
        service = SubscriptionSyncService()
        events = service._parse_ics_events(LATIN1_ICS)
        assert "latin1-event@test" in events


@patch("core.services.subscription_sync_service.cache")
class TestSyncSubscription:
    """Tests for sync_subscription() with mocked internal API calls."""

    @patch("core.services.subscription_sync_service.fetch_ics")
    @patch.object(SubscriptionSyncService, "_fetch_subscription_info")
    @patch.object(SubscriptionSyncService, "_fetch_existing_events")
    @patch.object(SubscriptionSyncService, "_apply_events_batch")
    @patch.object(SubscriptionSyncService, "_post_sync_result")
    def test_304_skips_sync(  # noqa: PLR0913  # pylint: disable=too-many-arguments,too-many-positional-arguments
        self,
        mock_post,
        mock_batch,
        mock_fetch_existing,
        mock_fetch_info,
        mock_fetch,
        mock_cache,
    ):
        mock_cache.add.return_value = True
        mock_fetch_info.return_value = {
            "source_url": "https://example.com/cal.ics",
            "etag": '"old-etag"',
            "last_modified": "old-date",
            "error_count": 0,
        }
        mock_fetch.return_value = (304, None, '"old-etag"', "old-date")

        service = SubscriptionSyncService()
        assert service.sync_subscription("abc123") is True

        mock_fetch_existing.assert_not_called()
        mock_batch.assert_not_called()
        mock_post.assert_called_once()
        kwargs = mock_post.call_args.kwargs
        assert kwargs["status"] == "ok"

    @patch("core.services.subscription_sync_service.fetch_ics")
    @patch.object(SubscriptionSyncService, "_fetch_subscription_info")
    @patch.object(SubscriptionSyncService, "_post_sync_result")
    def test_error_increments_count(
        self, mock_post, mock_fetch_info, mock_fetch, mock_cache
    ):
        mock_cache.add.return_value = True
        mock_fetch_info.return_value = {
            "source_url": "https://example.com/cal.ics",
            "etag": "",
            "last_modified": "",
            "error_count": 0,
        }
        mock_fetch.side_effect = URLValidationError("timeout")

        service = SubscriptionSyncService()
        assert service.sync_subscription("abc123") is False

        kwargs = mock_post.call_args.kwargs
        assert kwargs["status"] == "error"
        assert kwargs["error_count"] == 1
        assert "timeout" in kwargs["error_message"]

    @patch("core.services.subscription_sync_service.fetch_ics")
    @patch.object(SubscriptionSyncService, "_fetch_subscription_info")
    @patch.object(SubscriptionSyncService, "_post_sync_result")
    def test_three_strikes_auto_stops(
        self, mock_post, mock_fetch_info, mock_fetch, mock_cache
    ):
        mock_cache.add.return_value = True
        mock_fetch_info.return_value = {
            "source_url": "https://example.com/cal.ics",
            "etag": "",
            "last_modified": "",
            "error_count": 2,
        }
        mock_fetch.side_effect = URLValidationError("server error")

        service = SubscriptionSyncService()
        assert service.sync_subscription("abc123") is False

        kwargs = mock_post.call_args.kwargs
        assert kwargs["status"] == "stopped"
        assert kwargs["error_count"] == 3

    def test_lock_prevents_overlap(self, mock_cache):
        mock_cache.add.return_value = False  # lock held elsewhere

        service = SubscriptionSyncService()
        assert service.sync_subscription("abc123") is True

    @patch.object(SubscriptionSyncService, "_fetch_subscription_info")
    def test_missing_subscription_returns_false(self, mock_fetch_info, mock_cache):
        mock_cache.add.return_value = True
        mock_fetch_info.return_value = None

        service = SubscriptionSyncService()
        assert service.sync_subscription("does-not-exist") is False


class TestSyncEventsRefusesToDeleteAll:
    @patch.object(SubscriptionSyncService, "_apply_events_batch")
    @patch.object(SubscriptionSyncService, "_fetch_existing_events")
    def test_refuses_when_source_empty_but_calendar_has_events(
        self, mock_fetch_existing, mock_batch
    ):
        service = SubscriptionSyncService()
        mock_fetch_existing.return_value = {
            "u1@test": {"uri": "u1.ics", "data": ""},
        }
        empty_ics = (
            b"BEGIN:VCALENDAR\r\nVERSION:2.0\r\nPRODID:-//T//T//EN\r\nEND:VCALENDAR"
        )
        with pytest.raises(ValueError, match="refusing to delete all events"):
            service._sync_events("abc123", empty_ics)
        mock_batch.assert_not_called()


def test_system_user_passes_header_contract():
    user = _SystemUser()
    assert user.email
    assert user.organization_id
    # organization may be None — build_base_headers handles that case.
    assert user.organization is None


def test_events_differ_handles_unparseable_data():
    service = SubscriptionSyncService()
    # Any exception during parsing → treat as differing (safe default).
    assert service._events_differ("not ics", "also not ics") is True
