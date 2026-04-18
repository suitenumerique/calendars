"""RSVP view for handling invitation responses from email links.

Both verbs hit the same route ``/rsvp/``:

  - GET  /rsvp/?t=<signed-token>  renders a confirmation page that
    auto-submits the form via JavaScript. State-changing work is
    safely behind POST so link previewers / prefetchers can't act on
    the user's behalf.
  - POST /rsvp/                   processes the RSVP and renders the
    result page (also reached by the noscript fallback on the GET
    confirmation page).
"""

import logging
import re

from django.conf import settings
from django.core.signing import BadSignature, SignatureExpired, TimestampSigner
from django.shortcuts import render
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

    # Short keys: u=uid, e=email, o=organizer, g=org_id, a=action
    uid = payload.get("u")
    recipient_email = payload.get("e")
    organizer_email = payload.get("o", "")
    organizer_email = re.sub(r"^mailto:", "", organizer_email, flags=re.IGNORECASE)
    org_id = payload.get("g")
    action = payload.get("a")

    if (
        not uid
        or not recipient_email
        or not organizer_email
        or not org_id
        or not action
    ):
        return None, "invalid_payload"

    if action not in PARTSTAT_VALUES:
        return None, "invalid_payload"

    # Normalize to readable keys for downstream consumers
    payload["uid"] = uid
    payload["email"] = recipient_email
    payload["organizer"] = organizer_email
    payload["org_id"] = org_id
    payload["action"] = action
    return payload, None


_TOKEN_ERROR_KEYS = {
    "token_expired": "rsvp.error.tokenExpired",
    "invalid_token": "rsvp.error.invalidToken",
    "invalid_payload": "rsvp.error.invalidPayload",
}


def _validate_and_render_error(request, token, lang):
    """Validate token (which contains the action); return (payload, error_response).

    On success error_response is None.
    """
    t = TranslationService.t

    payload, error = _validate_token(
        token, max_age=settings.RSVP_TOKEN_MAX_AGE_RECURRING
    )
    if error:
        return None, _render_error(request, t(_TOKEN_ERROR_KEYS[error], lang), lang)

    return payload, None


@method_decorator(csrf_exempt, name="dispatch")
class RSVPConfirmView(View):
    """GET: render auto-submitting confirmation page.
    POST: noscript fallback that processes the RSVP directly.

    GET is safe for link previewers / prefetchers because it
    doesn't change any state. JS auto-submits via fetch() to the
    API endpoint; the noscript form falls back to POST here.
    """

    def get(self, request):
        """Render a page that auto-submits the RSVP via fetch()."""
        token = request.GET.get("t", "")
        lang = TranslationService.resolve_language(request=request)

        payload, error_response = _validate_and_render_error(request, token, lang)
        if error_response:
            return error_response

        action = payload["action"]
        label = TranslationService.t(f"rsvp.{action}", lang)
        return render(
            request,
            "rsvp/confirm.html",
            {
                "page_title": label,
                "token": token,
                "lang": lang,
                "heading": label,
                "status_icon": PARTSTAT_ICONS[action],
                "header_color": PARTSTAT_COLORS[action],
                "submit_label": label,
            },
        )

    def post(self, request):
        """Process the RSVP and render the result page.

        Reached by the auto-submitting form on the GET confirmation
        page (the common path) and by the noscript fallback (the
        progressive-enhancement path).
        """
        # Support both DRF's request.data and Django's request.POST.
        data = getattr(request, "data", None) or request.POST
        token = data.get("token", "") or data.get("t", "")
        lang = TranslationService.resolve_language(request=request)
        t = TranslationService.t

        payload, error_response = _validate_and_render_error(request, token, lang)
        if error_response:
            return error_response

        action = payload["action"]
        result = _process_rsvp(request, payload, action, lang)

        if not isinstance(result, str):
            return result

        summary = result
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


def _process_rsvp(request, payload, action, lang):
    """Execute the RSVP via the CalDAV internal API.

    The internal API finds the event by UID across all principals
    matching the organizer email (both principals/users/ and
    principals/mailboxes/) and updates the attendee's PARTSTAT
    atomically. No principal namespace selection needed.

    Returns an error response on failure, or True on success.
    """
    t = TranslationService.t
    http = CalDAVHTTPClient()

    organizer = _MailboxPrincipalProxy(
        payload["organizer"], org_id=payload.get("org_id")
    )

    try:
        resp = http.internal_request(
            "POST",
            organizer,
            "internal-api/rsvp/",
            json={
                "organizer_email": payload["organizer"],
                "uid": payload["uid"],
                "attendee_email": payload["email"],
                "partstat": PARTSTAT_VALUES[action],
            },
        )
    except Exception:  # pylint: disable=broad-exception-caught
        logger.exception("RSVP internal API call failed")
        return _render_error(request, t("rsvp.error.updateFailed", lang), lang)

    if resp.status_code == 404:
        body = resp.json() if resp.text else {}
        if body.get("error") == "Attendee not found in event":
            return _render_error(request, t("rsvp.error.notAttendee", lang), lang)
        return _render_error(request, t("rsvp.error.eventNotFound", lang), lang)

    if resp.status_code != 200:
        return _render_error(request, t("rsvp.error.updateFailed", lang), lang)

    body = resp.json() if resp.text else {}
    return body.get("summary", "")


class _MailboxPrincipalProxy:
    """Lightweight proxy to authenticate CalDAV requests as a mailbox principal.

    CalDAVHTTPClient.build_base_headers() expects an object with .email
    and .organization_id attributes. This proxy provides those for mailbox
    principals that don't have a corresponding Django User.
    """

    def __init__(self, email, org_id=None):
        self.email = email
        self.organization_id = org_id
