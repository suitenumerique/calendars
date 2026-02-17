"""iCal subscription export views."""

import logging

from django.http import Http404, HttpResponse
from django.utils import timezone
from django.utils.decorators import method_decorator
from django.views import View
from django.views.decorators.csrf import csrf_exempt

import requests

from core.models import CalendarSubscriptionToken
from core.services.caldav_service import CalDAVHTTPClient

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
        http = CalDAVHTTPClient()
        try:
            caldav_path = subscription.caldav_path.lstrip("/")
            response = http.request(
                "GET",
                subscription.owner.email,
                caldav_path,
                query="export",
            )
        except ValueError:
            logger.error("CALDAV_OUTBOUND_API_KEY is not configured")
            return HttpResponse(status=500, content="iCal export not configured")
        except requests.exceptions.RequestException as e:
            logger.error("CalDAV server error during iCal export: %s", str(e))
            return HttpResponse(
                status=502,
                content="Calendar server unavailable",
                content_type="text/plain",
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
