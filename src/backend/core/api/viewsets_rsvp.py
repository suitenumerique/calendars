"""RSVP view for handling invitation responses from email links."""

import logging
import re

from django.conf import settings
from django.core.signing import BadSignature, Signer
from django.shortcuts import render
from django.utils import timezone
from django.utils.decorators import method_decorator
from django.views import View
from django.views.decorators.csrf import csrf_exempt

import icalendar
import requests

import caldav

logger = logging.getLogger(__name__)

PARTSTAT_LABELS = {
    "accepted": "Vous avez accepté l'invitation",
    "tentative": "Vous avez répondu « peut-être » à l'invitation",
    "declined": "Vous avez décliné l'invitation",
}

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


def _render_error(request, message):
    """Render the RSVP error page."""
    return render(
        request,
        "rsvp/response.html",
        {
            "page_title": "Erreur",
            "error": message,
            "error_title": "Lien invalide",
            "header_color": "#dc2626",
        },
        status=400,
    )


def _is_event_past(icalendar_data):
    """Check if the event has already ended."""
    from core.services.calendar_invitation_service import (  # noqa: PLC0415  # pylint: disable=import-outside-toplevel
        ICalendarParser,
    )

    vevent = ICalendarParser.extract_vevent_block(icalendar_data)
    if not vevent:
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


def _get_caldav_client(organizer_email):
    """Build a caldav.DAVClient authenticated as the given organizer."""
    caldav_url = settings.CALDAV_URL
    outbound_api_key = settings.CALDAV_OUTBOUND_API_KEY
    if not outbound_api_key:
        logger.error("CALDAV_OUTBOUND_API_KEY is not configured")
        return None

    return caldav.DAVClient(
        url=f"{caldav_url}/api/v1.0/caldav/",
        headers={
            "X-Forwarded-User": organizer_email,
            "X-Api-Key": outbound_api_key,
        },
    )


def _find_event_in_caldav(organizer_email, event_uid):
    """
    Find an event by UID across all of the organizer's calendars.

    Returns (calendar_data, event_href) or (None, None).
    """
    client = _get_caldav_client(organizer_email)
    if client is None:
        return None, None

    try:
        principal = client.principal()
        for cal in principal.calendars():
            try:
                event = cal.object_by_uid(event_uid)
                return event.data, str(event.url.path)
            except caldav.error.NotFoundError:
                continue

        logger.warning(
            "Event UID %s not found in organizer %s calendars",
            event_uid,
            organizer_email,
        )
        return None, None

    except Exception:
        logger.exception("CalDAV error looking up event %s", event_uid)
        return None, None


def _update_attendee_partstat(icalendar_data, attendee_email, new_partstat):
    """
    Update the PARTSTAT of an attendee in iCalendar data.

    Returns the modified iCalendar string, or None if attendee not found.
    """
    cal = icalendar.Calendar.from_ical(icalendar_data)
    updated = False

    for component in cal.walk("VEVENT"):
        for _name, attendee in component.property_items("ATTENDEE"):
            attendee_val = str(attendee).lower()
            if attendee_email.lower() in attendee_val:
                attendee.params["PARTSTAT"] = icalendar.vText(new_partstat)
                updated = True

    if not updated:
        return None

    return cal.to_ical().decode("utf-8")


def _put_event_to_caldav(organizer_email, href, icalendar_data):
    """PUT the updated event back to CalDAV."""
    outbound_api_key = settings.CALDAV_OUTBOUND_API_KEY
    if not outbound_api_key:
        logger.error("CALDAV_OUTBOUND_API_KEY is not configured")
        return False

    target_url = f"{settings.CALDAV_URL}{href}"
    headers = {
        "Content-Type": "text/calendar; charset=utf-8",
        "X-Forwarded-User": organizer_email,
        "X-Api-Key": outbound_api_key,
    }

    try:
        response = requests.put(
            url=target_url,
            headers=headers,
            data=icalendar_data.encode("utf-8"),
            timeout=30,
        )
        if response.status_code in (200, 201, 204):
            return True
        logger.error(
            "CalDAV PUT failed: %s %s",
            response.status_code,
            response.text[:500],
        )
        return False
    except requests.exceptions.RequestException:
        logger.exception("CalDAV PUT error for %s", href)
        return False


@method_decorator(csrf_exempt, name="dispatch")
class RSVPView(View):
    """Handle RSVP responses from invitation email links."""

    def get(self, request):  # noqa: PLR0911
        """Process an RSVP response."""
        token = request.GET.get("token", "")
        action = request.GET.get("action", "")

        # Validate action
        if action not in PARTSTAT_VALUES:
            return _render_error(request, "Action invalide.")

        # Unsign token (no expiry — invitations are valid indefinitely)
        signer = Signer(salt="rsvp")
        try:
            payload = signer.unsign_object(token)
        except BadSignature:
            return _render_error(request, "Ce lien est invalide ou a expiré.")

        uid = payload.get("uid")
        recipient_email = payload.get("email")
        # Strip mailto: prefix (case-insensitive) in case it leaked into the token
        organizer_email = re.sub(
            r"^mailto:", "", payload.get("organizer", ""), flags=re.IGNORECASE
        )

        if not uid or not recipient_email or not organizer_email:
            return _render_error(request, "Ce lien est invalide.")

        # Find the event in the organizer's CalDAV calendars
        calendar_data, href = _find_event_in_caldav(organizer_email, uid)
        if not calendar_data or not href:
            return _render_error(
                request,
                "L'événement n'a pas été trouvé. Il a peut-être été supprimé.",
            )

        # Check if the event is already over
        if _is_event_past(calendar_data):
            return _render_error(
                request,
                "Cet événement est déjà passé.",
            )

        # Update the attendee's PARTSTAT
        partstat = PARTSTAT_VALUES[action]
        updated_data = _update_attendee_partstat(
            calendar_data, recipient_email, partstat
        )
        if not updated_data:
            return _render_error(
                request,
                "Vous ne figurez pas parmi les participants de cet événement.",
            )

        # PUT the updated event back to CalDAV
        success = _put_event_to_caldav(organizer_email, href, updated_data)
        if not success:
            return _render_error(
                request,
                "Une erreur est survenue lors de la mise à jour. Veuillez réessayer.",
            )

        # Extract event summary for display
        from core.services.calendar_invitation_service import (  # noqa: PLC0415  # pylint: disable=import-outside-toplevel
            ICalendarParser,
        )

        summary = ICalendarParser.extract_property(calendar_data, "SUMMARY") or ""

        return render(
            request,
            "rsvp/response.html",
            {
                "page_title": PARTSTAT_LABELS[action],
                "heading": PARTSTAT_LABELS[action],
                "message": "Votre réponse a été envoyée à l'organisateur.",
                "status_icon": PARTSTAT_ICONS[action],
                "header_color": PARTSTAT_COLORS[action],
                "event_summary": summary,
            },
        )
