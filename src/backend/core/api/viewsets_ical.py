"""iCal subscription export views."""

import logging

from django.conf import settings
from django.http import Http404, HttpResponse
from django.utils import timezone
from django.utils.decorators import method_decorator
from django.views import View
from django.views.decorators.csrf import csrf_exempt

import requests

from core.models import CalendarSubscriptionToken

logger = logging.getLogger(__name__)


@method_decorator(csrf_exempt, name="dispatch")
class ICalExportView(View):
    """
    Public endpoint for iCal calendar exports.

    This view serves calendar data in iCal format without requiring authentication.
    The token in the URL path acts as the authentication mechanism.

    URL format: /ical/<uuid:token>.ics

    The view proxies the request to SabreDAV's ICSExportPlugin, which generates
    RFC 5545 compliant iCal data.
    """

    def get(self, request, token):
        """Handle GET requests for iCal export."""
        # Lookup token
        subscription = (
            CalendarSubscriptionToken.objects.filter(token=token, is_active=True)
            .select_related("owner")
            .first()
        )

        if not subscription:
            logger.warning("Invalid or inactive subscription token: %s", token)
            raise Http404("Calendar not found")

        # Update last_accessed_at atomically to avoid race conditions
        # when multiple calendar clients poll simultaneously
        CalendarSubscriptionToken.objects.filter(token=token, is_active=True).update(
            last_accessed_at=timezone.now()
        )

        # Proxy to SabreDAV
        caldav_url = settings.CALDAV_URL
        outbound_api_key = settings.CALDAV_OUTBOUND_API_KEY

        if not outbound_api_key:
            logger.error("CALDAV_OUTBOUND_API_KEY is not configured")
            return HttpResponse(status=500, content="iCal export not configured")

        # Build the CalDAV export URL
        # caldav_path is like "/calendars/user@example.com/calendar-uuid/"
        # We need to call /api/v1.0/caldav/calendars/user@example.com/calendar-uuid?export
        base_uri_path = "/api/v1.0/caldav"
        caldav_path = subscription.caldav_path.lstrip("/")
        target_url = f"{caldav_url}{base_uri_path}/{caldav_path}?export"

        # Prepare headers for CalDAV server
        headers = {
            "X-Forwarded-User": subscription.owner.email,
            "X-Api-Key": outbound_api_key,
        }

        try:
            logger.debug(
                "Proxying iCal export for caldav_path %s to %s",
                subscription.caldav_path,
                target_url,
            )
            response = requests.get(
                target_url,
                headers=headers,
                timeout=30,  # Balanced timeout: allows large calendars while preventing DoS
            )

            if response.status_code != 200:
                logger.error(
                    "CalDAV server returned %d for iCal export: %s",
                    response.status_code,
                    response.content[:500],
                )
                return HttpResponse(
                    status=502,
                    content="Error generating calendar data",
                    content_type="text/plain",
                )

            # Return ICS response
            django_response = HttpResponse(
                content=response.content,
                status=200,
                content_type="text/calendar; charset=utf-8",
            )
            # Set filename for download (use calendar_name or fallback to "calendar")
            display_name = subscription.calendar_name or "calendar"
            safe_name = display_name.replace('"', '\\"')
            django_response["Content-Disposition"] = (
                f'attachment; filename="{safe_name}.ics"'
            )
            # Prevent caching of potentially sensitive data
            django_response["Cache-Control"] = "no-store, private"
            # Prevent token leakage via referrer
            django_response["Referrer-Policy"] = "no-referrer"

            return django_response

        except requests.exceptions.RequestException as e:
            logger.error("CalDAV server error during iCal export: %s", str(e))
            return HttpResponse(
                status=502,
                content="Calendar server unavailable",
                content_type="text/plain",
            )
