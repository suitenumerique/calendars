"""CalDAV proxy views for forwarding requests to CalDAV server."""

import base64
import binascii
import logging
import re
import secrets

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import validate_email
from django.http import HttpResponse
from django.utils import timezone
from django.utils.decorators import method_decorator
from django.views import View
from django.views.decorators.csrf import csrf_exempt

import requests

from core.entitlements import EntitlementsUnavailableError, get_user_entitlements
from core.enums import ChannelScopeLevel
from core.models import Channel, User, urlsafe_to_uuid
from core.services.caldav_service import CalDAVHTTPClient, validate_caldav_proxy_path
from core.services.calendar_invitation_service import calendar_invitation_service

logger = logging.getLogger(__name__)


@method_decorator(csrf_exempt, name="dispatch")
class CalDAVProxyView(View):
    """
    Proxy view that forwards all CalDAV requests to CalDAV server.

    THIS PROXY MUST REMAIN DUMB. It handles:
    - Authentication (OIDC or HTTP Basic Auth → X-LS-User header)
    - Scope-based method enforcement
    - Entitlement checks for calendar creation (MKCALENDAR)

    It MUST NOT implement:
    - Access control (ACL checks belong in SabreDAV)
    - Org scoping (belongs in SabreDAV plugins)
    - Content filtering (belongs in SabreDAV plugins)
    - Protocol-level validation (belongs in SabreDAV)

    All business logic runs in SabreDAV via plugins. The proxy is a
    transparent forwarder with authentication. Keep it that way.

    External services authenticate via HTTP Basic Auth where the
    username is the user's email (enabling standard CalDAV principal
    discovery) and the password is ``channel_id`` immediately followed
    by ``channel_token`` (no separator; the channel_id is a fixed-length
    22-char base64url UUID). This is standard CalDAV auth that works
    with any CalDAV client library.
    """

    # Length of a base64url-encoded UUID (16 bytes) without padding.
    _CHANNEL_ID_LEN = 22

    @staticmethod
    def _authenticate_basic_auth(request):
        """Authenticate via HTTP Basic Auth.

        Basic-auth payload: ``user_email:<channel_id><token>``

        The username is the user's email (enabling standard CalDAV
        principal discovery). The password is the 22-char base64url
        channel id concatenated with the raw token.

        Returns (channel, email) on success, (None, None) on failure.
        """
        auth_header = request.META.get("HTTP_AUTHORIZATION", "")
        if not auth_header.startswith("Basic "):
            return None, None

        try:
            decoded = base64.b64decode(auth_header[6:]).decode("utf-8")
            email, credentials = decoded.split(":", 1)
        except (ValueError, UnicodeDecodeError, binascii.Error):
            return None, None

        channel_id = credentials[: CalDAVProxyView._CHANNEL_ID_LEN]
        token = credentials[CalDAVProxyView._CHANNEL_ID_LEN :]

        if not email or not channel_id or not token:
            return None, None

        try:
            channel_pk = urlsafe_to_uuid(channel_id)
            channel = Channel.objects.select_related("user", "user__organization").get(
                pk=channel_pk, is_active=True, type="caldav"
            )
        except (ValueError, ValidationError, binascii.Error, Channel.DoesNotExist):
            return None, None

        if not channel.verify_token(token):
            return None, None

        Channel.objects.filter(pk=channel.pk).update(last_used_at=timezone.now())
        return channel, email

    @staticmethod
    def _resolve_channel_user(channel, email):
        """Resolve the acting user from channel scope + Basic Auth email.

        For global channels, the email from Basic Auth determines the
        acting user. For user/calendar channels, the email must match
        the channel's bound user.

        Returns (user, error_response) — exactly one is None.
        """
        if channel.scope_level == ChannelScopeLevel.GLOBAL:
            try:
                user = User.objects.select_related("organization").get(
                    email__iexact=email
                )
            except User.DoesNotExist:
                return None, HttpResponse(status=403, content="Unknown user")
            return user, None

        if not channel.user:
            return None, HttpResponse(status=500, content="Channel has no user")
        if channel.user.email.lower() != email.lower():
            return None, HttpResponse(
                status=403, content="Email does not match channel user"
            )
        return channel.user, None

    @staticmethod
    def _check_channel_path_access(channel, path):
        """Check that the CalDAV path is within the channel's scope.

        Returns True if allowed, False if denied.

        CalDAV clients (Thunderbird, Apple Calendar, etc.) bootstrap by
        PROPFIND-ing the server root and the user's principal URL to
        discover the calendar-home-set. So in addition to the channel's
        own scope, every authenticated channel may PROPFIND its own
        principal and the root. This exposes no data the channel could
        not have reached anyway via its calendar home.
        """
        full_path = "/" + path.lstrip("/") if path else "/"

        if channel.scope_level == ChannelScopeLevel.GLOBAL:
            return True

        # User/calendar scope: must have a bound user.
        if not channel.user:
            return False

        # Discovery: root + the channel-user's own principal are
        # always reachable. The method-scope check (PROPFIND/OPTIONS
        # only for read scopes) already prevents writes here.
        principal_prefix = f"/principals/users/{channel.user.email}/"
        if full_path == "/" or full_path.startswith(principal_prefix):
            return True

        if channel.scope_level == ChannelScopeLevel.CALENDAR:
            cal_path = channel.caldav_path
            if cal_path and not cal_path.endswith("/"):
                logger.error("caldav_path %r missing trailing slash", cal_path)
                cal_path = None
            return bool(cal_path) and full_path.startswith(cal_path)

        user_prefix = f"/calendars/users/{channel.user.email}/"
        return full_path.startswith(user_prefix)

    @staticmethod
    def _is_collection_path(path):
        """Return True if the path targets a CalDAV collection (calendar)
        rather than an object (event).

        CalDAV collections always end with ``/`` (RFC 4918, enforced by
        SabreDAV). Objects end with ``.ics``. Unknown paths default to
        collection (fail-safe: more restrictive).
        """
        if path and path.endswith("/"):
            return True
        if path and path.endswith(".ics"):
            return False
        return True

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
        if request.method == "OPTIONS":
            response = HttpResponse(status=200)
            response["Access-Control-Allow-Methods"] = (
                "GET, OPTIONS, PROPFIND, PROPPATCH, REPORT,"
                " MKCOL, MKCALENDAR, PUT, DELETE, POST"
            )
            response["Access-Control-Allow-Headers"] = (
                "Content-Type, depth, authorization, if-match, if-none-match, prefer"
            )
            return response

        channel = None
        effective_user = None
        path = kwargs.get("path", "")

        if not request.user.is_authenticated:
            channel, email = self._authenticate_basic_auth(request)
            if not channel:
                resp = HttpResponse(status=401)
                resp["WWW-Authenticate"] = 'Basic realm="CalDAV"'
                return resp
            effective_user, err = self._resolve_channel_user(channel, email)
            if err:
                return err
        else:
            effective_user = request.user

        if channel:
            is_collection = self._is_collection_path(path)
            allowed = channel.allowed_methods(collection=is_collection)
            if request.method not in allowed:
                return HttpResponse(
                    status=403,
                    content="Method not allowed for channel scopes",
                )

        if request.method in ("MKCALENDAR", "MKCOL"):
            if denied := self._check_entitlements_for_creation(effective_user):
                return denied

        if not validate_caldav_proxy_path(path):
            return HttpResponse(status=400, content="Invalid path")

        if channel and not self._check_channel_path_access(channel, path):
            return HttpResponse(status=403, content="Path not allowed for this channel")

        http = CalDAVHTTPClient()

        clean_path = path.lstrip("/") if path else ""
        target_url = http.build_url(clean_path)

        try:
            headers = CalDAVHTTPClient.build_base_headers(effective_user)
        except ValueError:
            logger.error("CALDAV_OUTBOUND_API_KEY is not configured")
            return HttpResponse(
                status=500, content="CalDAV authentication not configured"
            )

        if channel:
            headers["X-LS-Channel-Id"] = str(channel.pk)

        headers["Content-Type"] = request.content_type or "application/xml"

        if "HTTP_DEPTH" in request.META:
            headers["Depth"] = request.META["HTTP_DEPTH"]
        if "HTTP_IF_MATCH" in request.META:
            headers["If-Match"] = request.META["HTTP_IF_MATCH"]
        if "HTTP_IF_NONE_MATCH" in request.META:
            headers["If-None-Match"] = request.META["HTTP_IF_NONE_MATCH"]
        if "HTTP_PREFER" in request.META:
            headers["Prefer"] = request.META["HTTP_PREFER"]

        body = request.body if request.body else None

        try:
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
                timeout=CalDAVHTTPClient.DEFAULT_TIMEOUT,
                allow_redirects=False,
            )

            if response.status_code == 401:
                logger.warning(
                    "CalDAV server returned 401 for user %s at %s",
                    effective_user.email,
                    target_url,
                )
            if request.method == "PROPFIND":
                logger.debug(
                    "CalDAV PROPFIND %s -> %s (status=%s, body_len=%d,"
                    " content_type=%s)",
                    target_url,
                    effective_user.email,
                    response.status_code,
                    len(response.content),
                    response.headers.get("Content-Type", "?"),
                )

            django_response = HttpResponse(
                content=response.content,
                status=response.status_code,
                content_type=response.headers.get("Content-Type", "application/xml"),
            )

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
        api_key = request.headers.get("X-LS-Api-Key", "").strip()
        expected_key = settings.CALDAV_INBOUND_API_KEY

        if not expected_key or not secrets.compare_digest(api_key, expected_key):
            logger.warning("CalDAV scheduling callback request with invalid API key.")
            return HttpResponse(status=401)

        # Extract and validate sender/recipient emails
        sender = re.sub(
            r"(?i)^mailto:", "", request.headers.get("X-LS-Sender", "")
        ).strip()
        recipient = re.sub(
            r"(?i)^mailto:", "", request.headers.get("X-LS-Recipient", "")
        ).strip()
        method = request.headers.get("X-LS-Method", "").upper()

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
                content="Missing required headers: X-LS-Sender, "
                "X-LS-Recipient, X-LS-Method",
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

        # SabreDAV's HttpCallbackIMipPlugin checks the sender's principal type
        # and passes it via header — no need for an extra API call here.
        # Security: this endpoint is gated by X-LS-Api-Key (CALDAV_INBOUND_API_KEY),
        # so the header cannot be spoofed by external callers.
        is_mailbox = request.headers.get("X-LS-Is-Mailbox") == "true"
        org_id = request.headers.get("X-LS-Org-Id", "")
        via = "messages" if is_mailbox else "smtp"

        logger.info(
            "Processing CalDAV scheduling %s: %s -> %s (via %s)",
            method,
            sender,
            recipient,
            via,
        )

        # Send the invitation/notification email
        try:
            success = calendar_invitation_service.send_invitation(
                sender_email=sender,
                recipient_email=recipient,
                method=method,
                icalendar_data=icalendar_data,
                is_mailbox=is_mailbox,
                org_id=org_id,
            )

            if success:
                logger.info(
                    "Sent calendar %s: %s -> %s (via %s)",
                    method,
                    sender,
                    recipient,
                    via,
                )
                return HttpResponse(
                    status=200,
                    content="OK",
                    content_type="text/plain",
                )

            logger.error(
                "Failed to send calendar %s: %s -> %s (via %s)",
                method,
                sender,
                recipient,
                via,
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
