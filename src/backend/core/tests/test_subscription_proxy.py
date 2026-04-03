"""Tests for CalDAV proxy read-only enforcement on subscription calendars."""

import pytest

from core.api.viewsets_caldav import CalDAVProxyView
from core.factories import UserFactory
from core.models import Channel


@pytest.fixture()
def user():
    return UserFactory(email="test@example.com")


@pytest.fixture()
def subscription_channel(user):
    return Channel.objects.create(
        name="External Calendar",
        type="ical-subscription",
        user=user,
        is_active=True,
        caldav_path="/calendars/users/test@example.com/sub-uuid/",
        settings={
            "source_url": "https://example.com/cal.ics",
            "sync_interval": 300,
            "last_sync_status": "ok",
            "error_count": 0,
        },
    )


@pytest.mark.django_db
class TestSubscriptionReadOnly:
    def test_blocks_put_on_subscription_calendar(self, user, subscription_channel):
        """PUT to a subscription calendar event should return 403."""
        result = CalDAVProxyView._check_subscription_readonly(
            user,
            "calendars/users/test@example.com/sub-uuid/event-1.ics",
            "PUT",
        )
        assert result is not None
        assert result.status_code == 403

    def test_blocks_delete_on_subscription_calendar(self, user, subscription_channel):
        """DELETE on a subscription calendar event should return 403."""
        result = CalDAVProxyView._check_subscription_readonly(
            user,
            "calendars/users/test@example.com/sub-uuid/event-1.ics",
            "DELETE",
        )
        assert result is not None
        assert result.status_code == 403

    def test_allows_regular_calendar_put(self, user, subscription_channel):
        """PUT to a regular calendar should not be blocked."""
        result = CalDAVProxyView._check_subscription_readonly(
            user,
            "calendars/users/test@example.com/regular-uuid/event-1.ics",
            "PUT",
        )
        assert result is None

    def test_allows_when_no_subscriptions(self, user):
        """When user has no subscription channels, writes should pass."""
        result = CalDAVProxyView._check_subscription_readonly(
            user,
            "calendars/users/test@example.com/any-uuid/event-1.ics",
            "PUT",
        )
        assert result is None

    def test_inactive_subscription_still_blocks_writes(self, user):
        """Inactive (stopped) subscription calendars must remain read-only."""
        Channel.objects.create(
            name="Inactive Sub",
            type="ical-subscription",
            user=user,
            is_active=False,
            caldav_path="/calendars/users/test@example.com/inactive-uuid/",
            settings={
                "source_url": "https://example.com/cal.ics",
                "error_count": 3,
            },
        )
        result = CalDAVProxyView._check_subscription_readonly(
            user,
            "calendars/users/test@example.com/inactive-uuid/event-1.ics",
            "PUT",
        )
        assert result is not None
        assert result.status_code == 403

    def test_move_blocked_on_subscription(self, user, subscription_channel):
        """MOVE on a subscription calendar should return 403."""
        result = CalDAVProxyView._check_subscription_readonly(
            user,
            "calendars/users/test@example.com/sub-uuid/event-1.ics",
            "MOVE",
        )
        assert result is not None
        assert result.status_code == 403

    def test_proppatch_blocked_on_subscription(self, user, subscription_channel):
        """PROPPATCH on a subscription calendar event should return 403."""
        result = CalDAVProxyView._check_subscription_readonly(
            user,
            "calendars/users/test@example.com/sub-uuid/event-1.ics",
            "PROPPATCH",
        )
        assert result is not None
        assert result.status_code == 403

    def test_post_blocked_on_subscription(self, user, subscription_channel):
        """POST on a subscription calendar should return 403."""
        result = CalDAVProxyView._check_subscription_readonly(
            user,
            "calendars/users/test@example.com/sub-uuid/event-1.ics",
            "POST",
        )
        assert result is not None
        assert result.status_code == 403
