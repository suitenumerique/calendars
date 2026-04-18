"""Management command to run the subscription sync scheduler.

Dispatches sync_all_subscriptions every 60 seconds (configurable via
SUBSCRIPTION_SCHEDULER_INTERVAL env var). Designed to run as a
long-lived process in a dedicated Docker service.
"""

# pylint: disable=import-outside-toplevel

import logging
import os
import signal
import time

from django.core.management.base import BaseCommand

logger = logging.getLogger(__name__)


def _get_scheduler_interval() -> int:
    raw = os.environ.get("SUBSCRIPTION_SCHEDULER_INTERVAL", "60")
    try:
        interval = int(raw)
    except (TypeError, ValueError):
        logger.warning(
            "Invalid SUBSCRIPTION_SCHEDULER_INTERVAL=%r, falling back to 60s",
            raw,
        )
        return 60
    return max(interval, 1)


SCHEDULER_INTERVAL = _get_scheduler_interval()


class Command(BaseCommand):
    """Run the subscription sync scheduler loop."""

    help = "Run the subscription sync scheduler (dispatches sync tasks every 60s)"

    def handle(self, *args, **options):
        # Local import avoids loading Dramatiq at Django startup.
        from core.tasks import sync_all_subscriptions  # noqa: PLC0415

        running = True

        def _shutdown(signum, _frame):
            nonlocal running
            running = False
            logger.info(
                "Subscription scheduler received signal %s, shutting down...", signum
            )

        signal.signal(signal.SIGTERM, _shutdown)
        signal.signal(signal.SIGINT, _shutdown)

        self.stdout.write("Starting subscription scheduler...")
        logger.info("Subscription scheduler started (interval=%ds)", SCHEDULER_INTERVAL)

        while running:
            try:
                sync_all_subscriptions.send()
            except Exception:  # pylint: disable=broad-exception-caught
                logger.exception("Failed to dispatch sync_all_subscriptions")

            time.sleep(SCHEDULER_INTERVAL)

        logger.info("Subscription scheduler stopped.")
