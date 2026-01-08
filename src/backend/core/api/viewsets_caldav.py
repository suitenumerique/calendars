"""CalDAV proxy views for forwarding requests to DAViCal."""

import logging

from django.conf import settings
from django.http import HttpResponse
from django.utils.decorators import method_decorator
from django.views import View
from django.views.decorators.csrf import csrf_exempt

import requests

from core.services.caldav_service import DAViCalClient

logger = logging.getLogger(__name__)


@method_decorator(csrf_exempt, name="dispatch")
class CalDAVProxyView(View):
    """
    Proxy view that forwards all CalDAV requests to DAViCal.
    Handles authentication and adds appropriate headers.

    CSRF protection is disabled because CalDAV uses non-standard HTTP methods
    (PROPFIND, REPORT, etc.) that don't work with Django's CSRF middleware.
    Authentication is handled via session cookies instead.
    """

    def dispatch(self, request, *args, **kwargs):
        """Forward all HTTP methods to DAViCal."""
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

        # Ensure user exists in DAViCal before making requests
        try:
            davical_client = DAViCalClient()
            davical_client.ensure_user_exists(request.user)
        except Exception as e:
            logger.warning("Failed to ensure user exists in DAViCal: %s", str(e))
            # Continue anyway - user might already exist

        # Build the DAViCal URL
        davical_url = getattr(settings, "DAVICAL_URL", "http://davical:80")
        path = kwargs.get("path", "")

        # Use user email as the principal (DAViCal uses email as username)
        user_principal = request.user.email

        # Handle root CalDAV requests - return principal collection
        if not path or path == user_principal:
            # For PROPFIND on root, return the user's principal collection
            if request.method == "PROPFIND":
                # Get the request path to match the href in response
                request_path = request.path
                if not request_path.endswith("/"):
                    request_path += "/"

                # Return multistatus with href matching request URL and calendar-home-set
                multistatus = f"""<?xml version="1.0" encoding="utf-8"?>
<D:multistatus xmlns:D="DAV:" xmlns:C="urn:ietf:params:xml:ns:caldav">
  <D:response>
    <D:href>{request_path}</D:href>
    <D:propstat>
      <D:prop>
        <D:displayname>{user_principal}</D:displayname>
        <C:calendar-home-set>
          <D:href>/api/v1.0/caldav/{user_principal}/</D:href>
        </C:calendar-home-set>
      </D:prop>
      <D:status>HTTP/1.1 200 OK</D:status>
    </D:propstat>
  </D:response>
</D:multistatus>"""
                response = HttpResponse(
                    content=multistatus,
                    status=207,
                    content_type="application/xml; charset=utf-8",
                )
                return response

            # For other methods, redirect to principal URL
            target_url = f"{davical_url}/caldav.php/{user_principal}/"
        else:
            # Build target URL with path
            # Remove leading slash if present
            clean_path = path.lstrip("/")
            if clean_path.startswith(user_principal):
                # Path already includes principal
                target_url = f"{davical_url}/caldav.php/{clean_path}"
            else:
                # Path is relative to principal
                target_url = f"{davical_url}/caldav.php/{user_principal}/{clean_path}"

        # Prepare headers for DAViCal
        # Set headers to tell DAViCal it's behind a proxy so it generates correct URLs
        script_name = "/api/v1.0/caldav"
        headers = {
            "Content-Type": request.content_type or "application/xml",
            "X-Forwarded-User": user_principal,
            "X-Forwarded-For": request.META.get("REMOTE_ADDR", ""),
            "X-Forwarded-Prefix": script_name,
            "X-Forwarded-Host": request.get_host(),
            "X-Forwarded-Proto": request.scheme,
            "X-Script-Name": script_name,  # Tell DAViCal the base path
        }

        # DAViCal authentication: users with password '*' use external auth
        # We send the username via X-Forwarded-User header
        # For HTTP Basic Auth, we use the email as username with empty password
        # This works with DAViCal's external authentication when trust_x_forwarded is true
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
            # Forward the request to DAViCal
            # Use HTTP Basic Auth with username (email) and empty password
            # DAViCal will authenticate based on X-Forwarded-User header when trust_x_forwarded is true
            logger.debug(
                "Forwarding %s request to DAViCal: %s (user: %s)",
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
                    "DAViCal returned 401 for user %s at %s. Headers sent: %s",
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

            # Copy relevant headers from DAViCal response
            for header in ["ETag", "DAV", "Allow", "Location"]:
                if header in response.headers:
                    django_response[header] = response.headers[header]

            return django_response

        except requests.exceptions.RequestException as e:
            logger.error("DAViCal proxy error: %s", str(e))
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
