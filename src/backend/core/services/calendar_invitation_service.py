"""
Calendar Invitation Email Service.

This service handles parsing iCalendar data and sending invitation emails
with ICS file attachments for CalDAV scheduling (RFC 6638/6047).

The service is called by the CalDAVSchedulingCallbackView when the CalDAV
server (sabre/dav) needs to send invitations to external attendees.
"""

import logging
import re
from dataclasses import dataclass
from datetime import datetime
from datetime import timezone as dt_timezone
from email import encoders
from email.mime.base import MIMEBase
from typing import Optional

from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string

# French month and day names for date formatting
FRENCH_DAYS = ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"]
FRENCH_MONTHS = [
    "",
    "janvier",
    "février",
    "mars",
    "avril",
    "mai",
    "juin",
    "juillet",
    "août",
    "septembre",
    "octobre",
    "novembre",
    "décembre",
]

logger = logging.getLogger(__name__)


@dataclass
class EventDetails:  # pylint: disable=too-many-instance-attributes
    """Parsed event details from iCalendar data."""

    uid: str
    summary: str
    description: Optional[str]
    location: Optional[str]
    url: Optional[str]
    dtstart: datetime
    dtend: Optional[datetime]
    organizer_email: str
    organizer_name: Optional[str]
    attendee_email: str
    attendee_name: Optional[str]
    sequence: int
    is_all_day: bool
    raw_icalendar: str


class ICalendarParser:
    """
    Simple iCalendar parser for extracting event details.

    This is a lightweight parser focused on extracting the information
    needed for invitation emails. For full iCalendar handling, consider
    using a library like icalendar.
    """

    @staticmethod
    def extract_vevent_block(icalendar: str) -> Optional[str]:
        """
        Extract the VEVENT block from iCalendar data.

        This is important because VTIMEZONE blocks also contain DTSTART/DTEND
        properties (for DST rules with dates like 1970), and we need to parse
        only the VEVENT properties.
        """
        # Handle multi-line values first
        icalendar = re.sub(r"\r?\n[ \t]", "", icalendar)

        # Find VEVENT block
        pattern = r"BEGIN:VEVENT\s*\n(.+?)\nEND:VEVENT"
        match = re.search(pattern, icalendar, re.DOTALL | re.IGNORECASE)
        if match:
            return match.group(0)
        return None

    @staticmethod
    def extract_property(icalendar: str, property_name: str) -> Optional[str]:
        """Extract a simple property value from iCalendar data."""
        # Handle multi-line values (lines starting with space/tab are continuations)
        icalendar = re.sub(r"\r?\n[ \t]", "", icalendar)

        pattern = rf"^{property_name}(;[^:]*)?:(.+)$"
        match = re.search(pattern, icalendar, re.MULTILINE | re.IGNORECASE)
        if match:
            return match.group(2).strip()
        return None

    @staticmethod
    def extract_property_with_params(
        icalendar: str, property_name: str
    ) -> tuple[Optional[str], dict]:
        """
        Extract a property value and its parameters.

        Returns (value, {param_name: param_value, ...})
        """
        # Handle multi-line values
        icalendar = re.sub(r"\r?\n[ \t]", "", icalendar)

        pattern = rf"^{property_name}((?:;[^:]+)*):(.+)$"
        match = re.search(pattern, icalendar, re.MULTILINE | re.IGNORECASE)
        if not match:
            return None, {}

        params_str = match.group(1)
        value = match.group(2).strip()

        # Parse parameters
        params = {}
        if params_str:
            # Split by ; but not within quotes
            param_matches = re.findall(r";([^=]+)=([^;]+)", params_str)
            for param_name, raw_value in param_matches:
                # Remove quotes if present
                params[param_name.upper()] = raw_value.strip('"')

        return value, params

    @staticmethod
    def parse_datetime(
        value: Optional[str], tzid: Optional[str] = None
    ) -> Optional[datetime]:
        """Parse iCalendar datetime value with optional timezone."""
        if not value:
            return None

        value = value.strip()

        # Try different formats
        formats = [
            "%Y%m%dT%H%M%SZ",  # UTC format
            "%Y%m%dT%H%M%S",  # Local format
            "%Y%m%d",  # Date only (all-day event)
        ]

        for fmt in formats:
            try:
                dt = datetime.strptime(value, fmt)
                if fmt == "%Y%m%dT%H%M%SZ":
                    # Already UTC
                    dt = dt.replace(tzinfo=dt_timezone.utc)
                elif tzid:
                    # Has timezone info - try to convert using zoneinfo
                    try:
                        from zoneinfo import (  # noqa: PLC0415  # pylint: disable=import-outside-toplevel
                            ZoneInfo,
                        )

                        tz = ZoneInfo(tzid)
                        dt = dt.replace(tzinfo=tz)
                    except (KeyError, ValueError):
                        # If timezone conversion fails, keep as naive datetime
                        logger.debug(
                            "Unknown timezone %s, keeping naive datetime", tzid
                        )
                return dt
            except ValueError:
                continue

        logger.warning("Could not parse datetime: %s (tzid: %s)", value, tzid)
        return None

    @classmethod
    def parse(  # pylint: disable=too-many-locals,too-many-branches
        cls, icalendar: str, recipient_email: str
    ) -> Optional[EventDetails]:
        """
        Parse iCalendar data and extract event details.

        Args:
            icalendar: Raw iCalendar string (VCALENDAR with VEVENT)
            recipient_email: The email of the attendee receiving this invitation

        Returns:
            EventDetails object or None if parsing fails
        """
        try:
            # Extract VEVENT block to avoid parsing VTIMEZONE properties
            # (VTIMEZONE contains DTSTART/DTEND with 1970 dates for DST rules)
            vevent_block = cls.extract_vevent_block(icalendar)
            if not vevent_block:
                logger.error("No VEVENT block found in iCalendar data")
                return None

            # Extract basic properties from VEVENT block
            uid = cls.extract_property(vevent_block, "UID")
            summary = cls.extract_property(vevent_block, "SUMMARY") or "(Sans titre)"
            description = cls.extract_property(vevent_block, "DESCRIPTION")
            location = cls.extract_property(vevent_block, "LOCATION")
            url = cls.extract_property(vevent_block, "URL")

            # Parse dates with timezone support - from VEVENT block only
            dtstart_raw, dtstart_params = cls.extract_property_with_params(
                vevent_block, "DTSTART"
            )
            dtend_raw, dtend_params = cls.extract_property_with_params(
                vevent_block, "DTEND"
            )
            dtstart_tzid = dtstart_params.get("TZID")
            dtend_tzid = dtend_params.get("TZID")
            dtstart = cls.parse_datetime(dtstart_raw, dtstart_tzid)
            dtend = cls.parse_datetime(dtend_raw, dtend_tzid)

            # Check if all-day event (date only, no time component)
            is_all_day = (
                dtstart_raw and "T" not in dtstart_raw if dtstart_raw else False
            )

            # Extract organizer from VEVENT block
            organizer_value, organizer_params = cls.extract_property_with_params(
                vevent_block, "ORGANIZER"
            )
            organizer_email = ""
            if organizer_value:
                organizer_email = organizer_value.replace("mailto:", "").strip()
            organizer_name = organizer_params.get("CN")

            # Extract attendee info for the recipient from VEVENT block
            # Find the ATTENDEE line that matches the recipient
            recipient_clean = recipient_email.replace("mailto:", "").lower()
            attendee_name = None

            # Look for ATTENDEE lines in VEVENT block
            attendee_pattern = rf"^ATTENDEE[^:]*:mailto:{re.escape(recipient_clean)}$"
            attendee_match = re.search(
                attendee_pattern, vevent_block, re.MULTILINE | re.IGNORECASE
            )
            if attendee_match:
                full_line = attendee_match.group(0)
                cn_match = re.search(r"CN=([^;:]+)", full_line, re.IGNORECASE)
                if cn_match:
                    attendee_name = cn_match.group(1).strip('"')

            # Get sequence number from VEVENT block
            sequence_str = cls.extract_property(vevent_block, "SEQUENCE")
            sequence = (
                int(sequence_str) if sequence_str and sequence_str.isdigit() else 0
            )

            if not uid or not dtstart:
                logger.error(
                    "Missing required fields: UID=%s, DTSTART=%s", uid, dtstart
                )
                return None

            return EventDetails(
                uid=uid,
                summary=summary,
                description=description,
                location=location,
                url=url,
                dtstart=dtstart,
                dtend=dtend,
                organizer_email=organizer_email,
                organizer_name=organizer_name,
                attendee_email=recipient_clean,
                attendee_name=attendee_name,
                sequence=sequence,
                is_all_day=is_all_day,
                raw_icalendar=icalendar,
            )

        except Exception as e:  # pylint: disable=broad-exception-caught
            logger.exception("Failed to parse iCalendar data: %s", e)
            return None


class CalendarInvitationService:  # pylint: disable=too-many-instance-attributes
    """
    Service for sending calendar invitation emails.

    This service creates properly formatted invitation emails with:
    - Plain text body
    - HTML body
    - ICS file attachment with correct METHOD header

    The emails are compatible with major calendar clients:
    - Outlook
    - Google Calendar
    - Apple Calendar
    - Thunderbird
    """

    # iTip methods
    METHOD_REQUEST = "REQUEST"  # New invitation or update
    METHOD_CANCEL = "CANCEL"  # Cancellation
    METHOD_REPLY = "REPLY"  # Attendee response

    def __init__(self):
        self.parser = ICalendarParser()

    def send_invitation(
        self,
        sender_email: str,
        recipient_email: str,
        method: str,
        icalendar_data: str,
    ) -> bool:
        """
        Send a calendar invitation email.

        Args:
            sender_email: The organizer's email (mailto: format)
            recipient_email: The attendee's email (mailto: format)
            method: iTip method (REQUEST, CANCEL, REPLY)
            icalendar_data: Raw iCalendar data

        Returns:
            True if email was sent successfully, False otherwise
        """
        # Clean email addresses (remove mailto: prefix)
        sender = sender_email.replace("mailto:", "").strip()
        recipient = recipient_email.replace("mailto:", "").strip()

        # Parse event details
        event = self.parser.parse(icalendar_data, recipient)
        if not event:
            logger.error(
                "Failed to parse iCalendar data for invitation to %s", recipient
            )
            return False

        try:
            # Determine email type and get appropriate subject/content
            if method == self.METHOD_CANCEL:
                subject = self._get_cancel_subject(event)
                template_prefix = "calendar_invitation_cancel"
            elif method == self.METHOD_REPLY:
                subject = self._get_reply_subject(event)
                template_prefix = "calendar_invitation_reply"
            elif event.sequence > 0:
                subject = self._get_update_subject(event)
                template_prefix = "calendar_invitation_update"
            else:
                subject = self._get_invitation_subject(event)
                template_prefix = "calendar_invitation"

            # Build context for templates
            context = self._build_template_context(event, method)

            # Render email bodies
            text_body = render_to_string(f"emails/{template_prefix}.txt", context)
            html_body = render_to_string(f"emails/{template_prefix}.html", context)

            # Prepare ICS attachment with correct METHOD
            ics_content = self._prepare_ics_attachment(icalendar_data, method)

            # Send email
            return self._send_email(
                from_email=sender,
                to_email=recipient,
                subject=subject,
                text_body=text_body,
                html_body=html_body,
                ics_content=ics_content,
                ics_method=method,
                event_uid=event.uid,
            )

        except Exception as e:  # pylint: disable=broad-exception-caught
            logger.exception(
                "Failed to send calendar invitation to %s: %s", recipient, e
            )
            return False

    def _get_invitation_subject(self, event: EventDetails) -> str:
        """Generate subject line for new invitation."""
        return f"Invitation : {event.summary}"

    def _get_update_subject(self, event: EventDetails) -> str:
        """Generate subject line for event update."""
        return f"Invitation modifiée : {event.summary}"

    def _get_cancel_subject(self, event: EventDetails) -> str:
        """Generate subject line for cancellation."""
        return f"Annulé : {event.summary}"

    def _get_reply_subject(self, event: EventDetails) -> str:
        """Generate subject line for attendee reply."""
        return f"Réponse : {event.summary}"

    def _format_date_french(self, dt: datetime) -> str:
        """Format a datetime in French (e.g., 'jeudi 23 janvier 2026')."""
        day_name = FRENCH_DAYS[dt.weekday()]
        month_name = FRENCH_MONTHS[dt.month]
        return f"{day_name} {dt.day} {month_name} {dt.year}"

    def _build_template_context(self, event: EventDetails, method: str) -> dict:
        """Build context dictionary for email templates."""
        # Format dates for display in French
        if event.is_all_day:
            start_str = self._format_date_french(event.dtstart)
            end_str = (
                self._format_date_french(event.dtend) if event.dtend else start_str
            )
            time_str = "Toute la journée"
        else:
            time_format = "%H:%M"
            start_str = self._format_date_french(event.dtstart)
            start_time = event.dtstart.strftime(time_format)
            end_time = event.dtend.strftime(time_format) if event.dtend else ""
            end_str = (
                self._format_date_french(event.dtend) if event.dtend else start_str
            )
            time_str = f"{start_time} - {end_time}" if end_time else start_time

        return {
            "event": event,
            "method": method,
            "organizer_display": event.organizer_name or event.organizer_email,
            "attendee_display": event.attendee_name or event.attendee_email,
            "start_date": start_str,
            "end_date": end_str,
            "time_str": time_str,
            "is_update": event.sequence > 0,
            "is_cancel": method == self.METHOD_CANCEL,
            "app_name": getattr(settings, "APP_NAME", "Calendrier"),
            "app_url": getattr(settings, "APP_URL", ""),
        }

    def _prepare_ics_attachment(self, icalendar_data: str, method: str) -> str:
        """
        Prepare ICS content with correct METHOD for attachment.

        The METHOD property must be in the VCALENDAR component, not VEVENT.
        """
        # Check if METHOD is already present
        if "METHOD:" not in icalendar_data.upper():
            # Insert METHOD after VERSION
            icalendar_data = re.sub(
                r"(VERSION:2\.0\r?\n)",
                rf"\1METHOD:{method}\r\n",
                icalendar_data,
                flags=re.IGNORECASE,
            )
        else:
            # Update existing METHOD
            icalendar_data = re.sub(
                r"METHOD:[^\r\n]+",
                f"METHOD:{method}",
                icalendar_data,
                flags=re.IGNORECASE,
            )

        return icalendar_data

    def _send_email(  # noqa: PLR0913  # pylint: disable=too-many-arguments,too-many-positional-arguments
        self,
        from_email: str,
        to_email: str,
        subject: str,
        text_body: str,
        html_body: str,
        ics_content: str,
        ics_method: str,
        event_uid: str,
    ) -> bool:
        """
        Send the actual email with ICS attachment.

        The email structure follows RFC 6047 for iTip over email:
        - multipart/mixed
          - multipart/alternative
            - text/plain
            - text/html
          - text/calendar (ICS attachment)
        """
        try:
            # Get email settings
            from_addr = getattr(
                settings,
                "CALENDAR_INVITATION_FROM_EMAIL",
                getattr(settings, "DEFAULT_FROM_EMAIL", "noreply@example.com"),
            )

            # Create the email message
            email = EmailMultiAlternatives(
                subject=subject,
                body=text_body,
                from_email=from_addr,
                to=[to_email],
                reply_to=[from_email],  # Allow replies to the organizer
            )

            # Add HTML alternative
            email.attach_alternative(html_body, "text/html")

            # Add ICS attachment with proper MIME type
            # The Content-Type must include method parameter for calendar clients
            ics_attachment = MIMEBase("text", "calendar")
            ics_attachment.set_payload(ics_content.encode("utf-8"))
            encoders.encode_base64(ics_attachment)
            ics_attachment.add_header(
                "Content-Type", f"text/calendar; charset=utf-8; method={ics_method}"
            )
            ics_attachment.add_header(
                "Content-Disposition", 'attachment; filename="invite.ics"'
            )

            # Attach the ICS file
            email.attach(ics_attachment)

            # Send the email
            email.send(fail_silently=False)

            logger.info(
                "Calendar invitation sent: %s -> %s (method: %s, uid: %s)",
                from_email,
                to_email,
                ics_method,
                event_uid,
            )
            return True

        except Exception as e:  # pylint: disable=broad-exception-caught
            logger.exception(
                "Failed to send calendar invitation email to %s: %s", to_email, e
            )
            return False


# Singleton instance for convenience
calendar_invitation_service = CalendarInvitationService()
