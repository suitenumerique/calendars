"""CalDAV proxy views for forwarding requests to CalDAV server."""

import logging
import secrets

from django.conf import settings
from django.http import HttpResponse
from django.utils.decorators import method_decorator
from django.views import View
from django.views.decorators.csrf import csrf_exempt

import requests

logger = logging.getLogger(__name__)


@method_decorator(csrf_exempt, name="dispatch")
class CalDAVProxyView(View):
    """
    Proxy view that forwards all CalDAV requests to CalDAV server.
    Handles authentication and adds appropriate headers.

    CSRF protection is disabled because CalDAV uses non-standard HTTP methods
    (PROPFIND, REPORT, etc.) that don't work with Django's CSRF middleware.
    Authentication is handled via session cookies instead.
    """

    def dispatch(self, request, *args, **kwargs):
        """Forward all HTTP methods to CalDAV server."""
        # Handle CORS preflight requests
        if request.method == "OPTIONS":
            response = HttpResponse(status=200)
            response["Access-Control-Allow-Methods"] = (
                "GET, OPTIONS, PROPFIND, REPORT, MKCOL, MKCALENDAR, PUT, DELETE"
            )
            response["Access-Control-Allow-Headers"] = (
                "Content-Type, depth, authorization, if-match, if-none-match, prefer"
            )
            return response

        if not request.user.is_authenticated:
            return HttpResponse(status=401)

        # Build the CalDAV server URL
        caldav_url = settings.CALDAV_URL
        path = kwargs.get("path", "")

        # Use user email as the principal (CalDAV server uses email as username)
        user_principal = request.user.email

        # Build target URL - CalDAV server uses base URI /api/v1.0/caldav/
        # The proxy receives requests at /api/v1.0/caldav/... and forwards them
        # to the CalDAV server at the same path (sabre/dav expects requests at its base URI)
        base_uri_path = "/api/v1.0/caldav"
        clean_path = path.lstrip("/") if path else ""

        # Construct target URL - always include the base URI path
        if clean_path:
            target_url = f"{caldav_url}{base_uri_path}/{clean_path}"
        else:
            # Root request - use base URI path
            target_url = f"{caldav_url}{base_uri_path}/"

        # Prepare headers for CalDAV server
        # CalDAV server uses custom auth backend that requires X-Forwarded-User header and API key
        headers = {
            "Content-Type": request.content_type or "application/xml",
            "X-Forwarded-User": user_principal,
            "X-Forwarded-For": request.META.get("REMOTE_ADDR", ""),
            "X-Forwarded-Host": request.get_host(),
            "X-Forwarded-Proto": request.scheme,
        }

        # API key is required for authentication
        outbound_api_key = settings.CALDAV_OUTBOUND_API_KEY
        if not outbound_api_key:
            logger.error("CALDAV_OUTBOUND_API_KEY is not configured")
            return HttpResponse(
                status=500, content="CalDAV authentication not configured"
            )

        headers["X-Api-Key"] = outbound_api_key

        # No Basic Auth - our custom backend uses X-Forwarded-User header and API key
        auth = None

        # Copy relevant headers from the original request
        if "HTTP_DEPTH" in request.META:
            headers["Depth"] = request.META["HTTP_DEPTH"]
        if "HTTP_IF_MATCH" in request.META:
            headers["If-Match"] = request.META["HTTP_IF_MATCH"]
        if "HTTP_IF_NONE_MATCH" in request.META:
            headers["If-None-Match"] = request.META["HTTP_IF_NONE_MATCH"]
        if "HTTP_PREFER" in request.META:
            headers["Prefer"] = request.META["HTTP_PREFER"]

        # Get request body
        body = request.body if request.body else None

        try:
            # Forward the request to CalDAV server
            # CalDAV server authenticates via X-Forwarded-User header and API key
            logger.debug(
                "Forwarding %s request to CalDAV server: %s (user: %s)",
                request.method,
                target_url,
                user_principal,
            )
            response = requests.request(
                method=request.method,
                url=target_url,
                headers=headers,
                data=body,
                auth=auth,
                timeout=30,
                allow_redirects=False,
            )

            # Log authentication failures for debugging
            if response.status_code == 401:
                logger.warning(
                    "CalDAV server returned 401 for user %s at %s. Headers sent: %s",
                    user_principal,
                    target_url,
                    headers,
                )

            # Build Django response
            django_response = HttpResponse(
                content=response.content,
                status=response.status_code,
                content_type=response.headers.get("Content-Type", "application/xml"),
            )

            # Copy relevant headers from CalDAV server response
            for header in ["ETag", "DAV", "Allow", "Location"]:
                if header in response.headers:
                    django_response[header] = response.headers[header]

            return django_response

        except requests.exceptions.RequestException as e:
            logger.error("CalDAV server proxy error: %s", str(e))
            return HttpResponse(
                content=f"CalDAV server error: {str(e)}",
                status=502,
                content_type="text/plain",
            )


@method_decorator(csrf_exempt, name="dispatch")
class CalDAVDiscoveryView(View):
    """
    Handle CalDAV discovery requests (well-known URLs).

    Per RFC 6764, this endpoint should redirect to the CalDAV server base URL,
    not to a user-specific principal. Clients will then perform PROPFIND on
    the base URL to discover their principal.

    CSRF protection is disabled because CalDAV uses non-standard HTTP methods
    and this endpoint should be accessible without authentication.
    """

    def dispatch(self, request, *args, **kwargs):
        """Handle discovery requests."""
        # Handle CORS preflight requests
        if request.method == "OPTIONS":
            response = HttpResponse(status=200)
            response["Access-Control-Allow-Methods"] = "GET, OPTIONS, PROPFIND"
            response["Access-Control-Allow-Headers"] = (
                "Content-Type, depth, authorization"
            )
            return response

        # Note: Authentication is not required for discovery per RFC 6764
        # Clients need to discover the CalDAV URL before authenticating

        # Return redirect to CalDAV server base URL
        caldav_base_url = f"/api/{settings.API_VERSION}/caldav/"
        response = HttpResponse(status=301)
        response["Location"] = caldav_base_url
        return response


@method_decorator(csrf_exempt, name="dispatch")
class CalDAVSchedulingCallbackView(View):
    """
    Endpoint for receiving CalDAV scheduling messages (iMip) from sabre/dav.

    This endpoint receives scheduling messages (invites, responses, cancellations)
    from the CalDAV server and processes them. Authentication is via API key.

    See: https://sabre.io/dav/scheduling/
    """

    def dispatch(self, request, *args, **kwargs):
        """Handle scheduling messages from CalDAV server."""
        # Authenticate via API key
        api_key = request.headers.get("X-Api-Key", "").strip()
        expected_key = settings.CALDAV_INBOUND_API_KEY

        if not expected_key or not secrets.compare_digest(api_key, expected_key):
            logger.warning(
                "CalDAV scheduling callback request with invalid API key. "
                "Expected: %s..., Got: %s...",
                expected_key[:10] if expected_key else "None",
                api_key[:10] if api_key else "None",
            )
            return HttpResponse(status=401)

        # Extract headers
        sender = request.headers.get("X-CalDAV-Sender", "")
        recipient = request.headers.get("X-CalDAV-Recipient", "")
        method = request.headers.get("X-CalDAV-Method", "")

        # For now, just log the scheduling message
        logger.info(
            "Received CalDAV scheduling callback: %s -> %s (method: %s)",
            sender,
            recipient,
            method,
        )

        # Log message body (first 500 chars)
        if request.body:
            body_preview = request.body[:500].decode("utf-8", errors="ignore")
            logger.info("Scheduling message body (first 500 chars): %s", body_preview)

        # TODO: Process the scheduling message (send email, update calendar, etc.)
        # For now, just return success
        return HttpResponse(status=200, content_type="text/plain")
