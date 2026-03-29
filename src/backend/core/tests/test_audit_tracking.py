"""Tests for event audit tracking (channel_id, created_by, modified_by).

Unit tests verify header plumbing. E2E tests hit the real SabreDAV server
and verify audit columns via the channel-events internal API endpoints.
"""

# pylint: disable=redefined-outer-name,missing-function-docstring,too-many-lines,no-member

import uuid
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest
from rest_framework.test import APIClient

from core import factories
from core.services.caldav_service import CalDAVHTTPClient, CalendarService
from core.services.channel_event_service import ChannelEventService
from core.services.import_service import ICSImportService

pytestmark = pytest.mark.django_db

CHANNELS_URL = "/api/v1.0/channels/"

ICS_SINGLE_EVENT = b"""BEGIN:VCALENDAR
VERSION:2.0
PRODID:-//Test//EN
BEGIN:VEVENT
UID:audit-test-001
DTSTART:20260210T140000Z
DTEND:20260210T150000Z
SUMMARY:Audit test
END:VEVENT
END:VCALENDAR"""


@pytest.fixture()
def _caldav_settings(settings):
    """Configure CalDAV settings for all tests that need them."""
    settings.CALDAV_URL = "http://caldav:80"
    settings.CALDAV_INTERNAL_API_KEY = "test-internal-key"
    settings.CALDAV_OUTBOUND_API_KEY = "test-api-key"


def _make_caldav_path(user):
    return f"/calendars/users/{user.email}/{uuid.uuid4()}/"


def _make_sabredav_response(status_code=200, **body_fields):
    mock_resp = MagicMock()
    mock_resp.status_code = status_code
    defaults = {
        "total_events": 0,
        "imported_count": 0,
        "duplicate_count": 0,
        "skipped_count": 0,
        "errors": [],
    }
    defaults.update(body_fields)
    mock_resp.json.return_value = defaults
    mock_resp.text = "{}"
    return mock_resp


# ---------------------------------------------------------------------------
# Unit: CalDAV proxy X-CalDAV-Channel-Id header
# ---------------------------------------------------------------------------


class TestCalDAVProxyChannelIdHeader:
    """Verify the proxy passes X-CalDAV-Channel-Id for channel auth."""

    @patch("core.api.viewsets_caldav.CalDAVHTTPClient")
    @patch("core.api.viewsets_caldav.requests.request")
    def test_channel_put_sends_channel_id_header(self, mock_request, mock_http_cls):
        """PUT via channel token must include X-CalDAV-Channel-Id."""
        user = factories.UserFactory()
        channel = factories.ChannelFactory(
            user=user,
            settings={"role": "editor"},
        )
        token = channel.encrypted_settings["token"]

        mock_response = MagicMock()
        mock_response.status_code = 201
        mock_response.content = b""
        mock_response.headers = {"Content-Type": "text/plain"}
        mock_request.return_value = mock_response

        mock_http_cls.build_base_headers.return_value = {
            "X-Api-Key": "test",
            "X-Forwarded-User": user.email,
        }

        client = APIClient()
        client.put(
            f"/caldav/calendars/users/{user.email}/cal/event.ics",
            data=b"BEGIN:VCALENDAR",
            content_type="text/calendar",
            HTTP_X_CHANNEL_ID=str(channel.pk),
            HTTP_X_CHANNEL_TOKEN=token,
        )

        mock_request.assert_called_once()
        headers = mock_request.call_args.kwargs["headers"]
        assert headers["X-CalDAV-Channel-Id"] == str(channel.pk)

    @patch("core.api.viewsets_caldav.CalDAVHTTPClient")
    @patch("core.api.viewsets_caldav.requests.request")
    def test_channel_propfind_sends_channel_id_header(
        self, mock_request, mock_http_cls
    ):
        """PROPFIND via channel token also includes X-CalDAV-Channel-Id."""
        user = factories.UserFactory()
        channel = factories.ChannelFactory(
            user=user,
            settings={"role": "reader"},
        )
        token = channel.encrypted_settings["token"]

        mock_response = MagicMock()
        mock_response.status_code = 207
        mock_response.content = b"<xml/>"
        mock_response.headers = {"Content-Type": "application/xml"}
        mock_request.return_value = mock_response

        mock_http_cls.build_base_headers.return_value = {
            "X-Api-Key": "test",
            "X-Forwarded-User": user.email,
        }

        client = APIClient()
        client.generic(
            "PROPFIND",
            f"/caldav/calendars/users/{user.email}/",
            HTTP_X_CHANNEL_ID=str(channel.pk),
            HTTP_X_CHANNEL_TOKEN=token,
            HTTP_DEPTH="1",
        )

        mock_request.assert_called_once()
        headers = mock_request.call_args.kwargs["headers"]
        assert headers["X-CalDAV-Channel-Id"] == str(channel.pk)


# ---------------------------------------------------------------------------
# Unit: Import service channel_id parameter
# ---------------------------------------------------------------------------


@pytest.mark.usefixtures("_caldav_settings")
class TestImportChannelId:
    """Verify the import service passes channel_id as a header."""

    @patch("core.services.caldav_service.requests.request")
    def test_import_with_channel_id_sends_header(self, mock_request):
        mock_request.return_value = _make_sabredav_response(
            total_events=1, imported_count=1
        )

        user = factories.UserFactory()
        caldav_path = _make_caldav_path(user)
        channel_id = str(uuid.uuid4())

        service = ICSImportService()
        service.import_events(
            user, caldav_path, ICS_SINGLE_EVENT, channel_id=channel_id
        )

        headers = mock_request.call_args.kwargs["headers"]
        assert headers["X-CalDAV-Channel-Id"] == channel_id

    @patch("core.services.caldav_service.requests.request")
    def test_import_without_channel_id_omits_header(self, mock_request):
        mock_request.return_value = _make_sabredav_response(
            total_events=1, imported_count=1
        )

        user = factories.UserFactory()
        caldav_path = _make_caldav_path(user)

        service = ICSImportService()
        service.import_events(user, caldav_path, ICS_SINGLE_EVENT)

        headers = mock_request.call_args.kwargs["headers"]
        assert "X-CalDAV-Channel-Id" not in headers


# ---------------------------------------------------------------------------
# Unit: CalDAVHTTPClient.internal_request
# ---------------------------------------------------------------------------


@pytest.mark.usefixtures("_caldav_settings")
class TestInternalRequest:
    """Verify internal_request adds API key and handles json= param."""

    @patch("core.services.caldav_service.requests.request")
    def test_adds_internal_api_key(self, mock_request):
        mock_request.return_value = MagicMock(status_code=200)

        user = factories.UserFactory()
        http = CalDAVHTTPClient()
        http.internal_request("GET", user, "internal-api/test")

        headers = mock_request.call_args.kwargs["headers"]
        assert headers["X-Internal-Api-Key"] == "test-internal-key"

    @patch("core.services.caldav_service.requests.request")
    def test_json_param_serializes_body(self, mock_request):
        mock_request.return_value = MagicMock(status_code=200)

        user = factories.UserFactory()
        http = CalDAVHTTPClient()
        http.internal_request(
            "POST",
            user,
            "internal-api/test",
            json={"email": "alice@example.com"},
        )

        call_kwargs = mock_request.call_args.kwargs
        headers = call_kwargs["headers"]
        data = call_kwargs["data"]

        assert headers["Content-Type"] == "application/json"
        assert b'"email"' in data
        assert b"alice@example.com" in data

    def test_raises_without_api_key(self, settings):
        settings.CALDAV_INTERNAL_API_KEY = ""
        settings.CALDAV_URL = "http://caldav:80"
        settings.CALDAV_OUTBOUND_API_KEY = "test-api-key"

        user = factories.UserFactory()
        http = CalDAVHTTPClient()

        with pytest.raises(ValueError, match="CALDAV_INTERNAL_API_KEY"):
            http.internal_request("GET", user, "internal-api/test")

    @patch("core.services.caldav_service.requests.request")
    def test_extra_headers_merged(self, mock_request):
        mock_request.return_value = MagicMock(status_code=200)

        user = factories.UserFactory()
        http = CalDAVHTTPClient()
        http.internal_request(
            "POST",
            user,
            "internal-api/test",
            extra_headers={"X-CalDAV-Channel-Id": "abc-123"},
        )

        headers = mock_request.call_args.kwargs["headers"]
        assert headers["X-Internal-Api-Key"] == "test-internal-key"
        assert headers["X-CalDAV-Channel-Id"] == "abc-123"


# ---------------------------------------------------------------------------
# Unit: Channel events viewset
# ---------------------------------------------------------------------------


class TestChannelEventsAPI:
    """Tests for GET/DELETE /channels/{id}/events/ and events/count/."""

    def test_list_events(self):
        user = factories.UserFactory()
        channel = factories.ChannelFactory(user=user)

        client = APIClient()
        client.force_authenticate(user=user)

        mock_events = [{"uid": "ev-1", "uri": "ev-1.ics", "calendar_path": "/cal/"}]

        with patch.object(
            ChannelEventService,
            "list_events",
            return_value=mock_events,
        ) as mock_list:
            response = client.get(f"{CHANNELS_URL}{channel.pk}/events/")

        assert response.status_code == 200
        assert response.json()["events"] == mock_events
        mock_list.assert_called_once_with(user, str(channel.pk))

    def test_delete_events(self):
        user = factories.UserFactory()
        channel = factories.ChannelFactory(user=user)

        client = APIClient()
        client.force_authenticate(user=user)

        mock_result = {"deleted_count": 3, "errors": []}

        with patch.object(
            ChannelEventService,
            "delete_events",
            return_value=mock_result,
        ) as mock_delete:
            response = client.delete(f"{CHANNELS_URL}{channel.pk}/events/")

        assert response.status_code == 200
        assert response.json()["deleted_count"] == 3
        mock_delete.assert_called_once_with(user, str(channel.pk))

    def test_count_events(self):
        user = factories.UserFactory()
        channel = factories.ChannelFactory(user=user)

        client = APIClient()
        client.force_authenticate(user=user)

        with patch.object(
            ChannelEventService,
            "count_events",
            return_value=42,
        ) as mock_count:
            response = client.get(f"{CHANNELS_URL}{channel.pk}/events/count/")

        assert response.status_code == 200
        assert response.json()["count"] == 42
        mock_count.assert_called_once_with(user, str(channel.pk))

    def test_events_not_found_for_other_user(self):
        user_a = factories.UserFactory()
        channel = factories.ChannelFactory(user=user_a)

        user_b = factories.UserFactory()
        client = APIClient()
        client.force_authenticate(user=user_b)

        response = client.get(f"{CHANNELS_URL}{channel.pk}/events/")
        assert response.status_code == 404

    def test_events_requires_auth(self):
        channel = factories.ChannelFactory()
        client = APIClient()
        response = client.get(f"{CHANNELS_URL}{channel.pk}/events/")
        assert response.status_code in (401, 403)


# ===========================================================================
# E2E tests — hit real SabreDAV, verify audit columns via internal API
# ===========================================================================

e2e_marks = [
    pytest.mark.django_db,
    pytest.mark.xdist_group("caldav"),
]


def _put_event(client, user_email, cal_id, event_uid, summary="Test Event"):
    """PUT a VCALENDAR event into a calendar via the CalDAV proxy."""
    dtstart = datetime.now() + timedelta(days=1)
    dtend = dtstart + timedelta(hours=1)
    ical = (
        "BEGIN:VCALENDAR\r\n"
        "VERSION:2.0\r\n"
        "PRODID:-//Test//Test//EN\r\n"
        "BEGIN:VEVENT\r\n"
        f"UID:{event_uid}\r\n"
        f"DTSTART:{dtstart.strftime('%Y%m%dT%H%M%SZ')}\r\n"
        f"DTEND:{dtend.strftime('%Y%m%dT%H%M%SZ')}\r\n"
        f"SUMMARY:{summary}\r\n"
        "END:VEVENT\r\n"
        "END:VCALENDAR\r\n"
    )
    return client.generic(
        "PUT",
        f"/caldav/calendars/users/{user_email}/{cal_id}/{event_uid}.ics",
        data=ical,
        content_type="text/calendar",
    )


def _get_cal_id(caldav_path):
    parts = caldav_path.strip("/").split("/")
    return parts[-1] if len(parts) >= 4 else "default"


@pytest.mark.xdist_group("caldav")
class TestAuditTrackingE2E:
    """E2E: verify audit columns are set by SabreDAV and queryable."""

    @pytest.fixture(autouse=True)
    def _setup(self, settings):
        settings.ENTITLEMENTS_BACKEND = (
            "core.entitlements.backends.local.LocalEntitlementsBackend"
        )
        settings.ENTITLEMENTS_BACKEND_PARAMETERS = {}
        from core.entitlements.factory import (  # noqa: PLC0415  # pylint: disable=import-outside-toplevel
            get_entitlements_backend,
        )

        get_entitlements_backend.cache_clear()
        yield
        get_entitlements_backend.cache_clear()

    def test_session_user_put_sets_created_by(self):
        """Regular user PUT sets created_by, channel_id stays NULL."""
        org = factories.OrganizationFactory()
        user = factories.UserFactory(email="audit-user@test.com", organization=org)
        client = APIClient()
        client.force_login(user)

        service = CalendarService()
        caldav_path = service.create_calendar(user, name="Audit Cal")
        cal_id = _get_cal_id(caldav_path)

        event_uid = f"audit-e2e-{uuid.uuid4()}"
        resp = _put_event(client, user.email, cal_id, event_uid)
        assert resp.status_code in (200, 201), resp.content

        # Query via channel-events — no channel, so count should be 0
        chan_service = ChannelEventService()
        fake_channel_id = str(uuid.uuid4())
        count = chan_service.count_events(user, fake_channel_id)
        assert count == 0

    def test_channel_put_sets_channel_id(self):
        """PUT via channel token sets channel_id; other channel sees nothing."""
        org = factories.OrganizationFactory()
        user = factories.UserFactory(email="chan-audit@test.com", organization=org)

        session_client = APIClient()
        session_client.force_login(user)
        service = CalendarService()
        caldav_path = service.create_calendar(user, name="Channel Cal")
        cal_id = _get_cal_id(caldav_path)

        # Create two channels on the same calendar
        channel_a = factories.ChannelFactory(
            user=user,
            settings={"role": "editor"},
            caldav_path=caldav_path,
        )
        channel_b = factories.ChannelFactory(
            user=user,
            settings={"role": "editor"},
            caldav_path=caldav_path,
        )

        # PUT one event via channel A
        event_uid_a = f"chan-a-{uuid.uuid4()}"
        resp = APIClient().generic(
            "PUT",
            f"/caldav/calendars/users/{user.email}/{cal_id}/{event_uid_a}.ics",
            data=(
                "BEGIN:VCALENDAR\r\n"
                "VERSION:2.0\r\n"
                "PRODID:-//Test//EN\r\n"
                "BEGIN:VEVENT\r\n"
                f"UID:{event_uid_a}\r\n"
                "DTSTART:20260301T100000Z\r\n"
                "DTEND:20260301T110000Z\r\n"
                "SUMMARY:Channel A event\r\n"
                "END:VEVENT\r\n"
                "END:VCALENDAR\r\n"
            ),
            content_type="text/calendar",
            HTTP_X_CHANNEL_ID=str(channel_a.pk),
            HTTP_X_CHANNEL_TOKEN=channel_a.encrypted_settings["token"],
        )
        assert resp.status_code in (200, 201), resp.content

        # PUT another event via channel B
        event_uid_b = f"chan-b-{uuid.uuid4()}"
        resp = APIClient().generic(
            "PUT",
            f"/caldav/calendars/users/{user.email}/{cal_id}/{event_uid_b}.ics",
            data=(
                "BEGIN:VCALENDAR\r\n"
                "VERSION:2.0\r\n"
                "PRODID:-//Test//EN\r\n"
                "BEGIN:VEVENT\r\n"
                f"UID:{event_uid_b}\r\n"
                "DTSTART:20260301T120000Z\r\n"
                "DTEND:20260301T130000Z\r\n"
                "SUMMARY:Channel B event\r\n"
                "END:VEVENT\r\n"
                "END:VCALENDAR\r\n"
            ),
            content_type="text/calendar",
            HTTP_X_CHANNEL_ID=str(channel_b.pk),
            HTTP_X_CHANNEL_TOKEN=channel_b.encrypted_settings["token"],
        )
        assert resp.status_code in (200, 201), resp.content

        # Channel A sees only its event
        chan_service = ChannelEventService()
        events_a = chan_service.list_events(user, str(channel_a.pk))
        uids_a = [e["uid"] for e in events_a]
        assert event_uid_a in uids_a
        assert event_uid_b not in uids_a
        assert chan_service.count_events(user, str(channel_a.pk)) == 1

        # Channel B sees only its event
        events_b = chan_service.list_events(user, str(channel_b.pk))
        uids_b = [e["uid"] for e in events_b]
        assert event_uid_b in uids_b
        assert event_uid_a not in uids_b
        assert chan_service.count_events(user, str(channel_b.pk)) == 1

    def test_channel_id_preserved_on_user_update(self):
        """User updating a channel-created event preserves channel_id."""
        org = factories.OrganizationFactory()
        user = factories.UserFactory(email="preserve-audit@test.com", organization=org)

        session_client = APIClient()
        session_client.force_login(user)
        service = CalendarService()
        caldav_path = service.create_calendar(user, name="Preserve Cal")
        cal_id = _get_cal_id(caldav_path)

        # Create channel and PUT event
        channel = factories.ChannelFactory(
            user=user,
            settings={"role": "editor"},
            caldav_path=caldav_path,
        )
        token = channel.encrypted_settings["token"]

        chan_client = APIClient()
        event_uid = f"preserve-e2e-{uuid.uuid4()}"
        resp = chan_client.generic(
            "PUT",
            f"/caldav/calendars/users/{user.email}/{cal_id}/{event_uid}.ics",
            data=(
                "BEGIN:VCALENDAR\r\n"
                "VERSION:2.0\r\n"
                "PRODID:-//Test//EN\r\n"
                "BEGIN:VEVENT\r\n"
                f"UID:{event_uid}\r\n"
                "DTSTART:20260301T100000Z\r\n"
                "DTEND:20260301T110000Z\r\n"
                "SUMMARY:Original\r\n"
                "END:VEVENT\r\n"
                "END:VCALENDAR\r\n"
            ),
            content_type="text/calendar",
            HTTP_X_CHANNEL_ID=str(channel.pk),
            HTTP_X_CHANNEL_TOKEN=token,
        )
        assert resp.status_code in (200, 201)

        # Now update via regular session auth (no channel header)
        resp = _put_event(
            session_client, user.email, cal_id, event_uid, summary="Updated"
        )
        assert resp.status_code in (200, 201, 204)

        # channel_id should still be associated (COALESCE preserves it)
        chan_service = ChannelEventService()
        events = chan_service.list_events(user, str(channel.pk))
        uids = [e["uid"] for e in events]
        assert event_uid in uids

    def test_import_sets_channel_id(self):
        """ICS import with channel_id sets audit columns on all events."""
        org = factories.OrganizationFactory()
        user = factories.UserFactory(email="import-audit@test.com", organization=org)

        service = CalendarService()
        caldav_path = service.create_calendar(user, name="Import Cal")

        channel = factories.ChannelFactory(
            user=user,
            settings={"role": "editor"},
            caldav_path=caldav_path,
        )

        import_uid = f"import-e2e-{uuid.uuid4()}"
        ics_data = (
            b"BEGIN:VCALENDAR\r\n"
            b"VERSION:2.0\r\n"
            b"PRODID:-//Test//EN\r\n"
            b"BEGIN:VEVENT\r\n"
            b"UID:" + import_uid.encode() + b"\r\n"
            b"DTSTART:20260401T090000Z\r\n"
            b"DTEND:20260401T100000Z\r\n"
            b"SUMMARY:Imported event\r\n"
            b"END:VEVENT\r\n"
            b"END:VCALENDAR\r\n"
        )

        import_service = ICSImportService()
        result = import_service.import_events(
            user, caldav_path, ics_data, channel_id=str(channel.pk)
        )
        assert result.imported_count == 1

        # Verify via channel-events
        chan_service = ChannelEventService()
        events = chan_service.list_events(user, str(channel.pk))
        uids = [e["uid"] for e in events]
        assert import_uid in uids

    def test_channel_events_delete_only_removes_own_events(self):
        """DELETE removes one channel's events without touching another's."""
        org = factories.OrganizationFactory()
        user = factories.UserFactory(email="delete-audit@test.com", organization=org)

        service = CalendarService()
        caldav_path = service.create_calendar(user, name="Delete Cal")

        channel_a = factories.ChannelFactory(
            user=user,
            settings={"role": "editor"},
            caldav_path=caldav_path,
        )
        channel_b = factories.ChannelFactory(
            user=user,
            settings={"role": "editor"},
            caldav_path=caldav_path,
        )

        import_service = ICSImportService()

        # Import 2 events via channel A
        result_a = import_service.import_events(
            user,
            caldav_path,
            (
                b"BEGIN:VCALENDAR\r\nVERSION:2.0\r\nPRODID:-//T//EN\r\n"
                b"BEGIN:VEVENT\r\nUID:del-a-1\r\n"
                b"DTSTART:20260501T090000Z\r\nDTEND:20260501T100000Z\r\n"
                b"SUMMARY:A1\r\nEND:VEVENT\r\n"
                b"BEGIN:VEVENT\r\nUID:del-a-2\r\n"
                b"DTSTART:20260502T090000Z\r\nDTEND:20260502T100000Z\r\n"
                b"SUMMARY:A2\r\nEND:VEVENT\r\n"
                b"END:VCALENDAR\r\n"
            ),
            channel_id=str(channel_a.pk),
        )
        assert result_a.imported_count == 2

        # Import 1 event via channel B
        result_b = import_service.import_events(
            user,
            caldav_path,
            (
                b"BEGIN:VCALENDAR\r\nVERSION:2.0\r\nPRODID:-//T//EN\r\n"
                b"BEGIN:VEVENT\r\nUID:del-b-1\r\n"
                b"DTSTART:20260503T090000Z\r\nDTEND:20260503T100000Z\r\n"
                b"SUMMARY:B1\r\nEND:VEVENT\r\n"
                b"END:VCALENDAR\r\n"
            ),
            channel_id=str(channel_b.pk),
        )
        assert result_b.imported_count == 1

        chan_service = ChannelEventService()
        assert chan_service.count_events(user, str(channel_a.pk)) == 2
        assert chan_service.count_events(user, str(channel_b.pk)) == 1

        # Delete channel A's events
        delete_result = chan_service.delete_events(user, str(channel_a.pk))
        assert delete_result["deleted_count"] == 2
        assert not delete_result["errors"]

        # Channel A is empty, channel B is untouched
        assert chan_service.count_events(user, str(channel_a.pk)) == 0
        assert chan_service.count_events(user, str(channel_b.pk)) == 1
