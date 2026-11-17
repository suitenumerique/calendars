"""Tests for the task system: task functions, polling endpoint, and async dispatch."""

# pylint: disable=import-outside-toplevel

import uuid
from unittest.mock import MagicMock, patch

from django.core.cache import cache

import pytest
from rest_framework.test import APIClient

from core import factories
from core.services.import_service import ImportResult

pytestmark = pytest.mark.django_db


# ---------------------------------------------------------------------------
# Test import_events_task function directly
# ---------------------------------------------------------------------------


class TestImportEventsTask:
    """Test the import_events_task function itself (via EagerBroker)."""

    @patch("core.tasks.ICSImportService")
    def test_task_returns_success_result(self, mock_service_cls):
        """Task should return a SUCCESS dict with import results."""
        from core.tasks import import_events_task  # noqa: PLC0415

        mock_service = mock_service_cls.return_value
        mock_service.import_events.return_value = ImportResult(
            total_events=3,
            imported_count=3,
            duplicate_count=0,
            skipped_count=0,
            errors=[],
        )

        user = factories.UserFactory()
        ics_data = b"BEGIN:VCALENDAR\r\nEND:VCALENDAR"
        caldav_path = f"/calendars/users/{user.email}/{uuid.uuid4()}/"

        result = import_events_task(str(user.id), caldav_path, ics_data.hex())

        assert result["status"] == "SUCCESS"
        assert result["result"]["total_events"] == 3
        assert result["result"]["imported_count"] == 3
        assert result["error"] is None
        mock_service.import_events.assert_called_once_with(user, caldav_path, ics_data)

    @patch("core.tasks.ICSImportService")
    def test_task_user_not_found(self, mock_service_cls):
        """Task should return FAILURE if user does not exist."""
        from core.tasks import import_events_task  # noqa: PLC0415

        result = import_events_task(
            str(uuid.uuid4()),  # non-existent user
            "/calendars/users/nobody@example.com/cal/",
            b"dummy".hex(),
        )

        assert result["status"] == "FAILURE"
        assert "User not found" in result["error"]
        mock_service_cls.return_value.import_events.assert_not_called()

    @patch("core.tasks.set_task_progress")
    @patch("core.tasks.ICSImportService")
    def test_task_reports_progress(self, mock_service_cls, mock_progress):
        """Task should call set_task_progress at 0%, 10%, and 100%."""
        from core.tasks import import_events_task  # noqa: PLC0415

        mock_service_cls.return_value.import_events.return_value = ImportResult(
            total_events=1,
            imported_count=1,
            duplicate_count=0,
            skipped_count=0,
            errors=[],
        )

        user = factories.UserFactory()
        import_events_task(
            str(user.id),
            f"/calendars/users/{user.email}/{uuid.uuid4()}/",
            b"data".hex(),
        )

        progress_values = [call.args[0] for call in mock_progress.call_args_list]
        assert progress_values == [0, 10, 100]

    @patch("core.tasks.ICSImportService")
    def test_task_via_delay(self, mock_service_cls):
        """Calling .delay() should dispatch and return a Task with an id."""
        from core.tasks import import_events_task  # noqa: PLC0415

        mock_service_cls.return_value.import_events.return_value = ImportResult(
            total_events=1,
            imported_count=1,
            duplicate_count=0,
            skipped_count=0,
            errors=[],
        )

        user = factories.UserFactory()
        task = import_events_task.delay(
            str(user.id),
            f"/calendars/users/{user.email}/{uuid.uuid4()}/",
            b"data".hex(),
        )

        assert task.id is not None
        assert isinstance(task.id, str)


# ---------------------------------------------------------------------------
# Test TaskDetailView polling endpoint
# ---------------------------------------------------------------------------


class TestTaskDetailView:
    """Test the /api/v1.0/tasks/<task_id>/ polling endpoint."""

    TASK_URL = "/api/v1.0/tasks/{task_id}/"

    def test_requires_authentication(self):
        """Unauthenticated requests should be rejected."""
        client = APIClient()
        response = client.get(self.TASK_URL.format(task_id="some-id"))
        assert response.status_code == 401

    def test_task_not_found(self):
        """Unknown task_id should return 404."""
        user = factories.UserFactory()
        client = APIClient()
        client.force_login(user)

        response = client.get(self.TASK_URL.format(task_id=str(uuid.uuid4())))
        assert response.status_code == 404
        assert response.json()["status"] == "FAILURE"

    def test_task_forbidden_for_other_user(self):
        """Users cannot poll tasks they don't own."""
        owner = factories.UserFactory()
        other = factories.UserFactory()

        # Simulate a tracked task owned by `owner`
        task_id = str(uuid.uuid4())
        import json  # noqa: PLC0415

        cache.set(
            f"task_tracking:{task_id}",
            json.dumps(
                {
                    "owner": str(owner.id),
                    "actor_name": "import_events_task",
                    "queue_name": "import",
                }
            ),
        )

        client = APIClient()
        client.force_login(other)

        response = client.get(self.TASK_URL.format(task_id=task_id))
        assert response.status_code == 403

    @patch("core.tasks.ICSImportService")
    def test_poll_completed_task(self, mock_service_cls):
        """Polling a completed task should return SUCCESS with results."""
        from core.tasks import import_events_task  # noqa: PLC0415

        expected_result = ImportResult(
            total_events=5,
            imported_count=4,
            duplicate_count=1,
            skipped_count=0,
            errors=[],
        )
        mock_service_cls.return_value.import_events.return_value = expected_result

        user = factories.UserFactory()
        caldav_path = f"/calendars/users/{user.email}/{uuid.uuid4()}/"

        # Dispatch via .delay() — EagerBroker runs it synchronously
        task = import_events_task.delay(str(user.id), caldav_path, b"data".hex())
        task.track_owner(user.id)

        client = APIClient()
        client.force_login(user)

        response = client.get(self.TASK_URL.format(task_id=task.id))
        assert response.status_code == 200

        data = response.json()
        assert data["status"] == "SUCCESS"
        assert data["result"]["total_events"] == 5
        assert data["result"]["imported_count"] == 4
        assert data["error"] is None

    @patch("core.tasks.ICSImportService")
    def test_poll_task_owner_matches(self, mock_service_cls):
        """Only the task owner can poll the task."""
        from core.tasks import import_events_task  # noqa: PLC0415

        mock_service_cls.return_value.import_events.return_value = ImportResult(
            total_events=1,
            imported_count=1,
            duplicate_count=0,
            skipped_count=0,
            errors=[],
        )

        owner = factories.UserFactory()
        other = factories.UserFactory()
        caldav_path = f"/calendars/users/{owner.email}/{uuid.uuid4()}/"

        task = import_events_task.delay(str(owner.id), caldav_path, b"data".hex())
        task.track_owner(owner.id)

        client = APIClient()

        # Other user gets 403
        client.force_login(other)
        response = client.get(self.TASK_URL.format(task_id=task.id))
        assert response.status_code == 403

        # Owner gets 200
        client.force_login(owner)
        response = client.get(self.TASK_URL.format(task_id=task.id))
        assert response.status_code == 200
        assert response.json()["status"] == "SUCCESS"


# ---------------------------------------------------------------------------
# Test API → task dispatch integration
# ---------------------------------------------------------------------------


class TestImportAPITaskDispatch:
    """Test that the import API correctly dispatches a task."""

    IMPORT_URL = "/api/v1.0/calendars/import-events/"

    @patch("core.tasks.import_events_task")
    def test_api_calls_delay_with_correct_args(self, mock_task):
        """The API should call .delay() with user_id, caldav_path, ics_hex."""
        mock_message = MagicMock()
        mock_message.id = str(uuid.uuid4())
        mock_task.delay.return_value = mock_message

        user = factories.UserFactory(email="dispatch@example.com")
        caldav_path = f"/calendars/users/{user.email}/some-uuid/"

        client = APIClient()
        client.force_login(user)

        from django.core.files.uploadedfile import (  # noqa: PLC0415
            SimpleUploadedFile,
        )

        ics_file = SimpleUploadedFile(
            "events.ics",
            b"BEGIN:VCALENDAR\r\nEND:VCALENDAR",
            content_type="text/calendar",
        )
        response = client.post(
            self.IMPORT_URL,
            {"file": ics_file, "caldav_path": caldav_path},
            format="multipart",
        )

        assert response.status_code == 202
        assert response.json()["task_id"] == mock_message.id

        mock_task.delay.assert_called_once()
        call_args = mock_task.delay.call_args.args
        assert call_args[0] == str(user.id)
        assert call_args[1] == caldav_path
        # Third arg is ics_data as hex
        assert bytes.fromhex(call_args[2]) == b"BEGIN:VCALENDAR\r\nEND:VCALENDAR"

    @patch("core.tasks.import_events_task")
    def test_api_returns_202_with_task_id(self, mock_task):
        """Successful dispatch should return HTTP 202 with task_id."""
        mock_message = MagicMock()
        mock_message.id = "test-task-id-123"
        mock_task.delay.return_value = mock_message

        user = factories.UserFactory(email="dispatch202@example.com")
        caldav_path = f"/calendars/users/{user.email}/cal-uuid/"

        client = APIClient()
        client.force_login(user)

        from django.core.files.uploadedfile import (  # noqa: PLC0415
            SimpleUploadedFile,
        )

        ics_file = SimpleUploadedFile(
            "events.ics",
            b"BEGIN:VCALENDAR\r\nEND:VCALENDAR",
            content_type="text/calendar",
        )
        response = client.post(
            self.IMPORT_URL,
            {"file": ics_file, "caldav_path": caldav_path},
            format="multipart",
        )

        assert response.status_code == 202
        data = response.json()
        assert data["task_id"] == "test-task-id-123"


# ---------------------------------------------------------------------------
# Full round-trip: API dispatch → EagerBroker → poll result
# ---------------------------------------------------------------------------


class TestImportFullRoundTrip:
    """Full integration: POST import → task runs (EagerBroker) → poll result."""

    IMPORT_URL = "/api/v1.0/calendars/import-events/"
    TASK_URL = "/api/v1.0/tasks/{task_id}/"

    @patch.object(
        __import__(
            "core.services.import_service", fromlist=["ICSImportService"]
        ).ICSImportService,
        "import_events",
    )
    def test_full_round_trip(self, mock_import):
        """POST import → EagerBroker runs task → poll returns SUCCESS."""
        mock_import.return_value = ImportResult(
            total_events=2,
            imported_count=2,
            duplicate_count=0,
            skipped_count=0,
            errors=[],
        )

        user = factories.UserFactory(email="roundtrip@example.com")
        caldav_path = f"/calendars/users/{user.email}/cal-uuid/"

        client = APIClient()
        client.force_login(user)

        from django.core.files.uploadedfile import (  # noqa: PLC0415
            SimpleUploadedFile,
        )

        ics_file = SimpleUploadedFile(
            "events.ics",
            b"BEGIN:VCALENDAR\r\nEND:VCALENDAR",
            content_type="text/calendar",
        )

        # Step 1: POST triggers task dispatch
        response = client.post(
            self.IMPORT_URL,
            {"file": ics_file, "caldav_path": caldav_path},
            format="multipart",
        )
        assert response.status_code == 202
        task_id = response.json()["task_id"]

        # Step 2: Poll for result
        poll_response = client.get(self.TASK_URL.format(task_id=task_id))
        assert poll_response.status_code == 200
        data = poll_response.json()
        assert data["status"] == "SUCCESS"
        assert data["result"]["total_events"] == 2
        assert data["result"]["imported_count"] == 2
        assert data["error"] is None

    @patch.object(
        __import__(
            "core.services.import_service", fromlist=["ICSImportService"]
        ).ICSImportService,
        "import_events",
    )
    def test_full_round_trip_with_errors(self, mock_import):
        """Task that returns partial failure should surface errors via poll."""
        mock_import.return_value = ImportResult(
            total_events=3,
            imported_count=1,
            duplicate_count=0,
            skipped_count=2,
            errors=["Event A", "Event B"],
        )

        user = factories.UserFactory(email="roundtrip-err@example.com")
        caldav_path = f"/calendars/users/{user.email}/cal-uuid/"

        client = APIClient()
        client.force_login(user)

        from django.core.files.uploadedfile import (  # noqa: PLC0415
            SimpleUploadedFile,
        )

        ics_file = SimpleUploadedFile(
            "events.ics",
            b"BEGIN:VCALENDAR\r\nEND:VCALENDAR",
            content_type="text/calendar",
        )

        response = client.post(
            self.IMPORT_URL,
            {"file": ics_file, "caldav_path": caldav_path},
            format="multipart",
        )
        assert response.status_code == 202
        task_id = response.json()["task_id"]

        poll_response = client.get(self.TASK_URL.format(task_id=task_id))
        assert poll_response.status_code == 200
        data = poll_response.json()
        assert data["status"] == "SUCCESS"
        assert data["result"]["skipped_count"] == 2
        assert data["result"]["errors"] == ["Event A", "Event B"]
