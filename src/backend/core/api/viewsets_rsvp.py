"""RSVP view for handling invitation responses from email links.

GET  /rsvp/?token=...&action=accepted  -> renders a confirmation page that
     auto-submits via JavaScript (no extra click for the user).
POST /api/v1.0/rsvp/                   -> processes the RSVP and returns a
     result page. Link previewers / prefetchers only issue GET, so the
     state-changing work is safely behind POST.
"""

import logging
import re
from datetime import timezone as dt_timezone

from django.conf import settings
from django.core.signing import BadSignature, SignatureExpired, TimestampSigner
from django.shortcuts import render
from django.utils import timezone
from django.utils.decorators import method_decorator
from django.views import View
from django.views.decorators.csrf import csrf_exempt

from rest_framework.throttling import AnonRateThrottle
from rest_framework.views import APIView

from core.models import User
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


def _render_error(request, message, lang="en"):
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
                dt = dt.replace(tzinfo=dt_timezone.utc)
            return dt < timezone.now()

    return False


def _validate_token(token, max_age=None):
    """Unsign and validate an RSVP token.

    Returns (payload, error_key). On success error_key is None.
    """
    ts_signer = TimestampSigner(salt="rsvp")
    try:
        payload = ts_signer.unsign_object(token, max_age=max_age)
    except SignatureExpired:
        return None, "token_expired"
    except BadSignature:
        return None, "invalid_token"

    uid = payload.get("uid")
    recipient_email = payload.get("email")
    organizer_email = payload.get("organizer", "")
    # Strip mailto: prefix (case-insensitive) in case it leaked into the token
    organizer_email = re.sub(r"^mailto:", "", organizer_email, flags=re.IGNORECASE)

    if not uid or not recipient_email or not organizer_email:
        return None, "invalid_payload"

    payload["organizer"] = organizer_email
    return payload, None


_TOKEN_ERROR_KEYS = {
    "token_expired": "rsvp.error.tokenExpired",
    "invalid_token": "rsvp.error.invalidToken",
    "invalid_payload": "rsvp.error.invalidPayload",
}


def _validate_and_render_error(request, token, action, lang):
    """Validate action + token; return (payload, error_response).

    On success error_response is None.
    """
    t = TranslationService.t

    if action not in PARTSTAT_VALUES:
        return None, _render_error(request, t("rsvp.error.invalidAction", lang), lang)

    payload, error = _validate_token(
        token, max_age=settings.RSVP_TOKEN_MAX_AGE_RECURRING
    )
    if error:
        return None, _render_error(request, t(_TOKEN_ERROR_KEYS[error], lang), lang)

    return payload, None


@method_decorator(csrf_exempt, name="dispatch")
class RSVPConfirmView(View):
    """GET handler: render auto-submitting confirmation page.

    This page is safe for link previewers / prefetchers because it
    doesn't change any state — only the POST endpoint does.
    """

    def get(self, request):
        """Render a page that auto-submits the RSVP via POST."""
        token = request.GET.get("token", "")
        action = request.GET.get("action", "")
        lang = TranslationService.resolve_language(request=request)

        _, error_response = _validate_and_render_error(request, token, action, lang)
        if error_response:
            return error_response

        # Render auto-submit page
        label = TranslationService.t(f"rsvp.{action}", lang)
        return render(
            request,
            "rsvp/confirm.html",
            {
                "page_title": label,
                "token": token,
                "action": action,
                "lang": lang,
                "heading": label,
                "status_icon": PARTSTAT_ICONS[action],
                "header_color": PARTSTAT_COLORS[action],
                "submit_label": label,
                "post_url": f"/api/{settings.API_VERSION}/rsvp/",
            },
        )


class RSVPThrottle(AnonRateThrottle):
    """Throttle RSVP POST requests: 30/min per IP."""

    rate = "30/minute"


def _process_rsvp(request, payload, action, lang):
    """Execute the RSVP: find event, update PARTSTAT, PUT back.

    Returns an error response on failure, or the updated calendar data
    string on success.
    """
    t = TranslationService.t
    http = CalDAVHTTPClient()

    try:
        organizer = User.objects.get(email=payload["organizer"])
    except User.DoesNotExist:
        return _render_error(request, t("rsvp.error.eventNotFound", lang), lang)

    calendar_data, href, etag = http.find_event_by_uid(organizer, payload["uid"])
    if not calendar_data or not href:
        return _render_error(request, t("rsvp.error.eventNotFound", lang), lang)

    if _is_event_past(calendar_data):
        return _render_error(request, t("rsvp.error.eventPast", lang), lang)

    updated_data = CalDAVHTTPClient.update_attendee_partstat(
        calendar_data, payload["email"], PARTSTAT_VALUES[action]
    )
    if not updated_data:
        return _render_error(request, t("rsvp.error.notAttendee", lang), lang)

    if not http.put_event(organizer, href, updated_data, etag=etag):
        return _render_error(request, t("rsvp.error.updateFailed", lang), lang)

    return calendar_data


class RSVPProcessView(APIView):
    """POST handler: actually process the RSVP.

    Uses DRF's AnonRateThrottle for rate limiting. No authentication
    required — the signed token acts as authorization.
    """

    authentication_classes = []
    permission_classes = []
    throttle_classes = [RSVPThrottle]

    def post(self, request):
        """Process the RSVP response."""
        token = request.data.get("token", "")
        action = request.data.get("action", "")
        lang = TranslationService.resolve_language(request=request)
        t = TranslationService.t

        payload, error_response = _validate_and_render_error(
            request, token, action, lang
        )
        if error_response:
            return error_response

        result = _process_rsvp(request, payload, action, lang)

        # result is either an error HttpResponse or calendar data string
        if not isinstance(result, str):
            return result

        from core.services.calendar_invitation_service import (  # noqa: PLC0415  # pylint: disable=import-outside-toplevel
            ICalendarParser,
        )

        summary = ICalendarParser.extract_property(result, "SUMMARY") or ""
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
