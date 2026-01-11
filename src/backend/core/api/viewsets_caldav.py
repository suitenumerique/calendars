"""CalDAV proxy views for forwarding requests to CalDAV server."""

import logging

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
        # CalDAV server Apache backend reads REMOTE_USER, which we set via X-Forwarded-User
        headers = {
            "Content-Type": request.content_type or "application/xml",
            "X-Forwarded-User": user_principal,
            "X-Forwarded-For": request.META.get("REMOTE_ADDR", ""),
            "X-Forwarded-Host": request.get_host(),
            "X-Forwarded-Proto": request.scheme,
        }

        # CalDAV server authentication: Apache backend reads REMOTE_USER
        # We send the username via X-Forwarded-User header
        # For HTTP Basic Auth, we use the email as username with empty password
        # CalDAV server converts X-Forwarded-User to REMOTE_USER
        auth = (user_principal, "")

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
            # Use HTTP Basic Auth with username (email) and empty password
            # CalDAV server will authenticate based on X-Forwarded-User header (converted to REMOTE_USER)
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
        caldav_base_url = f"/api/v1.0/caldav/"
        response = HttpResponse(status=301)
        response["Location"] = caldav_base_url
        return response
