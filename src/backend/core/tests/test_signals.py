"""Tests for Django signals (CalDAV cleanup on user/org deletion)."""

from unittest import mock

from django.test import TestCase, override_settings

from core import factories
from core.models import Organization, User


@override_settings(
    CALDAV_URL="http://caldav:80",
    CALDAV_INTERNAL_API_KEY="test-internal-key",
    CALDAV_OUTBOUND_API_KEY="test-api-key",
)
class TestDeleteUserCaldavData(TestCase):
    """Tests for the delete_user_caldav_data pre_delete signal."""

    def test_deleting_user_calls_internal_api(self):
        """Deleting a user triggers a DELETE to the SabreDAV internal API."""
        user = factories.UserFactory(email="alice@example.com")

        with mock.patch(
            "core.services.caldav_service.requests.request"
        ) as mock_request:
            mock_response = mock.Mock()
            mock_response.status_code = 200
            mock_request.return_value = mock_response

            user.delete()

        # Verify the internal API was called to clean up CalDAV data
        mock_request.assert_called_once()
        call_kwargs = mock_request.call_args
        assert call_kwargs.kwargs["method"] == "DELETE"
        url = call_kwargs.kwargs.get("url", "")
        assert "internal-api/users/alice@example.com" in url
        headers = call_kwargs.kwargs.get("headers", {})
        assert headers.get("X-Internal-Api-Key") == "test-internal-key"

    def test_deleting_user_without_email_skips_cleanup(self):
        """Users without an email don't trigger CalDAV cleanup."""
        user = factories.UserFactory(email="")

        with mock.patch(
            "core.services.caldav_service.requests.request"
        ) as mock_request:
            user.delete()

        mock_request.assert_not_called()

    @override_settings(CALDAV_INTERNAL_API_KEY="")
    def test_deleting_user_without_api_key_skips_cleanup(self):
        """When CALDAV_INTERNAL_API_KEY is empty, cleanup is skipped."""
        user = factories.UserFactory(email="alice@example.com")

        with mock.patch(
            "core.services.caldav_service.requests.request"
        ) as mock_request:
            user.delete()

        mock_request.assert_not_called()

    def test_deleting_user_handles_http_error_gracefully(self):
        """HTTP errors during cleanup don't prevent user deletion."""
        user = factories.UserFactory(email="alice@example.com")

        with mock.patch(
            "core.services.caldav_service.requests.request",
            side_effect=Exception("Connection refused"),
        ):
            # Should not raise — the signal catches exceptions
            user.delete()

        assert not User.objects.filter(email="alice@example.com").exists()


@override_settings(
    CALDAV_URL="http://caldav:80",
    CALDAV_INTERNAL_API_KEY="test-internal-key",
    CALDAV_OUTBOUND_API_KEY="test-api-key",
)
class TestDeleteOrganizationCaldavData(TestCase):
    """Tests for the delete_organization_caldav_data pre_delete signal."""

    def test_deleting_org_cleans_up_all_members(self):
        """Deleting an org triggers CalDAV cleanup for every member.

        cleanup_organization_caldav_data calls DELETE for each member,
        then members.delete() triggers the user pre_delete signal which
        also calls DELETE. So we expect 2 calls per member = 4 total.
        """
        org = factories.OrganizationFactory(external_id="doomed-org")
        factories.UserFactory(email="alice@example.com", organization=org)
        factories.UserFactory(email="bob@example.com", organization=org)

        with mock.patch(
            "core.services.caldav_service.requests.request"
        ) as mock_request:
            mock_response = mock.Mock()
            mock_response.status_code = 200
            mock_request.return_value = mock_response

            org.delete()

        # 2 members x 2 DELETE calls each (org cleanup + user signal)
        assert mock_request.call_count == 4
        urls = [call.kwargs.get("url", "") for call in mock_request.call_args_list]
        assert any("alice@example.com" in url for url in urls)
        assert any("bob@example.com" in url for url in urls)

    def test_deleting_org_deletes_member_users(self):
        """Deleting an org also deletes member Django User objects."""
        org = factories.OrganizationFactory(external_id="doomed-org")
        factories.UserFactory(email="alice@example.com", organization=org)
        factories.UserFactory(email="bob@example.com", organization=org)

        with mock.patch(
            "core.services.caldav_service.requests.request"
        ) as mock_request:
            mock_response = mock.Mock()
            mock_response.status_code = 200
            mock_request.return_value = mock_response

            org.delete()

        assert not User.objects.filter(email="alice@example.com").exists()
        assert not User.objects.filter(email="bob@example.com").exists()
        assert not Organization.objects.filter(external_id="doomed-org").exists()

    def test_deleting_org_with_no_members(self):
        """Deleting an org with no members succeeds without errors."""
        org = factories.OrganizationFactory(external_id="empty-org")

        with mock.patch(
            "core.services.caldav_service.requests.request"
        ) as mock_request:
            org.delete()

        mock_request.assert_not_called()

    def test_deleting_org_continues_after_member_cleanup_failure(self):
        """If CalDAV cleanup fails for one member, other members still cleaned up."""
        org = factories.OrganizationFactory(external_id="doomed-org")
        factories.UserFactory(email="alice@example.com", organization=org)
        factories.UserFactory(email="bob@example.com", organization=org)

        call_count = 0

        def side_effect(**kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise Exception("Network error")  # pylint: disable=broad-exception-raised
            resp = mock.Mock()
            resp.status_code = 200
            return resp

        with mock.patch(
            "core.services.caldav_service.requests.request",
            side_effect=side_effect,
        ):
            org.delete()

        # Org cleanup: 2 calls (1 fails, 1 succeeds), then user signal: 2 more
        assert call_count == 4
        assert not Organization.objects.filter(external_id="doomed-org").exists()

    @override_settings(CALDAV_INTERNAL_API_KEY="")
    def test_deleting_org_without_api_key_skips_caldav_cleanup(self):
        """When CALDAV_INTERNAL_API_KEY is empty, CalDAV cleanup is skipped."""
        org = factories.OrganizationFactory(external_id="org-nokey")
        factories.UserFactory(email="alice@example.com", organization=org)

        with mock.patch(
            "core.services.caldav_service.requests.request"
        ) as mock_request:
            # Without the API key, the signal skips CalDAV cleanup but
            # also doesn't delete members, so PROTECT FK blocks deletion.
            try:
                org.delete()
            except Exception:  # noqa: BLE001  # pylint: disable=broad-exception-caught
                pass

        mock_request.assert_not_called()
