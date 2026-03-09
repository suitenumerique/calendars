"""iCal subscription export views."""

import logging

from django.core.cache import cache
from django.http import Http404, HttpResponse
from django.utils import timezone
from django.utils.decorators import method_decorator
from django.utils.text import slugify
from django.views import View
from django.views.decorators.csrf import csrf_exempt

import requests

from core.models import Channel, urlsafe_to_uuid
from core.services.caldav_service import CalDAVHTTPClient

logger = logging.getLogger(__name__)

ICAL_RATE_LIMIT = 5  # requests per minute per channel
ICAL_RATE_WINDOW = 60  # seconds


@method_decorator(csrf_exempt, name="dispatch")
class ICalExportView(View):
    """
    Public endpoint for iCal calendar exports.

    This view serves calendar data in iCal format without requiring authentication.
    The channel_id in the URL is used for lookup, and the token for authentication.

    URL format: /ical/<short_id>/<token>/<slug>.ics

    Looks up a Channel by base64url-encoded ID, verifies the token, then
    proxies the request to SabreDAV's ICSExportPlugin.
    """

    def get(self, request, short_id, token):
        """Handle GET requests for iCal export."""
        try:
            channel_id = urlsafe_to_uuid(short_id)
            channel = Channel.objects.get(pk=channel_id, is_active=True)
        except (ValueError, Channel.DoesNotExist) as exc:
            raise Http404("Calendar not found") from exc

        if channel.type != "ical-feed":
            raise Http404("Calendar not found")

        if not channel.verify_token(token):
            raise Http404("Calendar not found")

        if not channel.user:
            logger.warning("ical-feed channel %s has no user", channel.id)
            raise Http404("Calendar not found")

        # Rate limit: 5 requests per minute per channel
        rate_key = f"ical_rate:{channel_id}"
        hits = cache.get(rate_key, 0)
        if hits >= ICAL_RATE_LIMIT:
            return HttpResponse(status=429, content="Too many requests")
        cache.set(rate_key, hits + 1, ICAL_RATE_WINDOW)

        # Update last_used_at
        Channel.objects.filter(pk=channel.pk).update(last_used_at=timezone.now())

        # Proxy to SabreDAV
        http = CalDAVHTTPClient()
        try:
            caldav_path = channel.caldav_path.lstrip("/")
            response = http.request(
                "GET",
                channel.user,
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
        calendar_name = channel.settings.get("calendar_name", "")
        filename = slugify(calendar_name)[:50] or "feed"
        django_response["Content-Disposition"] = (
            f'attachment; filename="{filename}.ics"'
        )
        django_response["Cache-Control"] = "no-store, private"
        django_response["Referrer-Policy"] = "no-referrer"

        return django_response
