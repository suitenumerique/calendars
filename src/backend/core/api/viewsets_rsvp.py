"""RSVP view for handling invitation responses from email links."""

import logging
import re

from django.core.signing import BadSignature, Signer
from django.shortcuts import render
from django.utils import timezone
from django.utils.decorators import method_decorator
from django.views import View
from django.views.decorators.csrf import csrf_exempt

from core.services.caldav_service import CalDAVHTTPClient
from core.services.translation_service import TranslationService

logger = logging.getLogger(__name__)

PARTSTAT_ICONS = {
    "accepted": "&#9989;",  # green check
    "tentative": "&#10067;",  # question mark
    "declined": "&#10060;",  # red cross
}

PARTSTAT_COLORS = {
    "accepted": "#16a34a",
    "tentative": "#d97706",
    "declined": "#dc2626",
}

PARTSTAT_VALUES = {
    "accepted": "ACCEPTED",
    "tentative": "TENTATIVE",
    "declined": "DECLINED",
}


def _render_error(request, message, lang="fr"):
    """Render the RSVP error page."""
    t = TranslationService.t
    return render(
        request,
        "rsvp/response.html",
        {
            "page_title": t("rsvp.error.title", lang),
            "error": message,
            "error_title": t("rsvp.error.invalidLink", lang),
            "header_color": "#dc2626",
            "lang": lang,
        },
        status=400,
    )


def _is_event_past(icalendar_data):
    """Check if the event has already ended.

    For recurring events without DTEND, falls back to DTSTART.
    If the event has an RRULE, it is never considered past (the
    recurrence may extend indefinitely).
    """
    from core.services.calendar_invitation_service import (  # noqa: PLC0415  # pylint: disable=import-outside-toplevel
        ICalendarParser,
    )

    vevent = ICalendarParser.extract_vevent_block(icalendar_data)
    if not vevent:
        return False

    # Recurring events may have future occurrences — don't reject them
    rrule, _ = ICalendarParser.extract_property_with_params(vevent, "RRULE")
    if rrule:
        return False

    # Use DTEND if available, otherwise DTSTART
    for prop in ("DTEND", "DTSTART"):
        raw, params = ICalendarParser.extract_property_with_params(vevent, prop)
        dt = ICalendarParser.parse_datetime(raw, params.get("TZID"))
        if dt:
            # Make timezone-aware if naive (assume UTC)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt < timezone.now()

    return False


@method_decorator(csrf_exempt, name="dispatch")
class RSVPView(View):
    """Handle RSVP responses from invitation email links."""

    def get(self, request):  # noqa: PLR0911
        """Process an RSVP response."""
        token = request.GET.get("token", "")
        action = request.GET.get("action", "")
        lang = TranslationService.resolve_language(request=request)
        t = TranslationService.t

        # Validate action
        if action not in PARTSTAT_VALUES:
            return _render_error(request, t("rsvp.error.invalidAction", lang), lang)

        # Unsign token — tokens don't have a built-in expiry,
        # but RSVPs are rejected once the event has ended (_is_event_past).
        signer = Signer(salt="rsvp")
        try:
            payload = signer.unsign_object(token)
        except BadSignature:
            return _render_error(request, t("rsvp.error.invalidToken", lang), lang)

        uid = payload.get("uid")
        recipient_email = payload.get("email")
        # Strip mailto: prefix (case-insensitive) in case it leaked into the token
        organizer_email = re.sub(
            r"^mailto:", "", payload.get("organizer", ""), flags=re.IGNORECASE
        )

        if not uid or not recipient_email or not organizer_email:
            return _render_error(request, t("rsvp.error.invalidPayload", lang), lang)

        http = CalDAVHTTPClient()

        # Find the event in the organizer's CalDAV calendars
        calendar_data, href = http.find_event_by_uid(organizer_email, uid)
        if not calendar_data or not href:
            return _render_error(request, t("rsvp.error.eventNotFound", lang), lang)

        # Check if the event is already over
        if _is_event_past(calendar_data):
            return _render_error(request, t("rsvp.error.eventPast", lang), lang)

        # Update the attendee's PARTSTAT
        partstat = PARTSTAT_VALUES[action]
        updated_data = CalDAVHTTPClient.update_attendee_partstat(
            calendar_data, recipient_email, partstat
        )
        if not updated_data:
            return _render_error(request, t("rsvp.error.notAttendee", lang), lang)

        # PUT the updated event back to CalDAV
        success = http.put_event(organizer_email, href, updated_data)
        if not success:
            return _render_error(request, t("rsvp.error.updateFailed", lang), lang)

        # Extract event summary for display
        from core.services.calendar_invitation_service import (  # noqa: PLC0415  # pylint: disable=import-outside-toplevel
            ICalendarParser,
        )

        summary = ICalendarParser.extract_property(calendar_data, "SUMMARY") or ""
        label = t(f"rsvp.{action}", lang)

        return render(
            request,
            "rsvp/response.html",
            {
                "page_title": label,
                "heading": label,
                "message": t("rsvp.responseSent", lang),
                "status_icon": PARTSTAT_ICONS[action],
                "header_color": PARTSTAT_COLORS[action],
                "event_summary": summary,
                "lang": lang,
            },
        )
