"""Task queue utilities.

Provides decorators and helpers that abstract away the underlying task
queue library (currently Dramatiq).  Application code should import from
here instead of importing dramatiq directly.
"""

import json
import logging
from typing import Any, Optional

from django.core.cache import cache
from django.utils import timezone

import dramatiq
from dramatiq.brokers.stub import StubBroker
from dramatiq.middleware import CurrentMessage

logger = logging.getLogger(__name__)

TASK_PROGRESS_CACHE_TIMEOUT = 86400  # 24 hours
TASK_TRACKING_CACHE_TTL = 86400 * 30  # 30 days


# ---------------------------------------------------------------------------
# Task wrapper (Celery-compatible API)
# ---------------------------------------------------------------------------


class Task:
    """Wrapper around a Dramatiq Message with a Celery-like API."""

    def __init__(self, message):
        self._message = message

    @property
    def id(self):
        """Celery-compatible task ID (maps to message_id)."""
        return self._message.message_id

    def track_owner(self, user_id):
        """Register tracking metadata for permission checks."""
        cache.set(
            f"task_tracking:{self.id}",
            json.dumps(
                {
                    "owner": str(user_id),
                    "actor_name": self._message.actor_name,
                    "queue_name": self._message.queue_name,
                }
            ),
            timeout=TASK_TRACKING_CACHE_TTL,
        )

    def __getattr__(self, name):
        return getattr(self._message, name)


class CeleryCompatActor(dramatiq.Actor):
    """Actor subclass that adds a .delay() method returning a Task."""

    def delay(self, *args, **kwargs):
        """Dispatch the task asynchronously, returning a Task wrapper."""
        message = self.send(*args, **kwargs)
        return Task(message)


# ---------------------------------------------------------------------------
# Decorators
# ---------------------------------------------------------------------------


def register_task(*args, **kwargs):
    """Decorator to register a task (wraps dramatiq.actor).

    Usage::

        @register_task(queue="import")
        def my_task(arg):
            ...
    """
    kwargs.setdefault("store_results", True)
    if "queue" in kwargs:
        kwargs.setdefault("queue_name", kwargs.pop("queue"))
    kwargs.setdefault("actor_class", CeleryCompatActor)

    def decorator(fn):
        return dramatiq.actor(fn, **kwargs)

    if args and callable(args[0]):
        return decorator(args[0])
    return decorator


# ---------------------------------------------------------------------------
# Task tracking & progress
# ---------------------------------------------------------------------------


def get_task_tracking(task_id: str) -> Optional[dict]:
    """Get tracking metadata for a task, or None if not found."""
    raw = cache.get(f"task_tracking:{task_id}")
    if raw is None:
        return None
    return json.loads(raw)


def set_task_progress(progress: int, metadata: Optional[dict[str, Any]] = None) -> None:
    """Set the progress of the currently executing task."""
    current_message = CurrentMessage.get_current_message()
    if not current_message:
        logger.warning("set_task_progress called outside of a task")
        return

    task_id = current_message.message_id
    try:
        progress = max(0, min(100, int(progress)))
    except (TypeError, ValueError):
        progress = 0

    cache.set(
        f"task_progress:{task_id}",
        {
            "progress": progress,
            "timestamp": timezone.now().timestamp(),
            "metadata": metadata or {},
        },
        timeout=TASK_PROGRESS_CACHE_TIMEOUT,
    )


def get_task_progress(task_id: str) -> Optional[dict[str, Any]]:
    """Get the progress of a task by ID."""
    return cache.get(f"task_progress:{task_id}")


# ---------------------------------------------------------------------------
# EagerBroker for tests
# ---------------------------------------------------------------------------


class EagerBroker(StubBroker):
    """Broker that executes tasks synchronously (for tests).

    Equivalent to Celery's CELERY_TASK_ALWAYS_EAGER mode.
    Only runs CurrentMessage and Results middleware.
    """

    def enqueue(self, message, *, delay=None):
        from dramatiq.results import Results  # noqa: PLC0415  # pylint: disable=C0415

        actor = self.get_actor(message.actor_name)
        cm = next(
            (m for m in self.middleware if isinstance(m, CurrentMessage)),
            None,
        )
        rm = next((m for m in self.middleware if isinstance(m, Results)), None)
        prev = CurrentMessage.get_current_message() if cm else None
        if cm:
            cm.before_process_message(self, message)
        try:
            result = actor.fn(*message.args, **message.kwargs)
            if rm:
                rm.after_process_message(self, message, result=result)
        finally:
            if cm:
                cm.after_process_message(self, message)
                if prev is not None:
                    cm.before_process_message(self, prev)
        return message
