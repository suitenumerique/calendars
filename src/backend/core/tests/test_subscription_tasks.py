"""Tests for subscription background tasks.

``sync_all_subscriptions`` queries SabreDAV's internal API for the due
list; ``cleanup_orphan_subscriptions`` wraps the cleanup endpoint.
Both are exercised with the HTTP client mocked — no SabreDAV needed.
"""

# pylint: disable=missing-class-docstring,missing-function-docstring

from unittest.mock import MagicMock, patch

from core.tasks import cleanup_orphan_subscriptions, sync_all_subscriptions


def _mock_response(status_code: int, json_payload: dict) -> MagicMock:
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = json_payload
    resp.text = str(json_payload)
    return resp


class TestSyncAllSubscriptions:
    @patch("core.tasks.sync_one_subscription")
    @patch("core.services.caldav_service.CalDAVHTTPClient.internal_request")
    def test_dispatches_one_task_per_due_subscription(
        self, mock_request, mock_sync_one
    ):
        mock_request.return_value = _mock_response(
            200,
            {
                "subscriptions": [
                    {"subscription_id": "aabbccdd11223344", "sync_interval": 300},
                    {"subscription_id": "00ff00ff00ff00ff", "sync_interval": 60},
                ]
            },
        )

        dispatched = sync_all_subscriptions()
        assert dispatched == 2
        assert mock_sync_one.send_with_options.call_count == 2

    @patch("core.tasks.sync_one_subscription")
    @patch("core.services.caldav_service.CalDAVHTTPClient.internal_request")
    def test_skips_entries_without_id(self, mock_request, mock_sync_one):
        mock_request.return_value = _mock_response(
            200,
            {"subscriptions": [{"sync_interval": 300}]},
        )
        assert sync_all_subscriptions() == 0
        mock_sync_one.send_with_options.assert_not_called()

    @patch("core.tasks.sync_one_subscription")
    @patch("core.services.caldav_service.CalDAVHTTPClient.internal_request")
    def test_returns_zero_on_api_error(self, mock_request, mock_sync_one):
        mock_request.return_value = _mock_response(500, {"error": "boom"})
        assert sync_all_subscriptions() == 0
        mock_sync_one.send_with_options.assert_not_called()


class TestCleanupOrphanSubscriptions:
    @patch("core.services.caldav_service.CalDAVHTTPClient.internal_request")
    def test_returns_deleted_count(self, mock_request):
        mock_request.return_value = _mock_response(
            200, {"deleted_count": 4, "candidate_count": 5}
        )
        assert cleanup_orphan_subscriptions() == 4

    @patch("core.services.caldav_service.CalDAVHTTPClient.internal_request")
    def test_returns_zero_on_error(self, mock_request):
        mock_request.return_value = _mock_response(500, {"error": "boom"})
        assert cleanup_orphan_subscriptions() == 0
