#!/usr/bin/env python
# pylint: disable=import-outside-toplevel
"""
Background task worker with sensible queue defaults.

Usage:
    python worker.py                          # Process all queues
    python worker.py --queues=import,default  # Process only specific queues
    python worker.py --exclude=sync           # Process all except sync
    python worker.py --concurrency=4          # Set worker concurrency
    python worker.py -v 2                     # Verbose logging

Queue priority order (highest to lowest):
    1. default  - General / high-priority tasks
    2. import   - File import processing
    3. sync     - Background sync tasks
"""

import argparse
import logging
import multiprocessing
import os
import sys

# Workaround for Dramatiq + Python 3.14: forkserver (the new default) breaks
# Dramatiq's Canteen shared-memory mechanism, causing worker processes to never
# consume messages. See https://github.com/Bogdanp/dramatiq/issues/701
# Must be set before dramatiq.cli.main() spawns worker processes.
multiprocessing.set_start_method("fork", force=True)

# Setup Django before importing the task runner
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "calendars.settings")
os.environ.setdefault("DJANGO_CONFIGURATION", "Development")

# Override $APP if set by the host (e.g. Scalingo)
os.environ.pop("APP", None)

from configurations.importer import install  # pylint: disable=wrong-import-position

install(check_options=True)

import django  # pylint: disable=wrong-import-position

django.setup()

# Queue definitions in priority order
ALL_QUEUES = ["default", "import", "sync"]
DEFAULT_QUEUES = ALL_QUEUES


def get_default_concurrency():
    """Get default concurrency from environment variables."""
    env_value = os.environ.get("WORKER_CONCURRENCY")
    if env_value:
        try:
            return int(env_value)
        except ValueError:
            return None
    return None


def discover_tasks_modules():
    """Discover task modules the same way django_dramatiq does."""
    import importlib  # noqa: PLC0415  # pylint: disable=wrong-import-position

    from django.apps import (  # noqa: PLC0415  # pylint: disable=wrong-import-position
        apps,
    )
    from django.conf import (  # noqa: PLC0415  # pylint: disable=wrong-import-position
        settings,
    )
    from django.utils.module_loading import (  # noqa: PLC0415  # pylint: disable=wrong-import-position
        module_has_submodule,
    )

    task_module_names = settings.DRAMATIQ_AUTODISCOVER_MODULES
    modules = ["django_dramatiq.setup"]

    for conf in apps.get_app_configs():
        if conf.name == "django_dramatiq":
            module = conf.name + ".tasks"
            importlib.import_module(module)
            logging.getLogger(__name__).info("Discovered tasks module: %r", module)
            modules.append(module)
        else:
            for task_module in task_module_names:
                if module_has_submodule(conf.module, task_module):
                    module = conf.name + "." + task_module
                    importlib.import_module(module)
                    logging.getLogger(__name__).info(
                        "Discovered tasks module: %r", module
                    )
                    modules.append(module)

    return modules


def parse_args():
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description="Start a background task worker.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--queues",
        "-Q",
        type=str,
        default=None,
        help=(
            "Comma-separated list of queues to process. "
            f"Default: {','.join(DEFAULT_QUEUES)}"
        ),
    )
    parser.add_argument(
        "--exclude",
        "-X",
        type=str,
        default=None,
        help="Comma-separated list of queues to exclude.",
    )
    parser.add_argument(
        "--concurrency",
        "-c",
        type=int,
        default=get_default_concurrency(),
        help="Number of worker processes. Default: WORKER_CONCURRENCY env var.",
    )
    parser.add_argument(
        "--verbosity",
        "-v",
        type=int,
        default=1,
        help="Verbosity level (0=minimal, 1=normal, 2=verbose). Default: 1",
    )
    return parser.parse_args()


def main():
    """Start the background task worker."""
    logger = logging.getLogger(__name__)
    args = parse_args()

    # Determine which queues to process
    if args.queues:
        queues = [q.strip() for q in args.queues.split(",")]
        invalid = set(queues) - set(ALL_QUEUES)
        if invalid:
            sys.stderr.write(f"Error: Unknown queues: {', '.join(invalid)}\n")
            sys.stderr.write(f"Valid queues are: {', '.join(ALL_QUEUES)}\n")
            sys.exit(1)
    else:
        queues = DEFAULT_QUEUES.copy()

    # Apply exclusions
    if args.exclude:
        exclude = [q.strip() for q in args.exclude.split(",")]
        invalid_exclude = set(exclude) - set(ALL_QUEUES)
        if invalid_exclude:
            sys.stderr.write(
                f"Error: Unknown queues to exclude: {', '.join(invalid_exclude)}\n"
            )
            sys.stderr.write(f"Valid queues are: {', '.join(ALL_QUEUES)}\n")
            sys.exit(1)
        queues = [q for q in queues if q not in exclude]

    if not queues:
        sys.stderr.write("Error: No queues to process after exclusions.\n")
        sys.exit(1)

    # Discover task modules
    tasks_modules = discover_tasks_modules()

    # Build dramatiq CLI arguments and call main() directly.
    # This avoids rundramatiq's os.execvp which replaces the process and
    # discards our multiprocessing.set_start_method("fork") workaround.
    dramatiq_args = [
        "dramatiq",
        "--path",
        ".",
        "--processes",
        str(args.concurrency or 4),
        "--threads",
        "1",
        "--worker-shutdown-timeout",
        "600000",
    ]

    if args.verbosity > 1:
        dramatiq_args.append("-v")

    dramatiq_args.extend(tasks_modules)
    dramatiq_args.extend(["--queues", *queues])

    logger.info("Starting worker with queues: %s", ", ".join(queues))

    import dramatiq.cli  # noqa: PLC0415  # pylint: disable=wrong-import-position

    sys.argv = dramatiq_args
    dramatiq.cli.main()


if __name__ == "__main__":
    main()
