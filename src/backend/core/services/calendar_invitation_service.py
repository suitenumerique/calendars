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
from datetime import date, datetime
from datetime import timezone as dt_timezone
from email import encoders
from email.mime.base import MIMEBase
from email.utils import make_msgid
from typing import Optional
from urllib.parse import urlencode, urlparse

from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.core.signing import TimestampSigner
from django.template.loader import render_to_string
from django.utils import timezone

import icalendar

from core.models import User
from core.services.translation_service import TranslationService

logger = logging.getLogger(__name__)


class _CalendarEmail(EmailMultiAlternatives):
    """EmailMultiAlternatives that preserves the iMIP ``method=`` parameter
    on a ``text/calendar`` alternative.

    Django's ``_create_mime_attachment`` only forwards the base type and
    subtype to ``SafeMIMEText``, losing any extra Content-Type parameters
    passed via ``attach_alternative``. We override that hook to re-apply
    the ``method=`` once the part is built.
    """

    ics_method: Optional[str] = None

    def _create_mime_attachment(self, content, mimetype):
        attachment = super()._create_mime_attachment(content, mimetype)
        if mimetype == "text/calendar" and self.ics_method:
            attachment.replace_header(
                "Content-Type",
                f'text/calendar; charset="utf-8"; method={self.ics_method}',
            )
        return attachment


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
    Thin wrapper around the ``icalendar`` library that returns a flat
    ``EventDetails`` dataclass for the email-template / RSVP code paths.

    History: this used to be a hand-rolled regex parser. The regex
    approach was load-bearing on a fragile invariant — that every byte
    reaching it had been re-serialized by sabre/vobject upstream — and
    a security audit (see N1 in the ICS deep-dive) flagged it as a
    line-injection / header-smuggling primitive waiting for the wrong
    code path to feed it raw bytes. The fix is to use a real RFC 5545
    parser. The ``icalendar`` library is already a transitive dependency
    of ``caldav``/``tsdav`` and is used elsewhere in the codebase.
    """

    # URL schemes we are willing to render in invitation email bodies.
    # An ICS ``URL:`` value can be anything per RFC 5545 — including
    # ``javascript:``, ``data:`` or ``vbscript:`` — and we render it
    # straight into an HTML <a href=...> in the calendar_invitation*
    # templates. An attacker who can put an event on your calendar
    # (which is the whole point of an invitation) could otherwise
    # smuggle script-bearing URLs into the recipient's mail client.
    # Most modern clients block ``javascript:`` in href, but the safe
    # default is to allowlist instead of relying on the client.
    _SAFE_URL_SCHEMES = frozenset({"http", "https", "mailto", "tel"})

    @classmethod
    def sanitize_url(cls, raw: Optional[str]) -> Optional[str]:
        """Return ``raw`` only if it parses as a URL with a safe scheme.

        Returns ``None`` for any value whose scheme is not in the
        allowlist (``http``, ``https``, ``mailto``, ``tel``) — including
        scheme-less values, which would otherwise be interpreted as
        same-origin relative URLs by some mail clients.
        """
        if not raw:
            return None
        try:
            parsed = urlparse(raw.strip())
        except ValueError:
            return None
        scheme = (parsed.scheme or "").lower()
        if scheme not in cls._SAFE_URL_SCHEMES:
            logger.info(
                "Dropping ICS URL with disallowed scheme %r from invitation",
                scheme or "(none)",
            )
            return None
        return raw.strip()

    @staticmethod
    def _parse_calendar(icalendar_data: str) -> Optional[icalendar.Calendar]:
        """Wrap ``icalendar.Calendar.from_ical`` with logging."""
        try:
            return icalendar.Calendar.from_ical(icalendar_data)
        except (ValueError, TypeError, KeyError) as exc:
            logger.error("Failed to parse iCalendar data: %s", exc)
            return None

    @staticmethod
    def _first_vevent(cal: icalendar.Calendar):
        """Return the first VEVENT in the calendar (skipping VTIMEZONE)."""
        for component in cal.walk("VEVENT"):
            return component
        return None

    @staticmethod
    def _coerce_aware(value) -> Optional[datetime]:
        """Coerce a date/datetime to a timezone-aware datetime in UTC.

        ``icalendar`` returns naive ``datetime`` for floating times,
        ``date`` for all-day events, and ``datetime`` with ``tzinfo``
        otherwise. The downstream past-event check needs an aware
        datetime; render code only needs a value to format. Anchoring
        all values to UTC keeps comparisons monotonic.
        """
        if value is None:
            return None
        if isinstance(value, datetime):
            if value.tzinfo is None:
                return value.replace(tzinfo=dt_timezone.utc)
            return value
        if isinstance(value, date):
            # All-day: treat as midnight UTC.
            return datetime(value.year, value.month, value.day, tzinfo=dt_timezone.utc)
        return None

    @staticmethod
    def _is_all_day(value) -> bool:
        """True iff the value is a bare ``date`` (DTSTART;VALUE=DATE)."""
        return isinstance(value, date) and not isinstance(value, datetime)

    @staticmethod
    def _strip_mailto(raw: Optional[str]) -> str:
        if not raw:
            return ""
        return re.sub(r"^mailto:", "", str(raw), flags=re.IGNORECASE).strip()

    @classmethod
    def parse(  # noqa: PLR0915  # pylint: disable=too-many-statements,too-many-locals
        cls, icalendar_data: str, recipient_email: str
    ) -> Optional[EventDetails]:
        """Parse iCalendar data and return ``EventDetails``, or None on failure."""
        cal = cls._parse_calendar(icalendar_data)
        if cal is None:
            return None

        vevent = cls._first_vevent(cal)
        if vevent is None:
            logger.error("No VEVENT component found in iCalendar data")
            return None

        recipient_clean = cls._strip_mailto(recipient_email).lower()

        # Required fields
        uid_prop = vevent.get("UID")
        if not uid_prop:
            logger.error("VEVENT missing UID")
            return None
        uid = str(uid_prop)

        dtstart_prop = vevent.get("DTSTART")
        if dtstart_prop is None:
            logger.error("VEVENT missing DTSTART")
            return None

        dtstart_value = dtstart_prop.dt
        dtend_prop = vevent.get("DTEND")
        dtend_value = dtend_prop.dt if dtend_prop is not None else None

        is_all_day = cls._is_all_day(dtstart_value)
        dtstart = cls._coerce_aware(dtstart_value)
        dtend = cls._coerce_aware(dtend_value)

        if dtstart is None:
            logger.error("VEVENT DTSTART could not be coerced to a datetime")
            return None

        # Optional text fields. ``icalendar`` returns vText (strings)
        # which already have RFC 5545 escaping decoded — \n inside
        # DESCRIPTION becomes a real newline.
        summary = str(vevent.get("SUMMARY") or "")
        description_prop = vevent.get("DESCRIPTION")
        description = str(description_prop) if description_prop is not None else None
        location_prop = vevent.get("LOCATION")
        location = str(location_prop) if location_prop is not None else None
        url_prop = vevent.get("URL")
        url = cls.sanitize_url(str(url_prop)) if url_prop is not None else None

        # ORGANIZER: vCalAddress with optional CN parameter.
        organizer_prop = vevent.get("ORGANIZER")
        organizer_email = ""
        organizer_name: Optional[str] = None
        if organizer_prop is not None:
            organizer_email = cls._strip_mailto(str(organizer_prop))
            cn = (
                organizer_prop.params.get("CN")
                if hasattr(organizer_prop, "params")
                else None
            )
            organizer_name = str(cn) if cn else None

        # ATTENDEE matching the recipient — may be a single value or a list.
        attendee_name: Optional[str] = None
        attendees = vevent.get("ATTENDEE")
        if attendees is not None:
            if not isinstance(attendees, list):
                attendees = [attendees]
            for att in attendees:
                if cls._strip_mailto(str(att)).lower() == recipient_clean:
                    cn = att.params.get("CN") if hasattr(att, "params") else None
                    if cn:
                        attendee_name = str(cn)
                    break

        # SEQUENCE
        sequence_prop = vevent.get("SEQUENCE")
        try:
            sequence = int(sequence_prop) if sequence_prop is not None else 0
        except (TypeError, ValueError):
            sequence = 0

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
            is_all_day=bool(is_all_day),
            raw_icalendar=icalendar_data,
        )

    @classmethod
    def is_event_past(cls, icalendar_data: str) -> bool:
        """Return True if the event has already ended.

        Recurring events (with RRULE) are never considered past — the
        recurrence may extend indefinitely. Falls back to DTSTART when
        DTEND is absent.
        """
        cal = cls._parse_calendar(icalendar_data)
        if cal is None:
            return False
        vevent = cls._first_vevent(cal)
        if vevent is None:
            return False
        if vevent.get("RRULE"):
            return False
        prop = vevent.get("DTEND") or vevent.get("DTSTART")
        if prop is None:
            return False
        dt = cls._coerce_aware(prop.dt)
        if dt is None:
            return False
        return dt < timezone.now()

    @classmethod
    def extract_summary(cls, icalendar_data: str) -> str:
        """Return the SUMMARY of the first VEVENT, or '' if none."""
        cal = cls._parse_calendar(icalendar_data)
        if cal is None:
            return ""
        vevent = cls._first_vevent(cal)
        if vevent is None:
            return ""
        return str(vevent.get("SUMMARY") or "")


def _message_id_domain() -> str:
    """Domain portion for invitation Message-ID headers.

    Format: ``_lst_mail.<host>`` where ``<host>`` is the hostname of
    ``settings.APP_URL`` (the instance's public URL). Falls back to
    ``localhost`` if APP_URL is unset or malformed.

    Django's default ``DNS_NAME`` would otherwise be ``socket.getfqdn()``
    — i.e. the container hostname, which is opaque and per-pod. Anchoring
    the Message-ID domain to the instance URL means receiving MTAs can
    correlate invitations to the issuing instance, and the
    ``_lst_mail.`` prefix scopes our Message-IDs to a subdomain that
    cannot collide with any real-mail traffic served from APP_URL.
    """
    parsed = urlparse(settings.APP_URL or "")
    host = parsed.hostname or "localhost"
    return f"_lst_mail.{host}"


def _build_calendar_email(  # noqa: PLR0913  # pylint: disable=too-many-arguments,too-many-positional-arguments
    *,
    from_email: str,
    to_email: str,
    reply_to: Optional[str],
    subject: str,
    text_body: str,
    html_body: str,
    ics_content: str,
    ics_method: str,
    itip_enabled: bool,
) -> _CalendarEmail:
    """Build the canonical iMIP calendar email — single source of truth
    for BOTH the SMTP and Messages paths.

    The SMTP path calls ``email.send()``; the Messages path calls
    ``email.message().as_bytes()`` and POSTs the bytes. Building from
    the same function guarantees both recipients see the same MIME
    structure, the same ``Date`` / ``Message-ID`` (Django generates Date
    inside ``message()``; we inject Message-ID explicitly via
    ``extra_headers`` so its domain is ours, not the container's), and
    the same iMIP ``method=`` on the ``text/calendar`` Content-Type —
    historically the Messages path was missing all three.

    MIME layout (when ITIP is enabled):

        multipart/mixed
        ├── multipart/alternative
        │   ├── text/plain                       (plain-text body)
        │   ├── text/html                        (rich card)
        │   └── text/calendar; method=REQUEST    (iMIP payload)
        └── text/calendar; method=REQUEST        (attached invite.ics)

    Why ``text/calendar`` lives inside ``multipart/alternative`` and
    not only as a top-level attachment: Outlook (desktop + OWA) treats
    any ``text/calendar; method=REQUEST`` part as an iMIP meeting
    request and replaces the visible email body with its own meeting
    card. Per ``MS-STANOICAL`` V0346, Outlook picks the description
    from the first ``text/html`` *sibling of the calendar part inside
    its multipart/alternative parent* — so when calendar is a sibling
    of ``multipart/alternative`` (and not a child of it), Outlook
    finds no HTML and the message renders blank. This is the structure
    Google Calendar and Exchange itself emit. The top-level second
    ``text/calendar`` is treated by Outlook as a download attachment
    (V0343) and gives non-iMIP clients (Apple Mail, Thunderbird) a
    file they can act on directly.

    When ``itip_enabled`` is False the inline alternative is omitted
    and the .ics is sent only as an attachment.
    """
    # Pre-generate the Message-ID so Django's ``message()`` skips its
    # default ``make_msgid(domain=DNS_NAME)`` path (which would otherwise
    # leak the container hostname). When ``Message-ID`` is in
    # ``extra_headers``, Django bypasses the auto-injection.
    extra_headers = {"Message-ID": make_msgid(domain=_message_id_domain())}

    email = _CalendarEmail(
        subject=subject,
        body=text_body,
        from_email=from_email,
        to=[to_email],
        reply_to=[reply_to] if reply_to else None,
        headers=extra_headers,
    )
    if itip_enabled:
        email.ics_method = ics_method

    email.attach_alternative(html_body, "text/html")

    # iMIP calendar alternative — sibling of HTML so Outlook can find
    # the description (see docstring).
    if itip_enabled:
        email.attach_alternative(ics_content, "text/calendar")

    # ICS as a downloadable attachment for non-iMIP clients.
    # ``MIMEBase("text", "calendar")`` already sets a Content-Type
    # header; ``add_header`` would APPEND a second one and most
    # parsers honor the first — silently dropping ``method=``. Use
    # ``replace_header`` so the iMIP method actually lands.
    ics_attachment = MIMEBase("text", "calendar")
    ics_attachment.set_payload(ics_content.encode("utf-8"))
    encoders.encode_base64(ics_attachment)
    content_type = "text/calendar; charset=utf-8"
    if itip_enabled:
        content_type += f"; method={ics_method}"
    ics_attachment.replace_header("Content-Type", content_type)
    ics_attachment.add_header(
        "Content-Disposition", 'attachment; filename="invite.ics"'
    )
    email.attach(ics_attachment)

    return email


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

    def send_invitation(  # noqa: PLR0913  # pylint: disable=too-many-arguments,too-many-positional-arguments
        self,
        sender_email: str,
        recipient_email: str,
        method: str,
        icalendar_data: str,
        is_mailbox: bool = False,
        org_id: str = "",
    ) -> bool:
        """
        Send a calendar invitation email.

        Args:
            sender_email: The organizer's email (mailto: format)
            recipient_email: The attendee's email (mailto: format)
            method: iTip method (REQUEST, CANCEL, REPLY)
            icalendar_data: Raw iCalendar data
            is_mailbox: If True, send via Messages API from mailbox email
            org_id: Organization ID for RSVP token (from CalDAV request)

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
            # Resolve language for the recipient
            lang = TranslationService.resolve_language(email=recipient)
            t = TranslationService.t
            summary = event.summary or t("email.noTitle", lang)

            # Determine email type and get appropriate subject/content
            if method == self.METHOD_CANCEL:
                subject = t("email.subject.cancel", lang, summary=summary)
                template_prefix = "calendar_invitation_cancel"
            elif method == self.METHOD_REPLY:
                subject = t("email.subject.reply", lang, summary=summary)
                template_prefix = "calendar_invitation_reply"
            elif event.sequence > 0:
                subject = t("email.subject.update", lang, summary=summary)
                template_prefix = "calendar_invitation_update"
            else:
                subject = t("email.subject.invitation", lang, summary=summary)
                template_prefix = "calendar_invitation"

            # Build context for templates
            context = self._build_template_context(event, method, lang, org_id=org_id)

            # Render email bodies
            text_body = render_to_string(f"emails/{template_prefix}.txt", context)
            html_body = render_to_string(f"emails/{template_prefix}.html", context)

            # Prepare ICS attachment with correct METHOD
            ics_content = self._prepare_ics_attachment(icalendar_data, method)

            # Send email via Messages API (for mailbox calendars)
            # or via default SMTP (for standalone calendars).
            #
            # ``is_mailbox`` is runtime truth from SabreDAV
            # (``X-LS-Is-Mailbox`` set in ``viewsets_caldav.py``). If it's
            # true but Messages integration is disabled, fall-through to
            # SMTP would send the invitation from the system address
            # instead of the mailbox identity — silently wrong, and worse
            # than not sending. Refuse instead.
            if is_mailbox:
                if not settings.FEATURE_MESSAGES_INTEGRATION:
                    logger.error(
                        "Mailbox invitation requested but "
                        "FEATURE_MESSAGES_INTEGRATION is disabled — "
                        "refusing to fall back to SMTP (would send from "
                        "system address instead of %s). recipient=%s uid=%s",
                        sender,
                        recipient,
                        event.uid,
                    )
                    return False
                return self._send_via_messages(
                    mailbox_email=sender,
                    to_email=recipient,
                    subject=subject,
                    text_body=text_body,
                    html_body=html_body,
                    ics_content=ics_content,
                    ics_method=method,
                    event_uid=event.uid,
                )

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

    @staticmethod
    def _format_event_dates(event: "EventDetails", lang: str) -> tuple:
        """Return (start_str, end_str, time_str) for the given event."""
        t = TranslationService.t
        start_str = TranslationService.format_date(event.dtstart, lang)
        end_str = (
            TranslationService.format_date(event.dtend, lang)
            if event.dtend
            else start_str
        )
        if event.is_all_day:
            return start_str, end_str, t("email.allDay", lang)

        start_time = event.dtstart.strftime("%H:%M")
        end_time = event.dtend.strftime("%H:%M") if event.dtend else ""
        time_str = f"{start_time} - {end_time}" if end_time else start_time
        return start_str, end_str, time_str

    @staticmethod
    def _resolve_display_name(name: Optional[str], email: Optional[str]) -> str:
        """Resolve a display string like 'Name (email)' from name/email."""
        if not name and email:
            try:
                name = User.objects.get(email=email).full_name
            except User.DoesNotExist:
                pass
        if name and email:
            return f"{name} ({email})"
        return email or name or ""

    def _build_rsvp_context(self, event: "EventDetails", org_id: str = "") -> dict:
        """Build RSVP link context entries for REQUEST-method emails.

        Each action URL gets its own signed token with the action baked in.
        This prevents URL tampering (can't turn an accept link into a decline).
        """
        signer = TimestampSigner(salt="rsvp")
        organizer = re.sub(r"^mailto:", "", event.organizer_email, flags=re.IGNORECASE)
        base = {
            "u": event.uid,
            "e": event.attendee_email,
            "o": organizer,
            "g": org_id,
        }
        rsvp_base = f"{settings.APP_URL}/rsvp/"
        return {
            f"rsvp_{action}_url": (
                f"{rsvp_base}?{urlencode({'t': signer.sign_object({**base, 'a': action})})}"
            )
            for action in ("accepted", "tentative", "declined")
        }

    def _build_template_context(
        self, event: EventDetails, method: str, lang: str = "fr", org_id: str = ""
    ) -> dict:
        """Build context dictionary for email templates."""
        t = TranslationService.t
        summary = event.summary or t("email.noTitle", lang)
        start_str, end_str, time_str = self._format_event_dates(event, lang)

        organizer_display = self._resolve_display_name(
            event.organizer_name, event.organizer_email
        )
        attendee_display = self._resolve_display_name(
            event.attendee_name, event.attendee_email
        )

        # Determine email type key for content lookups
        if method == self.METHOD_CANCEL:
            type_key = "cancel"
        elif method == self.METHOD_REPLY:
            type_key = "reply"
        elif event.sequence > 0:
            type_key = "update"
        else:
            type_key = "invitation"

        context = {
            "event": event,
            "summary": summary,
            "method": method,
            "lang": lang,
            "organizer_display": organizer_display,
            "attendee_display": attendee_display,
            "start_date": start_str,
            "end_date": end_str,
            "time_str": time_str,
            "is_update": event.sequence > 0,
            "is_cancel": method == self.METHOD_CANCEL,
            "app_name": settings.APP_NAME,
            "app_url": settings.APP_URL,
            # Translated content blocks
            "content": {
                "title": t(f"email.{type_key}.title", lang),
                "heading": t(f"email.{type_key}.heading", lang),
                "body": t(
                    f"email.{type_key}.body",
                    lang,
                    organizer=organizer_display,
                    attendee=attendee_display,
                ),
                "badge": t(f"email.{type_key}.badge", lang),
            },
            "labels": {
                "when": t("email.labels.when", lang),
                "until": t("email.labels.until", lang),
                "location": t("email.labels.location", lang),
                "videoConference": t("email.labels.videoConference", lang),
                "organizer": t("email.labels.organizer", lang),
                "attendee": t("email.labels.attendee", lang),
                "description": t("email.labels.description", lang),
                "wasScheduledFor": t("email.labels.wasScheduledFor", lang),
            },
            "actions": {
                "accept": t("email.actions.accept", lang),
                "maybe": t("email.actions.maybe", lang),
                "decline": t("email.actions.decline", lang),
            },
            "instructions": t(f"email.instructions.{type_key}", lang),
            "footer": t(
                f"email.footer.{'invitation' if type_key == 'invitation' else 'notification'}",
                lang,
                appName=settings.APP_NAME,
            ),
        }

        # Add RSVP links for REQUEST method (invitations and updates)
        if method == self.METHOD_REQUEST:
            context.update(self._build_rsvp_context(event, org_id=org_id))

        return context

    def _prepare_ics_attachment(self, icalendar_data: str, method: str) -> str:
        """
        Prepare ICS content for attachment.

        When CALENDAR_ITIP_ENABLED is True, sets the METHOD property so that
        calendar clients show Accept/Decline buttons (standard iTIP flow).
        When False (default), strips METHOD so the ICS is treated as a plain
        calendar object — our own RSVP web links handle responses instead.
        """
        itip_enabled = settings.CALENDAR_ITIP_ENABLED

        if itip_enabled:
            if "METHOD:" not in icalendar_data.upper():
                icalendar_data = re.sub(
                    r"(VERSION:2\.0\r?\n)",
                    rf"\1METHOD:{method}\r\n",
                    icalendar_data,
                    flags=re.IGNORECASE,
                )
            else:
                icalendar_data = re.sub(
                    r"METHOD:[^\r\n]+",
                    f"METHOD:{method}",
                    icalendar_data,
                    flags=re.IGNORECASE,
                )
        else:
            # Strip any existing METHOD so clients treat it as a plain event
            icalendar_data = re.sub(
                r"METHOD:[^\r\n]+\r?\n",
                "",
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
        """Send via SMTP using Django's email backend.

        Thin wrapper around ``_build_calendar_email``: From is the system
        sender, Reply-To is the organizer so replies bypass the system
        address.
        """
        try:
            from_addr = (
                settings.CALENDAR_INVITATION_FROM_EMAIL or settings.DEFAULT_FROM_EMAIL
            )
            email = _build_calendar_email(
                from_email=from_addr,
                to_email=to_email,
                reply_to=from_email,
                subject=subject,
                text_body=text_body,
                html_body=html_body,
                ics_content=ics_content,
                ics_method=ics_method,
                itip_enabled=settings.CALENDAR_ITIP_ENABLED,
            )
            email.send(fail_silently=False)

            logger.info(
                "Calendar invitation sent via SMTP: %s -> %s (method: %s, uid: %s)",
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

    def _send_via_messages(  # noqa: PLR0913  # pylint: disable=too-many-arguments,too-many-positional-arguments
        self,
        mailbox_email: str,
        to_email: str,
        subject: str,
        text_body: str,
        html_body: str,
        ics_content: str,
        ics_method: str,
        event_uid: str,
    ) -> bool:
        """Send via the Messages API from a mailbox.

        Looks up the mailbox by email, builds the SAME MIME structure as
        the SMTP path, renders it to bytes, and POSTs it. No SMTP
        fallback — mailbox invitations must come from the mailbox identity
        or not at all.
        """
        try:
            from core.services.messages_service import (  # noqa: PLC0415  # pylint: disable=import-outside-toplevel
                MessagesService,
            )

            messages = MessagesService()
            mailbox = messages.get_mailbox_by_email(mailbox_email)
            if not mailbox:
                logger.error(
                    "Mailbox %s not found in Messages (lookup may have errored — "
                    "check earlier 'fetch_mailboxes failed' lines), cannot send "
                    "invitation to %s (uid: %s)",
                    mailbox_email,
                    to_email,
                    event_uid,
                )
                return False

            mailbox_id = mailbox.get("id")
            if not mailbox_id:
                logger.error(
                    "Mailbox %s has no id in Messages response (got %r), "
                    "cannot send invitation to %s (uid: %s)",
                    mailbox_email,
                    mailbox_id,
                    to_email,
                    event_uid,
                )
                return False

            email = _build_calendar_email(
                from_email=mailbox_email,
                to_email=to_email,
                # From is already the mailbox/organizer; an extra Reply-To
                # would be redundant noise on mailbox-calendar invites.
                reply_to=None,
                subject=subject,
                text_body=text_body,
                html_body=html_body,
                ics_content=ics_content,
                ics_method=ics_method,
                itip_enabled=settings.CALENDAR_ITIP_ENABLED,
            )
            # ``message()`` builds the SafeMIMEMultipart and adds Date.
            # ``linesep="\r\n"`` forces CRLF line endings (RFC 5322 §2.1)
            # — Django's ``MIMEMixin.as_bytes`` default is ``"\n"``, which
            # strict MTAs reject and lenient ones may rewrite in a way
            # that changes content hashes and Message-IDs. The Messages
            # submit endpoint and any MTA downstream both expect CRLF.
            mime_bytes = email.message().as_bytes(linesep="\r\n")

            success = messages.submit_raw_message(
                mailbox_id=mailbox_id,
                rcpt_to=to_email,
                mime_bytes=mime_bytes,
                correlation_id=event_uid,
            )

            if success:
                logger.info(
                    "Calendar invitation sent via Messages: %s -> %s (uid: %s)",
                    mailbox_email,
                    to_email,
                    event_uid,
                )
            else:
                logger.error(
                    "Messages API send failed for %s -> %s (uid: %s)",
                    mailbox_email,
                    to_email,
                    event_uid,
                )
            return success

        except Exception:  # pylint: disable=broad-exception-caught
            logger.exception(
                "Failed to send via Messages for %s -> %s (uid: %s)",
                mailbox_email,
                to_email,
                event_uid,
            )
            return False


# Singleton instance for convenience
calendar_invitation_service = CalendarInvitationService()
