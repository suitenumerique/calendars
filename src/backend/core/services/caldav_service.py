"""Services for CalDAV integration with DAViCal."""

import logging
from datetime import date, datetime, timedelta
from typing import Optional
from uuid import uuid4

from django.conf import settings
from django.utils import timezone

import psycopg

from caldav import DAVClient
from caldav.lib.error import NotFoundError
from core.models import Calendar

logger = logging.getLogger(__name__)


class DAViCalClient:
    """
    Client for communicating with DAViCal CalDAV server using the caldav library.
    """

    def __init__(self):
        self.base_url = getattr(settings, "DAVICAL_URL", "http://davical:80")
        self.timeout = 30

    def _get_client(self, user) -> DAVClient:
        """
        Get a CalDAV client for the given user.

        DAViCal uses X-Forwarded-User header for authentication. The caldav
        library requires username/password for Basic Auth, but DAViCal users have
        password '*' (external auth). We pass the X-Forwarded-User header directly
        to the DAVClient constructor.
        """
        # DAViCal base URL - the caldav library will discover the principal
        caldav_url = f"{self.base_url}/caldav.php/"

        return DAVClient(
            url=caldav_url,
            username=user.email,
            password="",  # Empty password - DAViCal uses X-Forwarded-User header
            timeout=self.timeout,
            headers={
                "X-Forwarded-User": user.email,
            },
        )

    def ensure_user_exists(self, user) -> None:
        """
        Ensure the user exists in DAViCal's database.
        Creates the user if they don't exist.
        """
        # Connect to shared calendars database (public schema)
        default_db = settings.DATABASES["default"]
        db_name = default_db.get("NAME", "calendars")

        # Get password - handle SecretValue objects
        password = default_db.get("PASSWORD", "pass")
        if hasattr(password, "value"):
            password = password.value

        # Connect to calendars database
        conn = psycopg.connect(
            host=default_db.get("HOST", "localhost"),
            port=default_db.get("PORT", 5432),
            dbname=db_name,
            user=default_db.get("USER", "pgroot"),
            password=password,
        )

        try:
            with conn.cursor() as cursor:
                # Check if user exists (in public schema)
                cursor.execute(
                    "SELECT user_no FROM usr WHERE lower(username) = lower(%s)",
                    [user.email],
                )
                if cursor.fetchone():
                    # User already exists
                    return

                # Create user in DAViCal (public schema)
                # Use email as username, password '*' means external auth
                # Get user's full name or use email prefix
                fullname = (
                    getattr(user, "full_name", None)
                    or getattr(user, "get_full_name", lambda: None)()
                    or user.email.split("@")[0]
                )

                cursor.execute(
                    """
                    INSERT INTO usr (username, email, fullname, active, password)
                    VALUES (%s, %s, %s, true, '*')
                    ON CONFLICT (lower(username)) DO NOTHING
                    RETURNING user_no
                    """,
                    [user.email, user.email, fullname],
                )
                result = cursor.fetchone()
                if result:
                    user_no = result[0]
                    logger.info(
                        "Created DAViCal user: %s (user_no: %s)", user.email, user_no
                    )

                    # Also create a principal record for the user (public schema)
                    # DAViCal needs both usr and principal records
                    # Principal type 1 is for users
                    type_id = 1

                    cursor.execute(
                        """
                        INSERT INTO principal (type_id, user_no, displayname)
                        SELECT %s, %s, %s
                        WHERE NOT EXISTS (SELECT 1 FROM principal WHERE user_no = %s)
                        RETURNING principal_id
                        """,
                        [type_id, user_no, fullname, user_no],
                    )
                    principal_result = cursor.fetchone()
                    if principal_result:
                        logger.info(
                            "Created DAViCal principal: %s (principal_id: %s)",
                            user.email,
                            principal_result[0],
                        )
                else:
                    logger.warning("User %s already exists in DAViCal", user.email)
                conn.commit()
        finally:
            conn.close()

    def create_calendar(self, user, calendar_name: str, calendar_id: str) -> str:
        """
        Create a new calendar in DAViCal for the given user.
        Returns the DAViCal path for the calendar.
        """
        # Ensure user exists first
        self.ensure_user_exists(user)

        client = self._get_client(user)
        principal = client.principal()

        try:
            # Create calendar using caldav library
            calendar = principal.make_calendar(name=calendar_name)

            # DAViCal calendar path format: /caldav.php/{username}/{calendar_id}/
            # The caldav library returns a URL object, convert to string and extract path
            calendar_url = str(calendar.url)
            # Extract path from full URL
            if calendar_url.startswith(self.base_url):
                path = calendar_url[len(self.base_url) :]
            else:
                # Fallback: construct path manually based on DAViCal's structure
                # DAViCal creates calendars with a specific path structure
                path = f"/caldav.php/{user.email}/{calendar_id}/"

            logger.info("Created calendar in DAViCal: %s at %s", calendar_name, path)
            return path
        except Exception as e:
            logger.error("Failed to create calendar in DAViCal: %s", str(e))
            raise

    def get_events(
        self,
        user,
        calendar_path: str,
        start: Optional[datetime] = None,
        end: Optional[datetime] = None,
    ) -> list:
        """
        Get events from a calendar within a time range.
        Returns list of event dictionaries with parsed data.
        """
        # Ensure user exists first
        self.ensure_user_exists(user)

        # Default to current month if no range specified
        if start is None:
            start = timezone.now().replace(day=1, hour=0, minute=0, second=0)
        if end is None:
            end = start + timedelta(days=31)

        client = self._get_client(user)

        # Get calendar by URL
        calendar_url = f"{self.base_url}{calendar_path}"
        calendar = client.calendar(url=calendar_url)

        try:
            # Search for events in the date range
            # Convert datetime to date for search if needed
            start_date = start.date() if isinstance(start, datetime) else start
            end_date = end.date() if isinstance(end, datetime) else end

            events = calendar.search(
                event=True,
                start=start_date,
                end=end_date,
                expand=True,  # Expand recurring events
            )

            # Parse events into dictionaries
            parsed_events = []
            for event in events:
                event_data = self._parse_event(event)
                if event_data:
                    parsed_events.append(event_data)

            return parsed_events
        except NotFoundError:
            logger.warning("Calendar not found at path: %s", calendar_path)
            return []
        except Exception as e:
            logger.error("Failed to get events from DAViCal: %s", str(e))
            raise

    def create_event(self, user, calendar_path: str, event_data: dict) -> str:
        """
        Create a new event in DAViCal.
        Returns the event UID.
        """
        # Ensure user exists first
        self.ensure_user_exists(user)

        client = self._get_client(user)
        calendar_url = f"{self.base_url}{calendar_path}"
        calendar = client.calendar(url=calendar_url)

        # Extract event data
        dtstart = event_data.get("start", timezone.now())
        dtend = event_data.get("end", dtstart + timedelta(hours=1))
        summary = event_data.get("title", "New Event")
        description = event_data.get("description", "")
        location = event_data.get("location", "")

        # Generate UID if not provided
        event_uid = event_data.get("uid", str(uuid4()))

        try:
            # Create event using caldav library
            event = calendar.save_event(
                dtstart=dtstart,
                dtend=dtend,
                uid=event_uid,
                summary=summary,
                description=description,
                location=location,
            )

            # Extract UID from created event
            # The caldav library returns an Event object
            if hasattr(event, "icalendar_component"):
                event_uid = str(event.icalendar_component.get("uid", event_uid))
            elif hasattr(event, "vobject_instance"):
                event_uid = event.vobject_instance.vevent.uid.value

            logger.info("Created event in DAViCal: %s", event_uid)
            return event_uid
        except Exception as e:
            logger.error("Failed to create event in DAViCal: %s", str(e))
            raise

    def update_event(
        self, user, calendar_path: str, event_uid: str, event_data: dict
    ) -> None:
        """Update an existing event in DAViCal."""
        # Ensure user exists first
        self.ensure_user_exists(user)

        client = self._get_client(user)
        calendar_url = f"{self.base_url}{calendar_path}"
        calendar = client.calendar(url=calendar_url)

        try:
            # Search for the event by UID
            events = calendar.search(event=True)
            target_event = None

            for event in events:
                event_uid_value = None
                if hasattr(event, "icalendar_component"):
                    event_uid_value = str(event.icalendar_component.get("uid", ""))
                elif hasattr(event, "vobject_instance"):
                    event_uid_value = event.vobject_instance.vevent.uid.value

                if event_uid_value == event_uid:
                    target_event = event
                    break

            if not target_event:
                raise ValueError(f"Event with UID {event_uid} not found")

            # Update event properties
            dtstart = event_data.get("start")
            dtend = event_data.get("end")
            summary = event_data.get("title")
            description = event_data.get("description")
            location = event_data.get("location")

            # Update using icalendar component
            component = target_event.icalendar_component

            if dtstart:
                component["dtstart"] = dtstart
            if dtend:
                component["dtend"] = dtend
            if summary:
                component["summary"] = summary
            if description is not None:
                component["description"] = description
            if location is not None:
                component["location"] = location

            # Save the updated event
            target_event.save()

            logger.info("Updated event in DAViCal: %s", event_uid)
        except Exception as e:
            logger.error("Failed to update event in DAViCal: %s", str(e))
            raise

    def delete_event(self, user, calendar_path: str, event_uid: str) -> None:
        """Delete an event from DAViCal."""
        # Ensure user exists first
        self.ensure_user_exists(user)

        client = self._get_client(user)
        calendar_url = f"{self.base_url}{calendar_path}"
        calendar = client.calendar(url=calendar_url)

        try:
            # Search for the event by UID
            events = calendar.search(event=True)
            target_event = None

            for event in events:
                event_uid_value = None
                if hasattr(event, "icalendar_component"):
                    event_uid_value = str(event.icalendar_component.get("uid", ""))
                elif hasattr(event, "vobject_instance"):
                    event_uid_value = event.vobject_instance.vevent.uid.value

                if event_uid_value == event_uid:
                    target_event = event
                    break

            if not target_event:
                raise ValueError(f"Event with UID {event_uid} not found")

            # Delete the event
            target_event.delete()

            logger.info("Deleted event from DAViCal: %s", event_uid)
        except Exception as e:
            logger.error("Failed to delete event from DAViCal: %s", str(e))
            raise

    def _parse_event(self, event) -> Optional[dict]:
        """
        Parse a caldav Event object and return event data as dictionary.
        """
        try:
            component = event.icalendar_component

            event_data = {
                "uid": str(component.get("uid", "")),
                "title": str(component.get("summary", "")),
                "start": component.get("dtstart").dt
                if component.get("dtstart")
                else None,
                "end": component.get("dtend").dt if component.get("dtend") else None,
                "description": str(component.get("description", "")),
                "location": str(component.get("location", "")),
            }

            # Convert datetime to string format for consistency
            if event_data["start"]:
                if isinstance(event_data["start"], datetime):
                    event_data["start"] = event_data["start"].strftime("%Y%m%dT%H%M%SZ")
                elif isinstance(event_data["start"], date):
                    event_data["start"] = event_data["start"].strftime("%Y%m%d")

            if event_data["end"]:
                if isinstance(event_data["end"], datetime):
                    event_data["end"] = event_data["end"].strftime("%Y%m%dT%H%M%SZ")
                elif isinstance(event_data["end"], date):
                    event_data["end"] = event_data["end"].strftime("%Y%m%d")

            return event_data if event_data.get("uid") else None
        except Exception as e:
            logger.warning("Failed to parse event: %s", str(e))
            return None


class CalendarService:
    """
    High-level service for managing calendars and events.
    """

    def __init__(self):
        self.davical = DAViCalClient()

    def create_default_calendar(self, user) -> Calendar:
        """
        Create a default calendar for a user.
        """
        calendar_id = str(uuid4())
        calendar_name = "Mon calendrier"

        # Create calendar in DAViCal
        davical_path = self.davical.create_calendar(user, calendar_name, calendar_id)

        # Create local Calendar record
        calendar = Calendar.objects.create(
            owner=user,
            name=calendar_name,
            davical_path=davical_path,
            is_default=True,
            color="#3174ad",
        )

        return calendar

    def create_calendar(self, user, name: str, color: str = "#3174ad") -> Calendar:
        """
        Create a new calendar for a user.
        """
        calendar_id = str(uuid4())

        # Create calendar in DAViCal
        davical_path = self.davical.create_calendar(user, name, calendar_id)

        # Create local Calendar record
        calendar = Calendar.objects.create(
            owner=user,
            name=name,
            davical_path=davical_path,
            is_default=False,
            color=color,
        )

        return calendar

    def get_user_calendars(self, user):
        """
        Get all calendars accessible by a user (owned + shared).
        """
        owned = Calendar.objects.filter(owner=user)
        shared = Calendar.objects.filter(shares__shared_with=user)
        return owned.union(shared)

    def get_events(self, user, calendar: Calendar, start=None, end=None) -> list:
        """
        Get events from a calendar.
        Returns parsed event data.
        """
        return self.davical.get_events(user, calendar.davical_path, start, end)

    def create_event(self, user, calendar: Calendar, event_data: dict) -> str:
        """Create a new event."""
        return self.davical.create_event(user, calendar.davical_path, event_data)

    def update_event(
        self, user, calendar: Calendar, event_uid: str, event_data: dict
    ) -> None:
        """Update an existing event."""
        self.davical.update_event(user, calendar.davical_path, event_uid, event_data)

    def delete_event(self, user, calendar: Calendar, event_uid: str) -> None:
        """Delete an event."""
        self.davical.delete_event(user, calendar.davical_path, event_uid)
