"""Client for the Messages app API.

Discovers mailboxes available to a user and sends emails
through those mailboxes via the provisioning and submit endpoints.

Authentication uses two headers, both required by the Messages app:
- ``X-API-Key: <token>`` — the shared service key
- ``X-Channel-Id: <id>`` — scopes the key to a specific channel
"""

import logging
from email.message import EmailMessage

from django.conf import settings
from django.core.cache import cache

import requests

logger = logging.getLogger(__name__)

MAILBOX_CACHE_TTL = 300  # 5 minutes


class MessagesServiceError(Exception):
    """Raised when a Messages API call fails."""


class MessagesService:
    """HTTP client for the Messages app API."""

    def __init__(self):
        if not settings.MESSAGES_API_URL:
            raise MessagesServiceError("MESSAGES_API_URL is not configured")
        if not settings.MESSAGES_API_KEY:
            raise MessagesServiceError("MESSAGES_API_KEY is not configured")
        if not settings.MESSAGES_CHANNEL_ID:
            raise MessagesServiceError("MESSAGES_CHANNEL_ID is not configured")
        self.base_url = settings.MESSAGES_API_URL.rstrip("/")
        self.api_key = settings.MESSAGES_API_KEY
        self.channel_id = settings.MESSAGES_CHANNEL_ID
        self._org_claim = settings.OIDC_USERINFO_ORGANIZATION_CLAIM

    def _request(  # noqa: PLR0913  # pylint: disable=too-many-arguments,too-many-positional-arguments
        self, method, path, *, params=None, data=None, headers=None, timeout=10
    ):
        """Make an authenticated request to the Messages API.

        Returns the requests.Response object. Raises on HTTP errors.
        """
        hdrs = {
            "X-API-Key": self.api_key,
            "X-Channel-Id": self.channel_id,
        }
        if headers:
            hdrs.update(headers)

        resp = requests.request(
            method,
            f"{self.base_url}{path}",
            params=params,
            data=data,
            headers=hdrs,
            timeout=timeout,
        )
        resp.raise_for_status()
        return resp

    def _get_results(self, path, params, timeout=10):
        """GET a provisioning endpoint and return the ``results`` list."""
        data = self._request("GET", path, params=params, timeout=timeout).json()
        if isinstance(data, dict) and "results" in data:
            return data["results"]
        return data

    def _fetch_mailboxes(self, cache_key, default, **params):
        """Fetch from provisioning/mailboxes/ with caching.

        Cache keys MUST be distinct per query shape — the response includes
        user-specific fields (role) when queried by user_email, but not
        when queried by email. Do not share cache keys across query shapes.
        """
        cached = cache.get(cache_key)
        if cached is not None:
            return cached

        if self._org_claim:
            params["add_maildomain_custom_attributes"] = self._org_claim

        try:
            results = self._get_results("/api/v1.0/provisioning/mailboxes/", params)
            cache.set(cache_key, results, MAILBOX_CACHE_TTL)
            return results
        except requests.RequestException as exc:
            logger.error("Messages API fetch_mailboxes failed: %s", exc)
            return default

    def get_user_mailboxes(self, user_email):
        """Fetch mailboxes the user has access to, with all users of each.

        Each mailbox includes the user's ``role`` and a ``users`` array.
        Cached separately from get_mailbox_by_email (different response shape).
        """
        return self._fetch_mailboxes(
            f"messages:by_user:{user_email}", [], user_email=user_email
        )

    def get_mailbox_by_email(self, mailbox_email):
        """Look up a mailbox by its email address.

        Returns dict with mailbox info or None. No ``role`` field in response.
        Cached separately from get_user_mailboxes (different response shape).
        """
        results = self._fetch_mailboxes(
            f"messages:by_email:{mailbox_email}", [], email=mailbox_email
        )
        return results[0] if results else None

    def submit_raw_email(  # noqa: PLR0913  # pylint: disable=too-many-arguments,too-many-positional-arguments
        self,
        mailbox_id,
        mailbox_email,
        to_email,
        subject,
        text_body,
        html_body,
        ics_attachment=None,
        reply_to=None,
    ):
        """Submit a raw RFC 5322 email via the Messages submit endpoint.

        Composes a MIME message and POSTs it to ``/api/v1.0/submit/``
        with ``Content-Type: message/rfc822``.

        Returns True on success, False on failure.
        """
        mime = _compose_mime(
            from_email=mailbox_email,
            to_email=to_email,
            subject=subject,
            text_body=text_body,
            html_body=html_body,
            ics_attachment=ics_attachment,
            reply_to=reply_to,
        )

        try:
            self._request(
                "POST",
                "/api/v1.0/submit/",
                data=mime.as_bytes(),
                headers={
                    "Content-Type": "message/rfc822",
                    "X-Mail-From": str(mailbox_id),
                    "X-Rcpt-To": to_email,
                },
                timeout=15,
            )
            return True
        except requests.RequestException as exc:
            logger.error(
                "Messages API submit_raw_email failed for mailbox %s: %s",
                mailbox_id,
                exc,
            )
            return False


def _compose_mime(  # noqa: PLR0913  # pylint: disable=too-many-arguments,too-many-positional-arguments
    from_email,
    to_email,
    subject,
    text_body,
    html_body,
    ics_attachment=None,
    reply_to=None,
):
    """Compose an RFC 5322 MIME message with optional ICS attachment."""
    msg = EmailMessage()
    msg["From"] = from_email
    msg["To"] = to_email
    msg["Subject"] = subject
    if reply_to:
        msg["Reply-To"] = reply_to

    msg.set_content(text_body)
    msg.add_alternative(html_body, subtype="html")

    if ics_attachment:
        msg.add_attachment(
            ics_attachment.encode("utf-8"),
            maintype="text",
            subtype="calendar",
            filename="invitation.ics",
        )

    return msg
