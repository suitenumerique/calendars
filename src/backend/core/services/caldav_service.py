"""Services for CalDAV integration."""

import logging
from datetime import date, datetime, timedelta
from typing import Optional
from uuid import uuid4

from django.conf import settings
from django.utils import timezone

from caldav import DAVClient
from caldav.lib.error import NotFoundError
from core.models import Calendar

logger = logging.getLogger(__name__)


class CalDAVClient:
    """
    Client for communicating with CalDAV server using the caldav library.
    """

    def __init__(self):
        self.base_url = settings.CALDAV_URL
        # Set the base URI path as expected by the CalDAV server
        self.base_uri_path = "/api/v1.0/caldav/"
        self.timeout = 30

    def _get_client(self, user) -> DAVClient:
        """
        Get a CalDAV client for the given user.

        The CalDAV server requires API key authentication via Authorization header
        and X-Forwarded-User header for user identification.
        """
        # CalDAV server base URL - include the base URI path that sabre/dav expects
        # Remove trailing slash from base_url and base_uri_path to avoid double slashes
        base_url_clean = self.base_url.rstrip("/")
        base_uri_clean = self.base_uri_path.rstrip("/")
        caldav_url = f"{base_url_clean}{base_uri_clean}/"

        # Prepare headers
        # API key is required for authentication
        headers = {
            "X-Forwarded-User": user.email,
        }

        outbound_api_key = settings.CALDAV_OUTBOUND_API_KEY
        if not outbound_api_key:
            raise ValueError("CALDAV_OUTBOUND_API_KEY is not configured")

        headers["X-Api-Key"] = outbound_api_key

        # No username/password needed - authentication is via API key and X-Forwarded-User header
        # Pass None to prevent the caldav library from trying Basic auth
        return DAVClient(
            url=caldav_url,
            username=None,
            password=None,
            timeout=self.timeout,
            headers=headers,
        )

    def get_calendar_info(self, user, calendar_path: str) -> dict | None:
        """
        Get calendar information from CalDAV server.
        Returns dict with name, color, description or None if not found.
        """
        client = self._get_client(user)
        calendar_url = f"{self.base_url}{calendar_path}"

        try:
            calendar = client.calendar(url=calendar_url)
            # Fetch properties
            props = calendar.get_properties(
                [
                    "{DAV:}displayname",
                    "{http://apple.com/ns/ical/}calendar-color",
                    "{urn:ietf:params:xml:ns:caldav}calendar-description",
                ]
            )

            name = props.get("{DAV:}displayname", "Calendar")
            color = props.get("{http://apple.com/ns/ical/}calendar-color", "#3174ad")
            description = props.get(
                "{urn:ietf:params:xml:ns:caldav}calendar-description", ""
            )

            # Clean up color (CalDAV may return with alpha channel like #RRGGBBAA)
            if color and len(color) == 9 and color.startswith("#"):
                color = color[:7]

            logger.info("Got calendar info from CalDAV: name=%s, color=%s", name, color)
            return {
                "name": name,
                "color": color,
                "description": description,
            }
        except NotFoundError:
            logger.warning("Calendar not found at path: %s", calendar_path)
            return None
        except Exception as e:  # noqa: BLE001  # pylint: disable=broad-exception-caught
            logger.error("Failed to get calendar info from CalDAV: %s", str(e))
            return None

    def create_calendar(self, user, calendar_name: str, calendar_id: str) -> str:
        """
        Create a new calendar in CalDAV server for the given user.
        Returns the CalDAV server path for the calendar.
        """
        client = self._get_client(user)
        principal = client.principal()

        try:
            # Create calendar using caldav library
            calendar = principal.make_calendar(name=calendar_name)

            # CalDAV server calendar path format: /calendars/{username}/{calendar_id}/
            # The caldav library returns a URL object, convert to string and extract path
            calendar_url = str(calendar.url)
            # Extract path from full URL
            if calendar_url.startswith(self.base_url):
                path = calendar_url[len(self.base_url) :]
            else:
                # Fallback: construct path manually based on standard CalDAV structure
                # CalDAV servers typically create calendars under /calendars/{principal}/
                path = f"/calendars/{user.email}/{calendar_id}/"

            logger.info(
                "Created calendar in CalDAV server: %s at %s", calendar_name, path
            )
            return path
        except Exception as e:
            logger.error("Failed to create calendar in CalDAV server: %s", str(e))
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
            logger.error("Failed to get events from CalDAV server: %s", str(e))
            raise

    def create_event_raw(self, user, calendar_path: str, ics_data: str) -> str:
        """
        Create an event in CalDAV server from raw ICS data.
        The ics_data should be a complete VCALENDAR string.
        Returns the event UID.
        """
        client = self._get_client(user)
        calendar_url = f"{self.base_url}{calendar_path}"
        calendar = client.calendar(url=calendar_url)

        try:
            event = calendar.save_event(ics_data)
            event_uid = str(event.icalendar_component.get("uid", ""))
            logger.info("Created event in CalDAV server: %s", event_uid)
            return event_uid
        except Exception as e:
            logger.error("Failed to create event in CalDAV server: %s", str(e))
            raise

    def create_event(self, user, calendar_path: str, event_data: dict) -> str:
        """
        Create a new event in CalDAV server.
        Returns the event UID.
        """

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

            logger.info("Created event in CalDAV server: %s", event_uid)
            return event_uid
        except Exception as e:
            logger.error("Failed to create event in CalDAV server: %s", str(e))
            raise

    def update_event(
        self, user, calendar_path: str, event_uid: str, event_data: dict
    ) -> None:
        """Update an existing event in CalDAV server."""

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

            logger.info("Updated event in CalDAV server: %s", event_uid)
        except Exception as e:
            logger.error("Failed to update event in CalDAV server: %s", str(e))
            raise

    def delete_event(self, user, calendar_path: str, event_uid: str) -> None:
        """Delete an event from CalDAV server."""

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

            logger.info("Deleted event from CalDAV server: %s", event_uid)
        except Exception as e:
            logger.error("Failed to delete event from CalDAV server: %s", str(e))
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
        except Exception as e:  # noqa: BLE001  # pylint: disable=broad-exception-caught
            logger.warning("Failed to parse event: %s", str(e))
            return None


class CalendarService:
    """
    High-level service for managing calendars and events.
    """

    def __init__(self):
        self.caldav = CalDAVClient()

    def create_default_calendar(self, user) -> Calendar:
        """
        Create a default calendar for a user.
        """
        calendar_id = str(uuid4())
        calendar_name = "Mon calendrier"

        # Create calendar in CalDAV server
        caldav_path = self.caldav.create_calendar(user, calendar_name, calendar_id)

        # Create local Calendar record
        calendar = Calendar.objects.create(
            owner=user,
            name=calendar_name,
            caldav_path=caldav_path,
            is_default=True,
            color="#3174ad",
        )

        return calendar

    def create_calendar(self, user, name: str, color: str = "#3174ad") -> Calendar:
        """
        Create a new calendar for a user.
        """
        calendar_id = str(uuid4())

        # Create calendar in CalDAV server
        caldav_path = self.caldav.create_calendar(user, name, calendar_id)

        # Create local Calendar record
        calendar = Calendar.objects.create(
            owner=user,
            name=name,
            caldav_path=caldav_path,
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
        return self.caldav.get_events(user, calendar.caldav_path, start, end)

    def create_event(self, user, calendar: Calendar, event_data: dict) -> str:
        """Create a new event."""
        return self.caldav.create_event(user, calendar.caldav_path, event_data)

    def update_event(
        self, user, calendar: Calendar, event_uid: str, event_data: dict
    ) -> None:
        """Update an existing event."""
        self.caldav.update_event(user, calendar.caldav_path, event_uid, event_data)

    def delete_event(self, user, calendar: Calendar, event_uid: str) -> None:
        """Delete an event."""
        self.caldav.delete_event(user, calendar.caldav_path, event_uid)
