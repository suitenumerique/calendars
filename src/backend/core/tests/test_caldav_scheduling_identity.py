"""Tests for the scheduling identity of a calendar.

A user can write to several mailbox calendars. Each calendar speaks for one
address only. A reply from one calendar must go to the organizer, even when
the user can also write to the calendar of the organizer.
"""

# pylint: disable=protected-access

import re
import secrets
import threading
import time
from datetime import datetime, timedelta

import pytest

from core import factories
from core.services.caldav_service import CalDAVHTTPClient, CalendarService
from core.tests.test_caldav_scheduling import _wait_for_callbacks, create_test_server

DOMAIN = "identity-test.com"


def _add_mailbox_calendar(user, mailbox_email):
    """Create a mailbox calendar, give the user write access, return its URL."""
    http = CalDAVHTTPClient()
    resp = http.internal_request(
        "POST",
        user,
        "internal-api/calendars/",
        json={
            "email": mailbox_email,
            "name": mailbox_email,
            "calendar_user_type": "MAILBOX",
            "org_id": str(user.organization_id),
        },
    )
    assert resp.status_code in (200, 201), resp.text

    dav = http.get_dav_client(user)
    before = {str(c.url) for c in dav.principal().calendars()}
    resp = http.internal_request(
        "POST",
        user,
        "internal-api/sync-mailbox-acls/",
        json={
            "shares": [
                {
                    "user_email": user.email,
                    "mailbox_email": mailbox_email,
                    "calendar_uri": "default",
                    "privilege": "read-write",
                }
            ],
            "full_sync_users": [],
        },
    )
    assert resp.status_code == 200, resp.text
    new = [str(c.url) for c in dav.principal().calendars() if str(c.url) not in before]
    assert len(new) == 1, new
    return new[0]


def _event(uid, organizer, attendee, partstat="NEEDS-ACTION"):
    dtstart = datetime.now() + timedelta(days=3)
    dtend = dtstart + timedelta(hours=1)
    return (
        "BEGIN:VCALENDAR\r\n"
        "VERSION:2.0\r\n"
        "PRODID:-//Test//Identity//EN\r\n"
        "BEGIN:VEVENT\r\n"
        f"UID:{uid}\r\n"
        f"DTSTART:{dtstart.strftime('%Y%m%dT%H%M%SZ')}\r\n"
        f"DTEND:{dtend.strftime('%Y%m%dT%H%M%SZ')}\r\n"
        f"DTSTAMP:{datetime.now().strftime('%Y%m%dT%H%M%SZ')}\r\n"
        "SUMMARY:Identity test\r\n"
        f"ORGANIZER:mailto:{organizer}\r\n"
        f"ATTENDEE;PARTSTAT={partstat};RSVP=TRUE:mailto:{attendee}\r\n"
        "END:VEVENT\r\n"
        "END:VCALENDAR\r\n"
    )


@pytest.fixture(name="callbacks")
def fixture_callbacks():
    """Run the scheduling callback server and return the received callbacks."""
    server, _port, callback_data = create_test_server()
    threading.Thread(target=server.serve_forever, daemon=True).start()
    time.sleep(0.5)
    yield callback_data
    server.shutdown()
    server.server_close()


def _methods(callback_data):
    return [
        (
            r["headers"].get("X-LS-Method"),
            r["headers"].get("X-LS-Sender"),
            r["headers"].get("X-LS-Recipient"),
        )
        for r in callback_data["requests"]
    ]


@pytest.mark.django_db
@pytest.mark.xdist_group("caldav")
class TestCalendarSchedulingIdentity:
    """Scheduling uses the identity of the calendar, not of the user."""

    @staticmethod
    def _accept_in(client, calendar_url, uid, organizer, attendee):
        """Put an accepted copy of the event in the calendar, as Messages does."""
        return client.calendar(url=calendar_url).save_event(
            _event(uid, organizer, attendee, partstat="ACCEPTED")
        )

    def test_accept_in_mailbox_calendar_replies_to_other_mailbox(self, callbacks):
        """The user writes to the organizer mailbox and to the attendee
        mailbox. An accept in the attendee calendar sends a REPLY to the
        organizer, and not a new REQUEST to the attendees."""
        user = factories.UserFactory(email=f"user-{secrets.token_hex(4)}@{DOMAIN}")
        organizer = f"organizer-{secrets.token_hex(4)}@{DOMAIN}"
        attendee = f"attendee-{secrets.token_hex(4)}@{DOMAIN}"
        organizer_url = _add_mailbox_calendar(user, organizer)
        attendee_url = _add_mailbox_calendar(user, attendee)
        client = CalendarService()._get_client(user)
        uid = f"identity-{secrets.token_hex(6)}"

        client.calendar(url=organizer_url).save_event(_event(uid, organizer, attendee))
        _wait_for_callbacks(callbacks, expected_count=1)
        assert _methods(callbacks) == [
            ("REQUEST", f"mailto:{organizer}", f"mailto:{attendee}")
        ]

        callbacks["requests"].clear()
        self._accept_in(client, attendee_url, uid, organizer, attendee)
        _wait_for_callbacks(callbacks, expected_count=1)

        assert _methods(callbacks) == [
            ("REPLY", f"mailto:{attendee}", f"mailto:{organizer}")
        ]

    def test_accept_in_mailbox_with_capitals_replies(self, callbacks):
        """A mailbox address with capitals still sends a REPLY."""
        user = factories.UserFactory(email=f"user-{secrets.token_hex(4)}@{DOMAIN}")
        organizer = f"organizer-{secrets.token_hex(4)}@external-{DOMAIN}"
        attendee = f"Attendee-{secrets.token_hex(4)}@{DOMAIN}"
        attendee_url = _add_mailbox_calendar(user, attendee)
        client = CalendarService()._get_client(user)

        self._accept_in(
            client,
            attendee_url,
            f"identity-{secrets.token_hex(6)}",
            organizer,
            attendee,
        )
        _wait_for_callbacks(callbacks, expected_count=1)

        assert [(m, r) for m, _s, r in _methods(callbacks)] == [
            ("REPLY", f"mailto:{organizer}")
        ]

    def test_accept_in_personal_calendar_replies_to_mailbox(self, callbacks):
        """The user writes to the organizer mailbox. An accept in the
        personal calendar of the user sends a REPLY to the mailbox."""
        user = factories.UserFactory(email=f"user-{secrets.token_hex(4)}@{DOMAIN}")
        organizer = f"organizer-{secrets.token_hex(4)}@{DOMAIN}"
        organizer_url = _add_mailbox_calendar(user, organizer)
        service = CalendarService()
        personal_url = service._calendar_url(
            service.create_calendar(user, name="Personal")
        )
        client = service._get_client(user)
        uid = f"identity-{secrets.token_hex(6)}"

        client.calendar(url=organizer_url).save_event(
            _event(uid, organizer, user.email)
        )
        _wait_for_callbacks(callbacks, expected_count=1)
        callbacks["requests"].clear()

        self._accept_in(client, personal_url, uid, organizer, user.email)
        _wait_for_callbacks(callbacks, expected_count=1)

        assert _methods(callbacks) == [
            ("REPLY", f"mailto:{user.email}", f"mailto:{organizer}")
        ]

    def test_delete_in_mailbox_calendar_declines(self, callbacks):
        """A delete of the accepted copy in the attendee calendar sends a
        REPLY to the organizer, and not a CANCEL to the attendees."""
        user = factories.UserFactory(email=f"user-{secrets.token_hex(4)}@{DOMAIN}")
        organizer = f"organizer-{secrets.token_hex(4)}@{DOMAIN}"
        attendee = f"attendee-{secrets.token_hex(4)}@{DOMAIN}"
        organizer_url = _add_mailbox_calendar(user, organizer)
        attendee_url = _add_mailbox_calendar(user, attendee)
        client = CalendarService()._get_client(user)
        uid = f"identity-{secrets.token_hex(6)}"

        client.calendar(url=organizer_url).save_event(_event(uid, organizer, attendee))
        _wait_for_callbacks(callbacks, expected_count=1)
        callbacks["requests"].clear()

        copy = self._accept_in(client, attendee_url, uid, organizer, attendee)
        _wait_for_callbacks(callbacks, expected_count=1)
        callbacks["requests"].clear()

        copy.delete()
        _wait_for_callbacks(callbacks, expected_count=1)

        assert _methods(callbacks) == [
            ("REPLY", f"mailto:{attendee}", f"mailto:{organizer}")
        ]
        assert "PARTSTAT=DECLINED" in callbacks["requests"][0]["body"]

    def test_organizer_mailbox_calendar_still_sends_requests(self, callbacks):
        """An event in a mailbox calendar, with the mailbox as organizer,
        still sends the invitations."""
        user = factories.UserFactory(email=f"user-{secrets.token_hex(4)}@{DOMAIN}")
        organizer = f"organizer-{secrets.token_hex(4)}@{DOMAIN}"
        organizer_url = _add_mailbox_calendar(user, organizer)
        client = CalendarService()._get_client(user)
        external = f"external-{secrets.token_hex(4)}@external-{DOMAIN}"

        client.calendar(url=organizer_url).save_event(
            _event(f"identity-{secrets.token_hex(6)}", organizer, external)
        )
        _wait_for_callbacks(callbacks, expected_count=1)

        assert _methods(callbacks) == [
            ("REQUEST", f"mailto:{organizer}", f"mailto:{external}")
        ]

    def test_moved_event_keeps_scheduling(self, callbacks):
        """The user moves a mailbox event to the personal calendar. A new
        date still sends a REQUEST from the mailbox, and a delete still sends
        a CANCEL."""
        user = factories.UserFactory(email=f"user-{secrets.token_hex(4)}@{DOMAIN}")
        organizer = f"organizer-{secrets.token_hex(4)}@{DOMAIN}"
        organizer_url = _add_mailbox_calendar(user, organizer)
        service = CalendarService()
        personal_url = service._calendar_url(
            service.create_calendar(user, name="Personal")
        )
        client = service._get_client(user)
        external = f"external-{secrets.token_hex(4)}@external-{DOMAIN}"
        data = _event(f"identity-{secrets.token_hex(6)}", organizer, external)

        event = client.calendar(url=organizer_url).save_event(data)
        _wait_for_callbacks(callbacks, expected_count=1)
        target = f"{personal_url.rstrip('/')}/{str(event.url).rsplit('/', 1)[-1]}"
        resp = client.request(str(event.url), "MOVE", "", {"Destination": target})
        assert resp.status in (201, 204)
        _wait_for_callbacks(callbacks, expected_count=2, timeout=1.0)
        assert len(callbacks["requests"]) == 1
        callbacks["requests"].clear()

        moved = client.calendar(url=personal_url).event_by_url(target)
        data = re.sub(r"DTSTART:\S+", "DTSTART:20990101T100000Z", data)
        moved.data = re.sub(r"DTEND:\S+", "DTEND:20990101T110000Z", data)
        moved.save()
        _wait_for_callbacks(callbacks, expected_count=1)
        assert _methods(callbacks) == [
            ("REQUEST", f"mailto:{organizer}", f"mailto:{external}")
        ]

        callbacks["requests"].clear()
        moved.delete()
        _wait_for_callbacks(callbacks, expected_count=1)
        assert _methods(callbacks) == [
            ("CANCEL", f"mailto:{organizer}", f"mailto:{external}")
        ]
