"""CalDAV proxy views for forwarding requests to CalDAV server."""

import logging
import re
import secrets

from django.conf import settings
from django.core.validators import validate_email
from django.http import HttpResponse
from django.urls import reverse
from django.utils import timezone
from django.utils.decorators import method_decorator
from django.views import View
from django.views.decorators.csrf import csrf_exempt

import requests

from core.entitlements import EntitlementsUnavailableError, get_user_entitlements
from core.models import Channel
from core.services.caldav_service import CalDAVHTTPClient, validate_caldav_proxy_path
from core.services.calendar_invitation_service import calendar_invitation_service

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

    # HTTP methods allowed per Channel role
    READER_METHODS = frozenset({"GET", "PROPFIND", "REPORT", "OPTIONS"})
    EDITOR_METHODS = READER_METHODS | frozenset({"PUT", "POST", "DELETE", "PROPPATCH"})
    ADMIN_METHODS = EDITOR_METHODS | frozenset({"MKCALENDAR", "MKCOL"})

    ROLE_METHODS = {
        Channel.ROLE_READER: READER_METHODS,
        Channel.ROLE_EDITOR: EDITOR_METHODS,
        Channel.ROLE_ADMIN: ADMIN_METHODS,
    }

    @staticmethod
    def _authenticate_channel_token(request):
        """Try to authenticate via X-Channel-Id + X-Channel-Token headers.

        Returns (channel, user) on success, (None, None) on failure.
        """
        channel_id = request.headers.get("X-Channel-Id", "").strip()
        token = request.headers.get("X-Channel-Token", "").strip()
        if not channel_id or not token:
            return None, None

        try:
            channel = Channel.objects.get(pk=channel_id, is_active=True, type="caldav")
        except (ValueError, Channel.DoesNotExist):
            return None, None

        if not channel.verify_token(token):
            return None, None

        user = channel.user
        if not user:
            logger.warning("Channel %s has no user", channel.id)
            return None, None

        # Update last_used_at (fire-and-forget, no extra query on critical path)
        Channel.objects.filter(pk=channel.pk).update(last_used_at=timezone.now())

        return channel, user

    @staticmethod
    def _check_channel_path_access(channel, path):
        """Check that the CalDAV path is within the channel's scope.

        Returns True if allowed, False if denied.
        """
        # Ensure path starts with /
        full_path = "/" + path.lstrip("/") if path else "/"

        # caldav_path scope: request must be within the scoped calendar
        # The trailing slash on caldav_path (enforced by serializer) ensures
        # /cal1/ won't match /cal1-secret/
        if channel.caldav_path:
            if not channel.caldav_path.endswith("/"):
                logger.error(
                    "caldav_path %r missing trailing slash", channel.caldav_path
                )
                return False
            return full_path.startswith(channel.caldav_path)

        # user scope: request must be under the user's calendars
        if channel.user:
            user_prefix = f"/calendars/users/{channel.user.email}/"
            return full_path.startswith(user_prefix)

        return False

    @staticmethod
    def _check_entitlements_for_creation(user):
        """Check if user is entitled to create calendars.

        Returns None if allowed, or an HttpResponse(403) if denied.
        Fail-closed: denies if the entitlements service is unavailable.
        """
        try:
            entitlements = get_user_entitlements(user.sub, user.email)
            if not entitlements.get("can_access", False):
                return HttpResponse(
                    status=403,
                    content="Calendar creation not allowed",
                )
        except EntitlementsUnavailableError:
            return HttpResponse(
                status=403,
                content="Calendar creation not allowed",
            )
        return None

    def dispatch(self, request, *args, **kwargs):  # noqa: PLR0912, PLR0911, PLR0915  # pylint: disable=too-many-branches,too-many-return-statements,too-many-statements,too-many-locals
        """Forward all HTTP methods to CalDAV server."""
        # Handle CORS preflight requests
        if request.method == "OPTIONS":
            response = HttpResponse(status=200)
            response["Access-Control-Allow-Methods"] = (
                "GET, OPTIONS, PROPFIND, PROPPATCH, REPORT,"
                " MKCOL, MKCALENDAR, PUT, DELETE, POST"
            )
            response["Access-Control-Allow-Headers"] = (
                "Content-Type, depth, x-channel-id, x-channel-token,"
                " if-match, if-none-match, prefer"
            )
            return response

        # Try channel token auth first (for external services like Messages)
        channel = None
        effective_user = None
        if not request.user.is_authenticated:
            channel, effective_user = self._authenticate_channel_token(request)
            if not channel:
                return HttpResponse(status=401)
        else:
            effective_user = request.user

        if channel:
            # Enforce role-based method restrictions
            allowed = self.ROLE_METHODS.get(channel.role, self.READER_METHODS)
            if request.method not in allowed:
                return HttpResponse(
                    status=403, content="Method not allowed for this role"
                )

        # Check entitlements for calendar creation (all auth methods)
        if request.method in ("MKCALENDAR", "MKCOL"):
            if denied := self._check_entitlements_for_creation(effective_user):
                return denied

        # Build the CalDAV server URL
        path = kwargs.get("path", "")

        # Validate path to prevent traversal attacks
        if not validate_caldav_proxy_path(path):
            return HttpResponse(status=400, content="Invalid path")

        # Enforce channel path scope
        if channel and not self._check_channel_path_access(channel, path):
            return HttpResponse(status=403, content="Path not allowed for this channel")

        http = CalDAVHTTPClient()

        # Build target URL
        clean_path = path.lstrip("/") if path else ""
        if clean_path:
            target_url = http.build_url(clean_path)
        else:
            target_url = http.build_url("")

        # Prepare headers — start with shared auth headers, add proxy-specific ones
        try:
            headers = CalDAVHTTPClient.build_base_headers(effective_user)
        except ValueError:
            logger.error("CALDAV_OUTBOUND_API_KEY is not configured")
            return HttpResponse(
                status=500, content="CalDAV authentication not configured"
            )

        headers["Content-Type"] = request.content_type or "application/xml"
        headers["X-Forwarded-For"] = request.META.get("REMOTE_ADDR", "")
        headers["X-Forwarded-Host"] = request.get_host()
        headers["X-Forwarded-Proto"] = request.scheme

        # Add callback URL for CalDAV scheduling (iTip/iMip)
        # The CalDAV server will call this URL when it needs to send invitations
        # Use CALDAV_CALLBACK_BASE_URL if configured (for Docker environments where
        # the CalDAV container needs to reach Django via internal network)
        callback_path = reverse("caldav-scheduling-callback")
        callback_base_url = settings.CALDAV_CALLBACK_BASE_URL
        if callback_base_url:
            # Use configured internal URL (e.g., http://backend:8000)
            headers["X-CalDAV-Callback-URL"] = (
                f"{callback_base_url.rstrip('/')}{callback_path}"
            )
        else:
            # Fall back to external URL (works when CalDAV can reach Django externally)
            headers["X-CalDAV-Callback-URL"] = request.build_absolute_uri(callback_path)

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
                effective_user.email,
            )
            response = requests.request(
                method=request.method,
                url=target_url,
                headers=headers,
                data=body,
                auth=auth,
                timeout=CalDAVHTTPClient.DEFAULT_TIMEOUT,
                allow_redirects=False,
            )

            # Log authentication failures for debugging (without sensitive headers)
            if response.status_code == 401:
                logger.warning(
                    "CalDAV server returned 401 for user %s at %s",
                    effective_user.email,
                    target_url,
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
                content="CalDAV server is unavailable",
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
        response = HttpResponse(status=301)
        response["Location"] = "/caldav/"
        return response


@method_decorator(csrf_exempt, name="dispatch")
class CalDAVSchedulingCallbackView(View):
    """
    Endpoint for receiving CalDAV scheduling messages (iMip) from sabre/dav.

    This endpoint receives scheduling messages (invites, responses, cancellations)
    from the CalDAV server and processes them by sending email notifications
    with ICS attachments. Authentication is via API key.

    Supported iTip methods (RFC 5546):
    - REQUEST: New invitation or event update
    - CANCEL: Event cancellation
    - REPLY: Attendee response (accept/decline/tentative)

    See: https://sabre.io/dav/scheduling/
    """

    http_method_names = ["post"]

    def post(self, request, *args, **kwargs):  # noqa: PLR0911  # pylint: disable=too-many-return-statements
        """Handle scheduling messages from CalDAV server."""
        # Authenticate via API key
        api_key = request.headers.get("X-Api-Key", "").strip()
        expected_key = settings.CALDAV_INBOUND_API_KEY

        if not expected_key or not secrets.compare_digest(api_key, expected_key):
            logger.warning("CalDAV scheduling callback request with invalid API key.")
            return HttpResponse(status=401)

        # Extract and validate sender/recipient emails
        sender = re.sub(
            r"^mailto:", "", request.headers.get("X-CalDAV-Sender", "")
        ).strip()
        recipient = re.sub(
            r"^mailto:", "", request.headers.get("X-CalDAV-Recipient", "")
        ).strip()
        method = request.headers.get("X-CalDAV-Method", "").upper()

        # Validate required fields
        if not sender or not recipient or not method:
            logger.error(
                "CalDAV scheduling callback missing required headers: "
                "sender=%s, recipient=%s, method=%s",
                sender,
                recipient,
                method,
            )
            return HttpResponse(
                status=400,
                content="Missing required headers: X-CalDAV-Sender, "
                "X-CalDAV-Recipient, X-CalDAV-Method",
                content_type="text/plain",
            )

        # Validate email format
        try:
            validate_email(sender)
            validate_email(recipient)
        except Exception:  # noqa: BLE001  # pylint: disable=broad-exception-caught
            logger.warning(
                "CalDAV scheduling callback with invalid email: sender=%s, recipient=%s",
                sender,
                recipient,
            )
            return HttpResponse(
                status=400,
                content="Invalid sender or recipient email",
                content_type="text/plain",
            )

        # Get iCalendar data from request body
        icalendar_data = (
            request.body.decode("utf-8", errors="replace") if request.body else ""
        )
        if not icalendar_data:
            logger.error("CalDAV scheduling callback received empty body")
            return HttpResponse(
                status=400,
                content="Missing iCalendar data in request body",
                content_type="text/plain",
            )

        logger.info(
            "Processing CalDAV scheduling message: %s -> %s (method: %s)",
            sender,
            recipient,
            method,
        )

        # Send the invitation/notification email
        try:
            success = calendar_invitation_service.send_invitation(
                sender_email=sender,
                recipient_email=recipient,
                method=method,
                icalendar_data=icalendar_data,
            )

            if success:
                logger.info(
                    "Successfully sent calendar %s email: %s -> %s",
                    method,
                    sender,
                    recipient,
                )
                return HttpResponse(
                    status=200,
                    content="OK",
                    content_type="text/plain",
                )

            logger.error(
                "Failed to send calendar %s email: %s -> %s",
                method,
                sender,
                recipient,
            )
            return HttpResponse(
                status=500,
                content="Failed to send email",
                content_type="text/plain",
            )

        except Exception as e:  # pylint: disable=broad-exception-caught
            logger.exception("Error processing CalDAV scheduling callback: %s", e)
            return HttpResponse(
                status=500,
                content="Internal server error",
                content_type="text/plain",
            )
