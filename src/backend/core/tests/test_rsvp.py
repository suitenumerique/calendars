"""Tests for RSVP view and token generation."""

# pylint: disable=missing-function-docstring,protected-access

import re
from datetime import timedelta
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse

from django.core import mail
from django.core.signing import BadSignature, Signer
from django.template.loader import render_to_string
from django.test import RequestFactory, TestCase, override_settings
from django.utils import timezone

import icalendar
import pytest

from core.api.viewsets_rsvp import RSVPView
from core.services.caldav_service import CalDAVHTTPClient
from core.services.calendar_invitation_service import (
    CalendarInvitationService,
    ICalendarParser,
)


def _make_ics(uid="test-uid-123", summary="Team Meeting", sequence=0, days_from_now=30):
    """Build a sample ICS string with a date relative to now."""
    dt = timezone.now() + timedelta(days=days_from_now)
    dtstart = dt.strftime("%Y%m%dT%H%M%SZ")
    dtend = (dt + timedelta(hours=1)).strftime("%Y%m%dT%H%M%SZ")
    return (
        "BEGIN:VCALENDAR\r\n"
        "VERSION:2.0\r\n"
        "PRODID:-//Test//EN\r\n"
        "BEGIN:VEVENT\r\n"
        f"UID:{uid}\r\n"
        f"DTSTART:{dtstart}\r\n"
        f"DTEND:{dtend}\r\n"
        f"SUMMARY:{summary}\r\n"
        "ORGANIZER;CN=Alice:mailto:alice@example.com\r\n"
        "ATTENDEE;CN=Bob;PARTSTAT=NEEDS-ACTION;RSVP=TRUE:mailto:bob@example.com\r\n"
        f"SEQUENCE:{sequence}\r\n"
        "END:VEVENT\r\n"
        "END:VCALENDAR"
    )


SAMPLE_ICS = _make_ics()
SAMPLE_ICS_UPDATE = _make_ics(uid="test-uid-456", summary="Updated Meeting", sequence=1)
SAMPLE_ICS_PAST = _make_ics(
    uid="test-uid-past", summary="Past Meeting", days_from_now=-30
)

SAMPLE_CALDAV_RESPONSE = """\
<?xml version="1.0" encoding="UTF-8"?>
<d:multistatus xmlns:d="DAV:" xmlns:cal="urn:ietf:params:xml:ns:caldav">
  <d:response>
    <d:href>/api/v1.0/caldav/calendars/alice%40example.com/cal-uuid/test-uid-123.ics</d:href>
    <d:propstat>
      <d:prop>
        <d:gethref>/api/v1.0/caldav/calendars/alice%40example.com/cal-uuid/test-uid-123.ics</d:gethref>
        <cal:calendar-data>{ics_data}</cal:calendar-data>
      </d:prop>
      <d:status>HTTP/1.1 200 OK</d:status>
    </d:propstat>
  </d:response>
</d:multistatus>"""


def _make_token(
    uid="test-uid-123", email="bob@example.com", organizer="alice@example.com"
):
    """Create a valid signed RSVP token."""
    signer = Signer(salt="rsvp")
    return signer.sign_object(
        {
            "uid": uid,
            "email": email,
            "organizer": organizer,
        }
    )


class TestRSVPTokenGeneration:
    """Tests for RSVP token generation in invitation service."""

    def test_token_roundtrip(self):
        """A generated token can be unsigned to recover the payload."""
        token = _make_token()
        signer = Signer(salt="rsvp")
        payload = signer.unsign_object(token)
        assert payload["uid"] == "test-uid-123"
        assert payload["email"] == "bob@example.com"
        assert payload["organizer"] == "alice@example.com"

    def test_tampered_token_fails(self):
        """A tampered token raises BadSignature."""
        token = _make_token() + "tampered"
        signer = Signer(salt="rsvp")
        with pytest.raises(BadSignature):
            signer.unsign_object(token)


@pytest.mark.django_db
class TestRSVPUrlsInContext:
    """Tests that RSVP URLs are added to template context for REQUEST method."""

    def test_request_method_has_rsvp_urls(self):
        """REQUEST method should include RSVP URLs in context."""
        event = ICalendarParser.parse(SAMPLE_ICS, "bob@example.com")
        service = CalendarInvitationService()
        context = service._build_template_context(event, "REQUEST")

        assert "rsvp_accept_url" in context
        assert "rsvp_tentative_url" in context
        assert "rsvp_decline_url" in context

        # Check URLs contain proper action params
        assert "action=accepted" in context["rsvp_accept_url"]
        assert "action=tentative" in context["rsvp_tentative_url"]
        assert "action=declined" in context["rsvp_decline_url"]

        # Check all URLs contain a token
        for key in ("rsvp_accept_url", "rsvp_tentative_url", "rsvp_decline_url"):
            parsed = urlparse(context[key])
            params = parse_qs(parsed.query)
            assert "token" in params

    def test_cancel_method_has_no_rsvp_urls(self):
        """CANCEL method should NOT include RSVP URLs."""
        event = ICalendarParser.parse(SAMPLE_ICS, "bob@example.com")
        service = CalendarInvitationService()
        context = service._build_template_context(event, "CANCEL")

        assert "rsvp_accept_url" not in context

    def test_reply_method_has_no_rsvp_urls(self):
        """REPLY method should NOT include RSVP URLs."""
        event = ICalendarParser.parse(SAMPLE_ICS, "bob@example.com")
        service = CalendarInvitationService()
        context = service._build_template_context(event, "REPLY")

        assert "rsvp_accept_url" not in context


@pytest.mark.django_db
class TestRSVPEmailTemplateRendering:
    """Tests that RSVP buttons appear in email templates."""

    def _build_context(self, ics_data, method="REQUEST"):
        event = ICalendarParser.parse(ics_data, "bob@example.com")
        service = CalendarInvitationService()
        return service._build_template_context(event, method)

    def test_invitation_html_has_rsvp_buttons(self):
        context = self._build_context(SAMPLE_ICS)
        html = render_to_string("emails/calendar_invitation.html", context)
        assert "Accepter" in html
        assert "Peut-être" in html
        assert "Refuser" in html

    def test_invitation_txt_has_rsvp_links(self):
        context = self._build_context(SAMPLE_ICS)
        txt = render_to_string("emails/calendar_invitation.txt", context)
        assert "Accepter" in txt
        assert "Peut-être" in txt
        assert "Refuser" in txt

    def test_update_html_has_rsvp_buttons(self):
        context = self._build_context(SAMPLE_ICS_UPDATE)
        html = render_to_string("emails/calendar_invitation_update.html", context)
        assert "Accepter" in html
        assert "Peut-être" in html
        assert "Refuser" in html

    def test_update_txt_has_rsvp_links(self):
        context = self._build_context(SAMPLE_ICS_UPDATE)
        txt = render_to_string("emails/calendar_invitation_update.txt", context)
        assert "Accepter" in txt
        assert "Peut-être" in txt
        assert "Refuser" in txt

    def test_cancel_html_has_no_rsvp_buttons(self):
        context = self._build_context(SAMPLE_ICS, method="CANCEL")
        html = render_to_string("emails/calendar_invitation_cancel.html", context)
        assert "rsvp" not in html.lower() or "Accepter" not in html

    def test_invitation_html_no_rsvp_for_cancel(self):
        """Cancel templates don't have RSVP buttons."""
        context = self._build_context(SAMPLE_ICS, method="CANCEL")
        html = render_to_string("emails/calendar_invitation_cancel.html", context)
        assert "Accepter" not in html


class TestUpdateAttendeePartstat:
    """Tests for the _update_attendee_partstat function."""

    def test_update_existing_partstat(self):
        result = CalDAVHTTPClient.update_attendee_partstat(
            SAMPLE_ICS, "bob@example.com", "ACCEPTED"
        )
        assert result is not None
        assert "PARTSTAT=ACCEPTED" in result
        assert "PARTSTAT=NEEDS-ACTION" not in result

    def test_update_to_declined(self):
        result = CalDAVHTTPClient.update_attendee_partstat(
            SAMPLE_ICS, "bob@example.com", "DECLINED"
        )
        assert result is not None
        assert "PARTSTAT=DECLINED" in result

    def test_update_to_tentative(self):
        result = CalDAVHTTPClient.update_attendee_partstat(
            SAMPLE_ICS, "bob@example.com", "TENTATIVE"
        )
        assert result is not None
        assert "PARTSTAT=TENTATIVE" in result

    def test_unknown_attendee_returns_none(self):
        result = CalDAVHTTPClient.update_attendee_partstat(
            SAMPLE_ICS, "unknown@example.com", "ACCEPTED"
        )
        assert result is None

    def test_preserves_other_attendee_properties(self):
        result = CalDAVHTTPClient.update_attendee_partstat(
            SAMPLE_ICS, "bob@example.com", "ACCEPTED"
        )
        assert result is not None
        assert "CN=Bob" in result
        assert "mailto:bob@example.com" in result


@override_settings(
    CALDAV_URL="http://caldav:80",
    CALDAV_OUTBOUND_API_KEY="test-api-key",
    APP_URL="http://localhost:8921",
)
class TestRSVPView(TestCase):
    """Tests for the RSVPView."""

    def setUp(self):
        self.factory = RequestFactory()
        self.view = RSVPView.as_view()

    def test_invalid_action_returns_400(self):
        token = _make_token()
        request = self.factory.get("/rsvp/", {"token": token, "action": "invalid"})
        response = self.view(request)
        assert response.status_code == 400

    def test_missing_action_returns_400(self):
        token = _make_token()
        request = self.factory.get("/rsvp/", {"token": token})
        response = self.view(request)
        assert response.status_code == 400

    def test_invalid_token_returns_400(self):
        request = self.factory.get(
            "/rsvp/", {"token": "bad-token", "action": "accepted"}
        )
        response = self.view(request)
        assert response.status_code == 400

    def test_missing_token_returns_400(self):
        request = self.factory.get("/rsvp/", {"action": "accepted"})
        response = self.view(request)
        assert response.status_code == 400

    @patch.object(CalDAVHTTPClient, "put_event")
    @patch.object(CalDAVHTTPClient, "find_event_by_uid")
    def test_accept_flow(self, mock_find, mock_put):
        """Full accept flow: find event, update partstat, put back."""
        mock_find.return_value = (
            SAMPLE_ICS,
            "/api/v1.0/caldav/calendars/alice%40example.com/cal/event.ics",
        )
        mock_put.return_value = True

        token = _make_token()
        request = self.factory.get("/rsvp/", {"token": token, "action": "accepted"})
        response = self.view(request)

        assert response.status_code == 200
        assert "accepted the invitation" in response.content.decode()

        # Verify CalDAV calls
        mock_find.assert_called_once_with("alice@example.com", "test-uid-123")
        mock_put.assert_called_once()
        # Check the updated data contains ACCEPTED
        put_args = mock_put.call_args
        assert "PARTSTAT=ACCEPTED" in put_args[0][2]

    @patch.object(CalDAVHTTPClient, "put_event")
    @patch.object(CalDAVHTTPClient, "find_event_by_uid")
    def test_decline_flow(self, mock_find, mock_put):
        mock_find.return_value = (SAMPLE_ICS, "/path/to/event.ics")
        mock_put.return_value = True

        token = _make_token()
        request = self.factory.get("/rsvp/", {"token": token, "action": "declined"})
        response = self.view(request)

        assert response.status_code == 200
        assert "declined the invitation" in response.content.decode()
        put_args = mock_put.call_args
        assert "PARTSTAT=DECLINED" in put_args[0][2]

    @patch.object(CalDAVHTTPClient, "put_event")
    @patch.object(CalDAVHTTPClient, "find_event_by_uid")
    def test_tentative_flow(self, mock_find, mock_put):
        mock_find.return_value = (SAMPLE_ICS, "/path/to/event.ics")
        mock_put.return_value = True

        token = _make_token()
        request = self.factory.get("/rsvp/", {"token": token, "action": "tentative"})
        response = self.view(request)

        assert response.status_code == 200
        content = response.content.decode()
        assert "maybe" in content.lower()
        put_args = mock_put.call_args
        assert "PARTSTAT=TENTATIVE" in put_args[0][2]

    @patch.object(CalDAVHTTPClient, "find_event_by_uid")
    def test_event_not_found_returns_400(self, mock_find):
        mock_find.return_value = (None, None)

        token = _make_token()
        request = self.factory.get("/rsvp/", {"token": token, "action": "accepted"})
        response = self.view(request)

        assert response.status_code == 400
        assert "not found" in response.content.decode().lower()

    @patch.object(CalDAVHTTPClient, "put_event")
    @patch.object(CalDAVHTTPClient, "find_event_by_uid")
    def test_put_failure_returns_400(self, mock_find, mock_put):
        mock_find.return_value = (SAMPLE_ICS, "/path/to/event.ics")
        mock_put.return_value = False

        token = _make_token()
        request = self.factory.get("/rsvp/", {"token": token, "action": "accepted"})
        response = self.view(request)

        assert response.status_code == 400
        assert "error occurred" in response.content.decode().lower()

    @patch.object(CalDAVHTTPClient, "find_event_by_uid")
    def test_attendee_not_in_event_returns_400(self, mock_find):
        """If the attendee email is not in the event, return error."""
        mock_find.return_value = (SAMPLE_ICS, "/path/to/event.ics")

        # Token with an email that's not in the event
        token = _make_token(email="stranger@example.com")
        request = self.factory.get("/rsvp/", {"token": token, "action": "accepted"})
        response = self.view(request)

        assert response.status_code == 400
        assert "not listed" in response.content.decode().lower()

    @patch.object(CalDAVHTTPClient, "find_event_by_uid")
    def test_past_event_returns_400(self, mock_find):
        """Cannot RSVP to an event that has already ended."""
        mock_find.return_value = (SAMPLE_ICS_PAST, "/path/to/event.ics")

        token = _make_token(uid="test-uid-past")
        request = self.factory.get("/rsvp/", {"token": token, "action": "accepted"})
        response = self.view(request)

        assert response.status_code == 400
        assert "already passed" in response.content.decode().lower()


def _make_ics_with_method(method="REQUEST"):
    """Build a sample ICS string that includes a METHOD property."""
    return (
        "BEGIN:VCALENDAR\r\n"
        "VERSION:2.0\r\n"
        f"METHOD:{method}\r\n"
        "PRODID:-//Test//EN\r\n"
        "BEGIN:VEVENT\r\n"
        "UID:itip-test\r\n"
        "DTSTART:20260301T100000Z\r\n"
        "DTEND:20260301T110000Z\r\n"
        "SUMMARY:iTIP test\r\n"
        "ORGANIZER:mailto:alice@example.com\r\n"
        "ATTENDEE:mailto:bob@example.com\r\n"
        "END:VEVENT\r\n"
        "END:VCALENDAR"
    )


@pytest.mark.django_db
class TestItipSetting:
    """Tests for CALENDAR_ITIP_ENABLED setting on ICS attachments."""

    def _prepare(self, ics_data, method="REQUEST"):
        service = CalendarInvitationService()
        return service._prepare_ics_attachment(ics_data, method)

    @override_settings(CALENDAR_ITIP_ENABLED=False)
    def test_disabled_strips_existing_method(self):
        result = self._prepare(_make_ics_with_method("REQUEST"))
        cal = icalendar.Calendar.from_ical(result)
        assert "METHOD" not in cal

    @override_settings(CALENDAR_ITIP_ENABLED=False)
    def test_disabled_does_not_add_method(self):
        result = self._prepare(SAMPLE_ICS)
        cal = icalendar.Calendar.from_ical(result)
        assert "METHOD" not in cal

    @override_settings(CALENDAR_ITIP_ENABLED=True)
    def test_enabled_adds_method(self):
        result = self._prepare(SAMPLE_ICS, method="REQUEST")
        cal = icalendar.Calendar.from_ical(result)
        assert str(cal["METHOD"]) == "REQUEST"

    @override_settings(CALENDAR_ITIP_ENABLED=True)
    def test_enabled_updates_existing_method(self):
        result = self._prepare(_make_ics_with_method("CANCEL"), method="REQUEST")
        cal = icalendar.Calendar.from_ical(result)
        assert str(cal["METHOD"]) == "REQUEST"


@override_settings(
    CALDAV_URL="http://caldav:80",
    CALDAV_OUTBOUND_API_KEY="test-api-key",
    CALDAV_INBOUND_API_KEY="test-inbound-key",
    APP_URL="http://localhost:8921",
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
)
class TestRSVPEndToEndFlow(TestCase):
    """
    Integration test: scheduling callback sends email → extract RSVP links
    → follow link → verify event is updated.

    This tests the full flow from CalDAV scheduling callback to RSVP response,
    using Django's in-memory email backend to intercept sent emails.
    """

    def setUp(self):
        self.factory = RequestFactory()
        self.rsvp_view = RSVPView.as_view()

    def test_email_to_rsvp_accept_flow(self):
        """
        1. CalDAV scheduling callback sends an invitation email
        2. Extract RSVP accept link from the email HTML
        3. Follow the RSVP link
        4. Verify the event PARTSTAT is updated to ACCEPTED
        """
        # Step 1: Send invitation via the CalendarInvitationService
        service = CalendarInvitationService()
        success = service.send_invitation(
            sender_email="alice@example.com",
            recipient_email="bob@example.com",
            method="REQUEST",
            icalendar_data=SAMPLE_ICS,
        )
        assert success is True
        assert len(mail.outbox) == 1

        sent_email = mail.outbox[0]
        assert "bob@example.com" in sent_email.to

        # Step 2: Extract RSVP accept link from email HTML
        html_body = None
        for alternative in sent_email.alternatives:
            if alternative[1] == "text/html":
                html_body = alternative[0]
                break
        assert html_body is not None, "Email should have an HTML body"

        # Find the accept link (green button with "Accepter")
        accept_match = re.search(r'<a\s+href="([^"]*action=accepted[^"]*)"', html_body)
        assert accept_match is not None, "Email HTML should contain an RSVP accept link"
        accept_url = accept_match.group(1)
        # Unescape HTML entities
        accept_url = accept_url.replace("&amp;", "&")

        # Step 3: Parse the URL and extract token + action
        parsed = urlparse(accept_url)
        params = parse_qs(parsed.query)
        assert "token" in params
        assert params["action"] == ["accepted"]

        # Step 4: Follow the RSVP link (mock CalDAV interactions)
        with (
            patch.object(CalDAVHTTPClient, "find_event_by_uid") as mock_find,
            patch.object(CalDAVHTTPClient, "put_event") as mock_put,
        ):
            mock_find.return_value = (
                SAMPLE_ICS,
                "/api/v1.0/caldav/calendars/alice%40example.com/cal/event.ics",
            )
            mock_put.return_value = True

            request = self.factory.get(
                "/rsvp/",
                {"token": params["token"][0], "action": "accepted"},
            )
            response = self.rsvp_view(request)

        # Step 5: Verify success
        assert response.status_code == 200
        content = response.content.decode()
        assert "accepted the invitation" in content

        # Verify CalDAV was called with the right data
        mock_find.assert_called_once_with("alice@example.com", "test-uid-123")
        mock_put.assert_called_once()
        put_data = mock_put.call_args[0][2]
        assert "PARTSTAT=ACCEPTED" in put_data

    def test_email_to_rsvp_decline_flow(self):
        """Same flow but for declining an invitation."""
        service = CalendarInvitationService()
        service.send_invitation(
            sender_email="alice@example.com",
            recipient_email="bob@example.com",
            method="REQUEST",
            icalendar_data=SAMPLE_ICS,
        )
        assert len(mail.outbox) == 1

        html_body = next(
            alt[0] for alt in mail.outbox[0].alternatives if alt[1] == "text/html"
        )

        decline_match = re.search(r'<a\s+href="([^"]*action=declined[^"]*)"', html_body)
        assert decline_match is not None
        decline_url = decline_match.group(1).replace("&amp;", "&")

        parsed = urlparse(decline_url)
        params = parse_qs(parsed.query)

        with (
            patch.object(CalDAVHTTPClient, "find_event_by_uid") as mock_find,
            patch.object(CalDAVHTTPClient, "put_event") as mock_put,
        ):
            mock_find.return_value = (SAMPLE_ICS, "/path/to/event.ics")
            mock_put.return_value = True

            request = self.factory.get(
                "/rsvp/",
                {"token": params["token"][0], "action": "declined"},
            )
            response = self.rsvp_view(request)

        assert response.status_code == 200
        assert "declined the invitation" in response.content.decode()
        assert "PARTSTAT=DECLINED" in mock_put.call_args[0][2]

    def test_email_contains_all_three_rsvp_links(self):
        """Verify the email contains accept, tentative, and decline links."""
        service = CalendarInvitationService()
        service.send_invitation(
            sender_email="alice@example.com",
            recipient_email="bob@example.com",
            method="REQUEST",
            icalendar_data=SAMPLE_ICS,
        )

        html_body = next(
            alt[0] for alt in mail.outbox[0].alternatives if alt[1] == "text/html"
        )

        for action in ("accepted", "tentative", "declined"):
            match = re.search(rf'<a\s+href="([^"]*action={action}[^"]*)"', html_body)
            assert match is not None, (
                f"Email should contain an RSVP link for action={action}"
            )

    def test_cancel_email_has_no_rsvp_links(self):
        """Cancel emails should NOT contain any RSVP links."""
        service = CalendarInvitationService()
        service.send_invitation(
            sender_email="alice@example.com",
            recipient_email="bob@example.com",
            method="CANCEL",
            icalendar_data=SAMPLE_ICS,
        )
        assert len(mail.outbox) == 1

        html_body = next(
            alt[0] for alt in mail.outbox[0].alternatives if alt[1] == "text/html"
        )
        assert "action=accepted" not in html_body
        assert "action=declined" not in html_body

    @patch.object(CalDAVHTTPClient, "find_event_by_uid")
    def test_rsvp_link_for_past_event_fails(self, mock_find):
        """RSVP link for a past event should return an error."""
        service = CalendarInvitationService()
        service.send_invitation(
            sender_email="alice@example.com",
            recipient_email="bob@example.com",
            method="REQUEST",
            icalendar_data=SAMPLE_ICS,
        )

        html_body = next(
            alt[0] for alt in mail.outbox[0].alternatives if alt[1] == "text/html"
        )
        accept_match = re.search(r'<a\s+href="([^"]*action=accepted[^"]*)"', html_body)
        accept_url = accept_match.group(1).replace("&amp;", "&")
        parsed = urlparse(accept_url)
        params = parse_qs(parsed.query)

        # The event is in the past
        mock_find.return_value = (SAMPLE_ICS_PAST, "/path/to/event.ics")

        request = self.factory.get(
            "/rsvp/",
            {"token": params["token"][0], "action": "accepted"},
        )
        response = self.rsvp_view(request)

        assert response.status_code == 400
        assert "already passed" in response.content.decode().lower()
