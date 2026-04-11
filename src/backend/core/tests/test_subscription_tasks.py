"""Tests for subscription sync Dramatiq tasks."""

# pylint: disable=missing-class-docstring,unused-argument

from unittest.mock import patch

from django.utils import timezone

import pytest

from core.factories import UserFactory
from core.models import Channel
from core.tasks import sync_all_subscriptions


@pytest.mark.django_db
class TestSyncAllSubscriptions:
    @patch("core.tasks.sync_one_subscription")
    def test_dispatches_for_active_channels(self, mock_sync_one):
        """Should dispatch one task per active subscription channel."""
        user = UserFactory()
        Channel.objects.create(
            name="Sub 1",
            type="ical-subscription",
            user=user,
            is_active=True,
            caldav_path="/calendars/users/test@test.com/uuid1/",
            settings={
                "source_url": "https://example.com/1.ics",
                "sync_interval": 300,
                "last_sync_status": "ok",
                "error_count": 0,
            },
        )
        Channel.objects.create(
            name="Sub 2",
            type="ical-subscription",
            user=user,
            is_active=True,
            caldav_path="/calendars/users/test@test.com/uuid2/",
            settings={
                "source_url": "https://example.com/2.ics",
                "sync_interval": 300,
                "last_sync_status": "ok",
                "error_count": 0,
            },
        )

        result = sync_all_subscriptions()
        assert result == 2
        assert mock_sync_one.send_with_options.call_count == 2

    @patch("core.tasks.sync_one_subscription")
    def test_skips_inactive_channels(self, mock_sync_one):
        """Should not dispatch for inactive channels."""
        user = UserFactory()
        Channel.objects.create(
            name="Inactive Sub",
            type="ical-subscription",
            user=user,
            is_active=False,
            caldav_path="/calendars/users/test@test.com/uuid/",
            settings={
                "source_url": "https://example.com/cal.ics",
                "sync_interval": 300,
                "error_count": 3,
            },
        )

        result = sync_all_subscriptions()
        assert result == 0
        assert mock_sync_one.send_with_options.call_count == 0

    @patch("core.tasks.sync_one_subscription")
    def test_skips_non_subscription_channels(self, mock_sync_one):
        """Should not dispatch for ical-feed or caldav channels."""
        user = UserFactory()
        Channel.objects.create(
            name="Feed",
            type="ical-feed",
            user=user,
            is_active=True,
            caldav_path="/calendars/users/test@test.com/uuid/",
            settings={"role": "reader"},
        )

        result = sync_all_subscriptions()
        assert result == 0

    @patch("core.tasks.sync_one_subscription")
    def test_skips_recently_synced(self, mock_sync_one):
        """Should skip channels that were synced recently."""
        user = UserFactory()
        Channel.objects.create(
            name="Recent Sub",
            type="ical-subscription",
            user=user,
            is_active=True,
            caldav_path="/calendars/users/test@test.com/uuid/",
            settings={
                "source_url": "https://example.com/cal.ics",
                "sync_interval": 300,
                "last_sync_at": timezone.now().isoformat(),
                "error_count": 0,
            },
        )

        result = sync_all_subscriptions()
        assert result == 0
