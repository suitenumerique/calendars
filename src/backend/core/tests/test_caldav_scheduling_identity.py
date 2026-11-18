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

from caldav.lib.error import AuthorizationError
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

    def test_event_of_other_identity_keeps_scheduling(self, callbacks):
        """Another client puts a mailbox meeting in the personal calendar. A
        new date still sends a REQUEST from the mailbox, and a delete still
        sends a CANCEL."""
        user = factories.UserFactory(email=f"user-{secrets.token_hex(4)}@{DOMAIN}")
        organizer = f"organizer-{secrets.token_hex(4)}@{DOMAIN}"
        _add_mailbox_calendar(user, organizer)
        service = CalendarService()
        personal_url = service._calendar_url(
            service.create_calendar(user, name="Personal")
        )
        client = service._get_client(user)
        external = f"external-{secrets.token_hex(4)}@external-{DOMAIN}"
        data = _event(f"identity-{secrets.token_hex(6)}", organizer, external)

        event = client.calendar(url=personal_url).save_event(data)
        _wait_for_callbacks(callbacks, expected_count=1)
        callbacks["requests"].clear()

        data = re.sub(r"DTSTART:\S+", "DTSTART:20990101T100000Z", data)
        event.data = re.sub(r"DTEND:\S+", "DTEND:20990101T110000Z", data)
        event.save()
        _wait_for_callbacks(callbacks, expected_count=1)
        assert _methods(callbacks) == [
            ("REQUEST", f"mailto:{organizer}", f"mailto:{external}")
        ]

        callbacks["requests"].clear()
        event.delete()
        _wait_for_callbacks(callbacks, expected_count=1)
        assert _methods(callbacks) == [
            ("CANCEL", f"mailto:{organizer}", f"mailto:{external}")
        ]


def _move(client, event, calendar_url):
    """Move the event to the calendar and return the new URL and response."""
    target = f"{calendar_url.rstrip('/')}/{str(event.url).rsplit('/', 1)[-1]}"
    resp = client.request(str(event.url), "MOVE", "", {"Destination": target})
    return target, resp


def _series(uid, organizer, attendees, sequences=(0, 0)):
    """Return a series whose second occurrence alone has the attendees."""
    stamp = datetime.now().strftime("%Y%m%dT%H%M%SZ")
    guests = "".join(
        f"ATTENDEE;PARTSTAT=NEEDS-ACTION:mailto:{a}\r\n" for a in attendees
    )
    return (
        "BEGIN:VCALENDAR\r\nVERSION:2.0\r\nPRODID:-//Test//Identity//EN\r\n"
        f"BEGIN:VEVENT\r\nUID:{uid}\r\nDTSTAMP:{stamp}\r\nSEQUENCE:{sequences[0]}\r\n"
        "DTSTART:20990101T100000Z\r\nDTEND:20990101T110000Z\r\n"
        "RRULE:FREQ=DAILY;COUNT=10\r\nSUMMARY:Series\r\n"
        f"ORGANIZER:mailto:{organizer}\r\nEND:VEVENT\r\n"
        f"BEGIN:VEVENT\r\nUID:{uid}\r\nDTSTAMP:{stamp}\r\nSEQUENCE:{sequences[1]}\r\n"
        "RECURRENCE-ID:20990102T100000Z\r\n"
        "DTSTART:20990102T100000Z\r\nDTEND:20990102T110000Z\r\nSUMMARY:Series\r\n"
        f"ORGANIZER:mailto:{organizer}\r\n{guests}END:VEVENT\r\n"
        "END:VCALENDAR\r\n"
    )


def _sequence(callback):
    """Return the highest SEQUENCE of a scheduling message."""
    return max(int(n) for n in re.findall(r"SEQUENCE:(\d+)", callback["body"]))


@pytest.mark.django_db
@pytest.mark.xdist_group("caldav")
class TestMoveChangesOrganizer:
    """A move of a meeting to a calendar with another identity changes the
    organizer."""

    def test_move_to_personal_calendar_changes_organizer(self, callbacks):
        """The user moves a mailbox meeting to the personal calendar. The
        user becomes the organizer, the mailbox accepts, and the attendee
        receives the update from the user."""
        user = factories.UserFactory(email=f"user-{secrets.token_hex(4)}@{DOMAIN}")
        organizer = f"organizer-{secrets.token_hex(4)}@{DOMAIN}"
        organizer_url = _add_mailbox_calendar(user, organizer)
        service = CalendarService()
        personal_url = service._calendar_url(
            service.create_calendar(user, name="Personal")
        )
        client = service._get_client(user)
        external = f"external-{secrets.token_hex(4)}@external-{DOMAIN}"

        event = client.calendar(url=organizer_url).save_event(
            _event(f"identity-{secrets.token_hex(6)}", organizer, external)
        )
        _wait_for_callbacks(callbacks, expected_count=1)
        callbacks["requests"].clear()

        target, resp = _move(client, event, personal_url)
        assert resp.status == 201
        _wait_for_callbacks(callbacks, expected_count=1)
        assert _methods(callbacks) == [
            ("REQUEST", f"mailto:{user.email}", f"mailto:{external}")
        ]

        data = client.calendar(url=personal_url).event_by_url(target).data
        assert f"ORGANIZER:mailto:{user.email}" in data
        assert re.search(rf"ATTENDEE;PARTSTAT=ACCEPTED:mailto:{organizer}", data)
        assert "SEQUENCE:1" in data

        callbacks["requests"].clear()
        client.calendar(url=personal_url).event_by_url(target).delete()
        _wait_for_callbacks(callbacks, expected_count=2)
        assert sorted(_methods(callbacks)) == [
            ("CANCEL", f"mailto:{user.email}", f"mailto:{external}"),
            ("CANCEL", f"mailto:{user.email}", f"mailto:{organizer}"),
        ]

    def test_move_to_attendee_calendar_changes_organizer(self, callbacks):
        """The user moves a mailbox meeting that invites the user to the
        personal calendar. The user is no longer an attendee, and a new date
        sends a REQUEST from the user."""
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
        data = data.replace(
            "END:VEVENT",
            f"ATTENDEE;PARTSTAT=ACCEPTED:mailto:{user.email}\r\nEND:VEVENT",
        )

        event = client.calendar(url=organizer_url).save_event(data)
        _wait_for_callbacks(callbacks, expected_count=2)
        callbacks["requests"].clear()

        target, resp = _move(client, event, personal_url)
        assert resp.status == 201
        _wait_for_callbacks(callbacks, expected_count=1)
        callbacks["requests"].clear()

        moved = client.calendar(url=personal_url).event_by_url(target)
        assert f"ATTENDEE;PARTSTAT=ACCEPTED:mailto:{user.email}" not in moved.data
        data = re.sub(r"DTSTART:\S+", "DTSTART:20990101T100000Z", moved.data)
        moved.data = re.sub(r"DTEND:\S+", "DTEND:20990101T110000Z", data)
        moved.save()
        _wait_for_callbacks(callbacks, expected_count=2)
        assert sorted(_methods(callbacks)) == [
            ("REQUEST", f"mailto:{user.email}", f"mailto:{external}"),
            ("REQUEST", f"mailto:{user.email}", f"mailto:{organizer}"),
        ]

    def test_attendee_copy_cannot_move_to_other_identity(self, callbacks):
        """The user cannot move an attendee copy to a calendar with another
        identity, even when this identity is also an attendee."""
        user = factories.UserFactory(email=f"user-{secrets.token_hex(4)}@{DOMAIN}")
        attendee = f"attendee-{secrets.token_hex(4)}@{DOMAIN}"
        attendee_url = _add_mailbox_calendar(user, attendee)
        service = CalendarService()
        personal_url = service._calendar_url(
            service.create_calendar(user, name="Personal")
        )
        client = service._get_client(user)
        external = f"external-{secrets.token_hex(4)}@external-{DOMAIN}"

        data = _event(
            f"identity-{secrets.token_hex(6)}", external, attendee, "ACCEPTED"
        )
        data = data.replace("END:VEVENT", f"ATTENDEE:mailto:{user.email}\r\nEND:VEVENT")

        copy = client.calendar(url=attendee_url).save_event(data)
        _wait_for_callbacks(callbacks, expected_count=1)
        callbacks["requests"].clear()

        with pytest.raises(AuthorizationError):
            _move(client, copy, personal_url)
        time.sleep(1)
        assert not callbacks["requests"]

    def test_move_with_same_identity_sends_nothing(self, callbacks):
        """A mailbox meeting in a personal calendar moves to another personal
        calendar. The identity does not change, so the organizer stays and
        nothing is sent."""
        user = factories.UserFactory(email=f"user-{secrets.token_hex(4)}@{DOMAIN}")
        organizer = f"organizer-{secrets.token_hex(4)}@{DOMAIN}"
        _add_mailbox_calendar(user, organizer)
        service = CalendarService()
        first_url = service._calendar_url(service.create_calendar(user, name="First"))
        second_url = service._calendar_url(service.create_calendar(user, name="Second"))
        client = service._get_client(user)
        external = f"external-{secrets.token_hex(4)}@external-{DOMAIN}"

        event = client.calendar(url=first_url).save_event(
            _event(f"identity-{secrets.token_hex(6)}", organizer, external)
        )
        _wait_for_callbacks(callbacks, expected_count=1)
        callbacks["requests"].clear()

        target, resp = _move(client, event, second_url)
        assert resp.status == 201
        time.sleep(1)
        assert not callbacks["requests"]
        data = client.calendar(url=second_url).event_by_url(target).data
        assert f"ORGANIZER:mailto:{organizer}" in data

    @pytest.mark.parametrize("override_first", [False, True])
    def test_move_series_with_guests_on_override_changes_organizer(
        self, callbacks, override_first
    ):
        """A mailbox series has guests on one occurrence only. A move to the
        personal calendar still changes the organizer, whatever the order of
        the components, and a delete sends a CANCEL to the guests."""
        user = factories.UserFactory(email=f"user-{secrets.token_hex(4)}@{DOMAIN}")
        organizer = f"organizer-{secrets.token_hex(4)}@{DOMAIN}"
        organizer_url = _add_mailbox_calendar(user, organizer)
        service = CalendarService()
        personal_url = service._calendar_url(
            service.create_calendar(user, name="Personal")
        )
        client = service._get_client(user)
        external = f"external-{secrets.token_hex(4)}@external-{DOMAIN}"
        uid = f"identity-{secrets.token_hex(6)}"
        stamp = datetime.now().strftime("%Y%m%dT%H%M%SZ")
        master = (
            "BEGIN:VEVENT\r\n"
            f"UID:{uid}\r\nDTSTAMP:{stamp}\r\n"
            "DTSTART:20990101T100000Z\r\nDTEND:20990101T110000Z\r\n"
            "RRULE:FREQ=DAILY;COUNT=10\r\nSUMMARY:Series\r\n"
            f"ORGANIZER:mailto:{organizer}\r\n"
            "END:VEVENT\r\n"
        )
        override = (
            "BEGIN:VEVENT\r\n"
            f"UID:{uid}\r\nDTSTAMP:{stamp}\r\n"
            "RECURRENCE-ID:20990105T100000Z\r\n"
            "DTSTART:20990105T100000Z\r\nDTEND:20990105T110000Z\r\n"
            "SUMMARY:Series\r\n"
            f"ORGANIZER:mailto:{organizer}\r\n"
            f"ATTENDEE;PARTSTAT=ACCEPTED:mailto:{user.email}\r\n"
            f"ATTENDEE;PARTSTAT=NEEDS-ACTION;RSVP=TRUE:mailto:{external}\r\n"
            "END:VEVENT\r\n"
        )
        data = (
            "BEGIN:VCALENDAR\r\nVERSION:2.0\r\nPRODID:-//Test//Identity//EN\r\n"
            f"{override + master if override_first else master + override}"
            "END:VCALENDAR\r\n"
        )

        # The caldav library cannot save an override that comes first.
        url = f"{organizer_url.rstrip('/')}/{uid}.ics"
        resp = client.request(
            url, "PUT", data, {"Content-Type": "text/calendar; charset=utf-8"}
        )
        assert resp.status == 201
        _wait_for_callbacks(callbacks, expected_count=2)
        callbacks["requests"].clear()

        event = client.calendar(url=organizer_url).event_by_url(url)
        target, resp = _move(client, event, personal_url)
        assert resp.status == 201
        _wait_for_callbacks(callbacks, expected_count=1)
        assert _methods(callbacks) == [
            ("REQUEST", f"mailto:{user.email}", f"mailto:{external}")
        ]

        moved = client.calendar(url=personal_url).event_by_url(target)
        assert f"ORGANIZER:mailto:{organizer}" not in moved.data
        callbacks["requests"].clear()
        moved.delete()
        _wait_for_callbacks(callbacks, expected_count=2)
        assert sorted(_methods(callbacks)) == [
            ("CANCEL", f"mailto:{user.email}", f"mailto:{external}"),
            ("CANCEL", f"mailto:{user.email}", f"mailto:{organizer}"),
        ]

    def test_repeated_moves_keep_cancel_sequence_above_requests(self, callbacks):
        """A series with guests on one occurrence moves three times between
        the mailbox and the personal calendar, then the user deletes it. Each
        message to the guest has a SEQUENCE above the previous one."""
        user = factories.UserFactory(email=f"user-{secrets.token_hex(4)}@{DOMAIN}")
        organizer = f"organizer-{secrets.token_hex(4)}@{DOMAIN}"
        calendars = [_add_mailbox_calendar(user, organizer)]
        service = CalendarService()
        calendars.append(
            service._calendar_url(service.create_calendar(user, name="Personal"))
        )
        client = service._get_client(user)
        external = f"external-{secrets.token_hex(4)}@external-{DOMAIN}"
        uid = f"identity-{secrets.token_hex(6)}"

        url = f"{calendars[0].rstrip('/')}/{uid}.ics"
        resp = client.request(
            url,
            "PUT",
            _series(uid, organizer, [external], sequences=(2, 9)),
            {"Content-Type": "text/calendar; charset=utf-8"},
        )
        assert resp.status == 201
        _wait_for_callbacks(callbacks, expected_count=1)

        for step in range(3):
            event = client.calendar(url=calendars[step % 2]).event_by_url(url)
            url, resp = _move(client, event, calendars[(step + 1) % 2])
            assert resp.status == 201
            _wait_for_callbacks(callbacks, expected_count=step + 2)

        client.calendar(url=calendars[1]).event_by_url(url).delete()
        _wait_for_callbacks(callbacks, expected_count=6)

        to_external = [
            r
            for r in callbacks["requests"]
            if r["headers"].get("X-LS-Recipient") == f"mailto:{external}"
        ]
        methods = [r["headers"].get("X-LS-Method") for r in to_external]
        assert methods == ["REQUEST"] * 4 + ["CANCEL"]
        sequences = [_sequence(r) for r in to_external]
        assert sequences == sorted(set(sequences))
