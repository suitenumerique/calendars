"""API endpoint for polling async task status."""

import logging
import uuid

import dramatiq
from dramatiq.results import ResultFailure, ResultMissing
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from core.task_utils import get_task_progress, get_task_tracking

logger = logging.getLogger(__name__)


class TaskDetailView(APIView):
    """View to retrieve the status of an async task."""

    permission_classes = [IsAuthenticated]

    def get(self, request, task_id):  # noqa: PLR0911  # pylint: disable=too-many-return-statements
        """Get the status of a task."""
        try:
            uuid.UUID(task_id)
        except ValueError:
            return Response(
                {"status": "FAILURE", "result": None, "error": "Not found"},
                status=404,
            )

        tracking = get_task_tracking(task_id)
        if tracking is None:
            return Response(
                {"status": "FAILURE", "result": None, "error": "Not found"},
                status=404,
            )
        if str(request.user.id) != tracking["owner"]:
            return Response(
                {"status": "FAILURE", "result": None, "error": "Forbidden"},
                status=403,
            )

        # Try to fetch the result from dramatiq's result backend
        message = dramatiq.Message(
            queue_name=tracking["queue_name"],
            actor_name=tracking["actor_name"],
            args=(),
            kwargs={},
            options={},
            message_id=task_id,
        )
        try:
            result_data = message.get_result(block=False)
        except ResultMissing:
            result_data = None
        except ResultFailure as exc:
            logger.error("Task %s failed: %s", task_id, exc)
            return Response(
                {
                    "status": "FAILURE",
                    "result": None,
                    "error": "Task failed",
                }
            )

        if result_data is not None:
            resp = {
                "status": "SUCCESS",
                "result": result_data,
                "error": None,
            }
            # Unpack {status, result, error} convention
            if (
                isinstance(result_data, dict)
                and {"status", "result", "error"} <= result_data.keys()
            ):
                resp["status"] = result_data["status"]
                resp["result"] = result_data["result"]
                resp["error"] = result_data["error"]
            return Response(resp)

        # Check for progress data
        progress_data = get_task_progress(task_id)
        if progress_data:
            return Response(
                {
                    "status": "PROGRESS",
                    "result": None,
                    "error": None,
                    "progress": progress_data.get("progress"),
                    "message": progress_data.get("metadata", {}).get("message"),
                    "timestamp": progress_data.get("timestamp"),
                }
            )

        # Default to pending
        return Response(
            {
                "status": "PENDING",
                "result": None,
                "error": None,
            }
        )
