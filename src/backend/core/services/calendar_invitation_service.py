"""
Calendar Invitation Email Service.

This service handles parsing iCalendar data and sending invitation emails
with ICS file attachments for CalDAV scheduling (RFC 6638/6047).

The service is called by the CalDAVSchedulingCallbackView when the CalDAV
server (sabre/dav) needs to send invitations to external attendees.
"""

import logging
import re
import smtplib
import ssl
from datetime import datetime
from email import encoders
from email.mime.base import MIMEBase
from email.utils import formatdate, make_msgid
from typing import Optional
from urllib.parse import urlencode, urlparse

from django.conf import settings
from django.core.mail import EmailMultiAlternatives, get_connection
from django.core.signing import TimestampSigner
from django.template.loader import render_to_string

from core.models import User
from core.services.icalendar_parser import EventDetails, ICalendarParser
from core.services.translation_service import TranslationService

logger = logging.getLogger(__name__)


class InvitationNotSentError(Exception):
    """The server did not accept the email, so a retry is safe."""


def _is_temporary_refusal(error: Exception) -> bool:
    """Return True when the SMTP server refuses the email for now (4xx code).

    The server refuses the sender, all the recipients, or the data. After a
    4xx answer, the server does not deliver the email (RFC 5321, 4.2.5).
    """
    if isinstance(error, (smtplib.SMTPSenderRefused, smtplib.SMTPDataError)):
        codes = [error.smtp_code]
    elif isinstance(error, smtplib.SMTPRecipientsRefused):
        codes = [code for code, _ in error.recipients.values()]
    else:
        return False
    return bool(codes) and all(400 <= code < 500 for code in codes)


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
    email_date: Optional[datetime] = None,
) -> _CalendarEmail:
    """Build the email for the SMTP and the Messages transports.

    The two transports get the same MIME structure and the same header
    rules.

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
    # Without a Date header, Django uses the time of the build.
    if email_date is not None:
        extra_headers["Date"] = formatdate(
            email_date.timestamp(), localtime=settings.EMAIL_USE_LOCALTIME
        )

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

    def send_invitation(  # noqa: PLR0913  # pylint: disable=too-many-arguments,too-many-positional-arguments,too-many-locals
        self,
        sender_email: str,
        recipient_email: str,
        method: str,
        icalendar_data: str,
        is_mailbox: bool = False,
        org_id: str = "",
        is_new_attendee: bool = False,
        email_date: Optional[datetime] = None,
        recurrence_id: str = "",
        previous_start: str = "",
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
            is_new_attendee: If True, the recipient is not on the previous
                version of the event, so the email is an invitation and not
                an update
            email_date: The Date header of the email. If None, it is the
                time of the send
            recurrence_id: The RECURRENCE-ID value of the only date of a
                series that the change affects, or "" for other changes
            previous_start: The start of this date before the change

        Returns:
            True if email was sent successfully, False otherwise

        Raises:
            InvitationNotSentError: the SMTP server or the Messages mailbox
                is not available, and the server did not accept the email
        """
        # Clean email addresses (remove mailto: prefix)
        sender = sender_email.replace("mailto:", "").strip()
        recipient = recipient_email.replace("mailto:", "").strip()

        # Parse event details
        # A REPLY goes from the attendee to the organizer: the attendee is
        # the sender.
        event = self.parser.parse(
            icalendar_data,
            sender if method == self.METHOD_REPLY else recipient,
            recurrence_id,
            previous_start,
        )
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

            is_update = self._is_update(event) and not is_new_attendee

            # Determine email type and get appropriate subject/content
            if method == self.METHOD_CANCEL:
                subject = t("email.subject.cancel", lang, summary=summary)
                template_prefix = "calendar_invitation_cancel"
            elif method == self.METHOD_REPLY:
                subject = t("email.subject.reply", lang, summary=summary)
                template_prefix = "calendar_invitation_reply"
            elif is_update:
                subject = t("email.subject.update", lang, summary=summary)
                template_prefix = "calendar_invitation_update"
            else:
                subject = t("email.subject.invitation", lang, summary=summary)
                template_prefix = "calendar_invitation"

            # Build context for templates
            context = self._build_template_context(
                event, method, lang, org_id=org_id, is_update=is_update
            )

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
                    email_date=email_date,
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
                email_date=email_date,
            )

        except InvitationNotSentError:
            raise
        except Exception as e:  # pylint: disable=broad-exception-caught
            logger.exception(
                "Failed to send calendar invitation to %s: %s", recipient, e
            )
            return False

    @staticmethod
    def _is_update(event: EventDetails) -> bool:
        """Tell if a REQUEST changes a known event.

        A changed date of a series is a change, also when its SEQUENCE
        is 0.
        """
        return event.sequence > 0 or event.original_start is not None

    @staticmethod
    def _format_original_date(event: EventDetails, lang: str) -> str:
        """Return the date before the change, or "" when it did not move."""
        original = event.original_start
        if original is None:
            return ""
        if not isinstance(original, datetime):
            if event.is_all_day and original == event.dtstart.date():
                return ""
            return TranslationService.format_date(original, lang)
        if original == event.dtstart:
            return ""
        date_str = TranslationService.format_date(original, lang)
        return f"{date_str} · {original.strftime('%H:%M')}"

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

    def _build_template_context(  # pylint: disable=too-many-arguments
        self,
        event: EventDetails,
        method: str,
        lang: str = "fr",
        org_id: str = "",
        *,
        is_update: bool | None = None,
    ) -> dict:
        """Build context dictionary for email templates.

        When ``is_update`` is None, a SEQUENCE above 0 or a changed date
        makes a REQUEST an update.
        """
        if is_update is None:
            is_update = self._is_update(event)
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
        elif is_update:
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
            "original_date": (
                self._format_original_date(event, lang)
                if is_update and method == self.METHOD_REQUEST
                else ""
            ),
            "is_update": is_update,
            "is_cancel": method == self.METHOD_CANCEL,
            "app_name": settings.APP_NAME,
            "app_url": settings.APP_URL,
            "logo_img": settings.EMAIL_LOGO_IMG
            or f"{settings.APP_URL}{settings.STATIC_URL}images/logo-calendriers.png",
            "footer_img": settings.EMAIL_FOOTER_IMG,
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
        email_date: Optional[datetime] = None,
    ) -> bool:
        """Send via SMTP using Django's email backend.

        Thin wrapper around ``_build_calendar_email``: From is the system
        sender, Reply-To is the organizer so replies bypass the system
        address.
        """
        connection = get_connection(fail_silently=False)
        try:
            connection.open()
        except smtplib.SMTPAuthenticationError as e:
            # A 4xx code is a temporary failure (RFC 4954). Another code is a
            # configuration error, and a retry does not fix it.
            if not 400 <= e.smtp_code < 500:
                raise
            raise InvitationNotSentError(
                f"The SMTP server cannot check the login for now: {e}"
            ) from e
        except ssl.SSLCertVerificationError:
            # A retry does not fix a configuration error.
            raise
        except OSError as e:
            raise InvitationNotSentError(
                f"Cannot connect to the SMTP server: {e}"
            ) from e

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
                email_date=email_date,
            )
            connection.send_messages([email])

            logger.info(
                "Calendar invitation sent via SMTP: %s -> %s (method: %s, uid: %s)",
                from_email,
                to_email,
                ics_method,
                event_uid,
            )
            return True

        except Exception as e:  # pylint: disable=broad-exception-caught
            if _is_temporary_refusal(e):
                raise InvitationNotSentError(
                    f"The SMTP server refuses the email for now: {e}"
                ) from e
            logger.exception(
                "Failed to send calendar invitation email to %s: %s", to_email, e
            )
            return False
        finally:
            connection.close()

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
        email_date: Optional[datetime] = None,
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
                MessagesServiceError,
            )

            messages = MessagesService()
            try:
                mailbox = messages.get_mailbox_by_email(mailbox_email)
            except MessagesServiceError as e:
                raise InvitationNotSentError(
                    f"Cannot look up the mailbox {mailbox_email} in Messages: {e}"
                ) from e
            if not mailbox:
                logger.error(
                    "Mailbox %s not found in Messages, cannot send the invitation "
                    "to %s (uid: %s)",
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
                email_date=email_date,
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

        except InvitationNotSentError:
            raise
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
