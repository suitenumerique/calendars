"""Background tasks for the calendars core application."""

# pylint: disable=import-outside-toplevel

import logging
from dataclasses import asdict

from core.services.import_service import ICSImportService
from core.task_utils import register_task, set_task_progress

logger = logging.getLogger(__name__)


@register_task(queue="import")
def import_events_task(user_id, caldav_path, ics_data_hex):
    """Import events from ICS data in the background.

    Parameters are kept JSON-serialisable:
    - user_id: pk of the User who triggered the import
    - caldav_path: target CalDAV calendar path
    - ics_data_hex: ICS bytes encoded as hex string
    """
    from core.models import User  # noqa: PLC0415

    set_task_progress(0, {"message": "Starting import..."})

    try:
        user = User.objects.get(pk=user_id)
    except User.DoesNotExist:
        logger.error("import_events_task: user %s not found", user_id)
        return {
            "status": "FAILURE",
            "result": None,
            "error": "User not found",
        }

    ics_data = bytes.fromhex(ics_data_hex)
    set_task_progress(10, {"message": "Sending to CalDAV server..."})

    service = ICSImportService()
    result = service.import_events(user, caldav_path, ics_data)

    set_task_progress(100, {"message": "Import complete"})

    result_dict = asdict(result)
    return {
        "status": "SUCCESS",
        "result": result_dict,
        "error": None,
    }
