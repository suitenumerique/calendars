"""End-to-end iCal feed tests against real SabreDAV.

These tests do the full round-trip:
    1. Create an ical-feed channel via the public API.
    2. PUT a real event into the underlying calendar via the CalDAV proxy.
    3. GET /ical/{short_id}/{token}/calendar.ics (no authentication).
    4. Assert the served body actually contains the event we wrote.

Without this round-trip, regressions in caldav_path computation, header
forwarding, or SabreDAV's ?export plugin can slip through the unit tests
that mock the CalDAV layer entirely.

Requires: CalDAV server running.
"""

# pylint: disable=no-member

from datetime import datetime, timedelta

from django.core.cache import cache

import pytest
from rest_framework.status import (
    HTTP_200_OK,
    HTTP_201_CREATED,
    HTTP_404_NOT_FOUND,
)
from rest_framework.test import APIClient

from core import factories
from core.entitlements.factory import get_entitlements_backend
from core.models import Channel, uuid_to_urlsafe
from core.services.caldav_service import CalendarService

CHANNELS_URL = "/api/v1.0/channels/"

pytestmark = [
    pytest.mark.django_db,
    pytest.mark.xdist_group("caldav"),
]


@pytest.fixture(autouse=True)
def _local_entitlements(settings):
    """Use local entitlements backend."""
    settings.ENTITLEMENTS_BACKEND = (
        "core.entitlements.backends.local.LocalEntitlementsBackend"
    )
    settings.ENTITLEMENTS_BACKEND_PARAMETERS = {}
    get_entitlements_backend.cache_clear()
    yield
    get_entitlements_backend.cache_clear()


def _ical_url(channel: Channel) -> str:
    """Build the public iCal URL for *channel*."""
    token = channel.encrypted_settings["token"]
    short_id = uuid_to_urlsafe(channel.pk)
    return f"/ical/{short_id}/{token}/calendar.ics"


def _put_event(  # noqa: PLR0913  # pylint: disable=too-many-arguments,too-many-positional-arguments
    client,
    user_email,
    cal_id,
    uid,
    summary,
    days_offset=1,
):
    """PUT a VEVENT into the calendar via the CalDAV proxy."""
    dtstart = datetime.now() + timedelta(days=days_offset)
    dtend = dtstart + timedelta(hours=1)
    ical = (
        "BEGIN:VCALENDAR\r\n"
        "VERSION:2.0\r\n"
        "PRODID:-//Test//Test//EN\r\n"
        "BEGIN:VEVENT\r\n"
        f"UID:{uid}\r\n"
        f"DTSTART:{dtstart.strftime('%Y%m%dT%H%M%SZ')}\r\n"
        f"DTEND:{dtend.strftime('%Y%m%dT%H%M%SZ')}\r\n"
        f"SUMMARY:{summary}\r\n"
        "END:VEVENT\r\n"
        "END:VCALENDAR\r\n"
    )
    return client.generic(
        "PUT",
        f"/caldav/calendars/users/{user_email}/{cal_id}/{uid}.ics",
        data=ical,
        content_type="text/calendar",
    )


def _create_user_with_calendar(name="ical-feed-owner"):
    """Create a user with one real calendar and return (user, client, cal_id)."""
    org = factories.OrganizationFactory(external_id=f"ical-e2e-{name}")
    user = factories.UserFactory(email=f"{name}@ical-e2e.com", organization=org)
    client = APIClient()
    client.force_login(user)
    caldav_path = CalendarService().create_calendar(user, name="My Feed Calendar")
    cal_id = caldav_path.strip("/").split("/")[-1]
    return user, client, cal_id, caldav_path


class TestICalExportRoundTripE2E:
    """Real round-trip from channel creation to ICS body served via /ical/."""

    def test_created_channel_serves_real_event_in_feed(self):
        """Create feed channel, PUT a real event, fetch the public feed,
        assert the event UID and SUMMARY appear in the served body."""
        user, client, cal_id, caldav_path = _create_user_with_calendar("served-feed")

        # 1. Create the ical-feed channel via the public API.
        resp = client.post(
            CHANNELS_URL,
            {
                "name": "Public Feed",
                "type": "ical-feed",
                "caldav_path": caldav_path,
                "calendar_name": "Public Feed",
            },
            format="json",
        )
        assert resp.status_code == HTTP_201_CREATED, resp.content
        channel = Channel.objects.get(pk=resp.data["id"])

        # 2. PUT a real event into the calendar.
        put_resp = _put_event(
            client, user.email, cal_id, "feed-event-served", "Public Feed Meeting"
        )
        assert put_resp.status_code in (200, 201, 204), put_resp.content

        # 3. Fetch the feed unauthenticated.
        anon = APIClient()
        feed_resp = anon.get(_ical_url(channel))

        assert feed_resp.status_code == HTTP_200_OK, (
            f"Public iCal feed should serve event, got {feed_resp.status_code}: "
            f"{feed_resp.content[:500]}"
        )
        body = feed_resp.content.decode("utf-8", errors="ignore")

        # 4. Assert the event we wrote is actually in the response body.
        assert "BEGIN:VCALENDAR" in body
        assert "END:VCALENDAR" in body
        assert "BEGIN:VEVENT" in body, (
            f"Feed body has no VEVENT — proxy/export pipeline broken: {body[:500]}"
        )
        assert "UID:feed-event-served" in body, (
            f"Event UID not in feed body: {body[:500]}"
        )
        assert "SUMMARY:Public Feed Meeting" in body, (
            f"Event SUMMARY not in feed body: {body[:500]}"
        )

    def test_feed_reflects_subsequent_event_added_after_creation(self):
        """A new event PUT after the channel was created shows up in the feed.

        Catches regressions where the feed caches stale state or reads from
        the wrong calendar path.
        """
        user, client, cal_id, caldav_path = _create_user_with_calendar("fresh-feed")

        resp = client.post(
            CHANNELS_URL,
            {
                "name": "Fresh Feed",
                "type": "ical-feed",
                "caldav_path": caldav_path,
            },
            format="json",
        )
        assert resp.status_code == HTTP_201_CREATED
        channel = Channel.objects.get(pk=resp.data["id"])

        # Channel created BEFORE any events exist. Add events after.
        _put_event(client, user.email, cal_id, "first-event-uid", "First Standup")
        _put_event(
            client,
            user.email,
            cal_id,
            "second-event-uid",
            "Second Review",
            days_offset=2,
        )

        anon = APIClient()
        feed_resp = anon.get(_ical_url(channel))
        assert feed_resp.status_code == HTTP_200_OK
        body = feed_resp.content.decode()

        assert body.count("BEGIN:VEVENT") == 2, (
            f"Expected 2 VEVENT blocks, got {body.count('BEGIN:VEVENT')}: {body[:500]}"
        )
        assert "UID:first-event-uid" in body
        assert "UID:second-event-uid" in body
        assert "SUMMARY:First Standup" in body
        assert "SUMMARY:Second Review" in body

    def test_deleted_event_disappears_from_feed(self):
        """DELETE on the underlying calendar removes the event from the feed."""
        user, client, cal_id, caldav_path = _create_user_with_calendar("deleted-feed")

        resp = client.post(
            CHANNELS_URL,
            {
                "name": "Del Feed",
                "type": "ical-feed",
                "caldav_path": caldav_path,
            },
            format="json",
        )
        assert resp.status_code == HTTP_201_CREATED
        channel = Channel.objects.get(pk=resp.data["id"])

        _put_event(client, user.email, cal_id, "doomed-uid", "Doomed Meeting")

        anon = APIClient()
        before = anon.get(_ical_url(channel))
        assert "UID:doomed-uid" in before.content.decode()

        # Delete the event via the proxy
        del_resp = client.generic(
            "DELETE",
            f"/caldav/calendars/users/{user.email}/{cal_id}/doomed-uid.ics",
        )
        assert del_resp.status_code in (200, 204), del_resp.content

        # Force a fresh request — cache key includes channel id, but the
        # rate limiter has its own cache so re-fetch is fine.
        cache.clear()
        anon2 = APIClient()
        after = anon2.get(_ical_url(channel))
        assert after.status_code == HTTP_200_OK
        body = after.content.decode()
        assert "UID:doomed-uid" not in body, (
            f"Deleted event still present in feed: {body[:500]}"
        )

    def test_feed_returns_404_for_inactive_channel(self):
        """A real round-trip 404 path: deactivating the channel rejects the URL
        even though the underlying calendar still exists and has events."""
        user, client, cal_id, caldav_path = _create_user_with_calendar("inactive-feed")

        resp = client.post(
            CHANNELS_URL,
            {
                "name": "Inactive Feed",
                "type": "ical-feed",
                "caldav_path": caldav_path,
            },
            format="json",
        )
        assert resp.status_code == HTTP_201_CREATED
        channel = Channel.objects.get(pk=resp.data["id"])

        _put_event(client, user.email, cal_id, "live-uid", "Live Event")

        # Sanity check: feed works while channel is active.
        anon = APIClient()
        ok_resp = anon.get(_ical_url(channel))
        assert ok_resp.status_code == HTTP_200_OK
        assert "UID:live-uid" in ok_resp.content.decode()

        # Now deactivate.
        Channel.objects.filter(pk=channel.pk).update(is_active=False)

        cache.clear()
        anon2 = APIClient()
        gone = anon2.get(_ical_url(channel))
        assert gone.status_code == HTTP_404_NOT_FOUND

    def test_get_or_create_returns_token_that_serves_the_same_calendar(self):
        """If a feed channel already exists for a path, the API returns the
        existing one. The returned token must still serve the same calendar."""
        user, client, cal_id, caldav_path = _create_user_with_calendar("existing-feed")

        first = client.post(
            CHANNELS_URL,
            {
                "name": "Reusable",
                "type": "ical-feed",
                "caldav_path": caldav_path,
            },
            format="json",
        )
        assert first.status_code == HTTP_201_CREATED

        # Second create returns the same channel (HTTP 200, get-or-create).
        second = client.post(
            CHANNELS_URL,
            {
                "name": "Reusable",
                "type": "ical-feed",
                "caldav_path": caldav_path,
            },
            format="json",
        )
        assert second.status_code == HTTP_200_OK
        assert second.data["id"] == first.data["id"]

        _put_event(client, user.email, cal_id, "round-trip-uid", "Round Trip Event")

        channel = Channel.objects.get(pk=second.data["id"])
        anon = APIClient()
        feed = anon.get(_ical_url(channel))
        assert feed.status_code == HTTP_200_OK
        body = feed.content.decode()
        assert "UID:round-trip-uid" in body
        assert "SUMMARY:Round Trip Event" in body
