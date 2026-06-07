"""Client for the Messages app API.

Discovers mailboxes available to a user and submits raw RFC 5322
messages through those mailboxes via the provisioning and submit
endpoints.

Authentication uses two headers, both required by the Messages app:
- ``X-API-Key: <token>`` — the shared service key
- ``X-Channel-Id: <id>`` — scopes the key to a specific channel
"""

import logging
import re
import time

from django.conf import settings
from django.core.cache import cache

import requests

logger = logging.getLogger(__name__)

MAILBOX_CACHE_TTL = 300  # 5 minutes

# One retry on transient failures (5xx or connection error). Bounded so a
# Messages outage can't snowball into a stuck callback. Backoff is short
# because SabreDAV's iTip callback is synchronous on the user's PUT.
SUBMIT_RETRY_BACKOFF_SECONDS = 0.5
SUBMIT_TIMEOUT_SECONDS = 15

# Cap on the bytes of response body included in log lines — enough to
# read a JSON error, short enough not to flood logs with HTML 5xx pages.
LOG_BODY_EXCERPT = 300

# Header names whose values MUST come from configuration (never from a
# caller). Compared case-insensitively because HTTP headers are
# case-insensitive — a caller dict with ``{"x-api-key": ...}`` would
# otherwise sit alongside our ``X-API-Key`` and most servers honor
# whichever they parse first.
_RESERVED_HEADERS = frozenset({"x-api-key", "x-channel-id"})


class MessagesServiceError(Exception):
    """Raised when a Messages API call fails."""


def _sanitize_header_value(value: str, max_length: int = 998) -> str:
    """Strip bytes that could break an HTTP header line.

    RFC 7230 forbids CR/LF in field values; ``requests`` and ``urllib3``
    enforce this by raising, but a defense-in-depth pass here means we
    don't depend on library version. Non-printable bytes are dropped,
    and the value is truncated to RFC 5322's 998-octet line limit.
    """
    s = str(value or "")
    s = re.sub(r"[^\x20-\x7E]", "", s)
    if len(s) > max_length:
        s = s[:max_length]
    return s


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

        Caller headers whose lowercased name matches a reserved name
        (``x-api-key`` / ``x-channel-id``) are dropped — including
        differently-cased variants — so a caller dict can never sit
        alongside our auth headers. Returns the ``requests.Response``;
        raises on HTTP errors.
        """
        hdrs = {
            k: v
            for k, v in (headers or {}).items()
            if k.lower() not in _RESERVED_HEADERS
        }
        hdrs["X-API-Key"] = self.api_key
        hdrs["X-Channel-Id"] = self.channel_id

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

        Transient ``RequestException`` is logged and swallowed (returns
        ``default``). The caller cannot distinguish transient errors from
        a missing mailbox — see the warning logged here for correlation.
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
            logger.error(
                "Messages API fetch_mailboxes failed (cache_key=%s): %s — "
                "callers will see this as 'mailbox not found'",
                cache_key,
                exc,
            )
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

    def submit_raw_message(  # pylint: disable=too-many-arguments,too-many-positional-arguments
        self,
        mailbox_id,
        rcpt_to,
        mime_bytes,
        *,
        correlation_id="",
    ):
        """Submit pre-built RFC 5322 bytes via the Messages submit endpoint.

        Caller is responsible for building the MIME (Date, Message-ID, MIME
        structure, From/To/Subject headers). This method only handles the
        HTTP boundary: sanitization, authentication, retry, and observability.

        Retries once on connection errors or 5xx responses. The single retry
        is bounded by ``SUBMIT_RETRY_BACKOFF_SECONDS`` because SabreDAV's
        iTip callback is synchronous on the user's PUT — open-ended retry
        would stall the request.

        Logs the response status code and a body excerpt on every outcome
        so a Messages backend that returns 2xx with a rejection payload
        is visible in production logs (previously this was invisible — the
        caller saw success and assumed delivery).

        Returns True if the Messages API accepted the submit (2xx).
        """
        # Sanitize the only attacker-influenceable header we set. The
        # Django callback view validates the email format upstream, but
        # defense-in-depth means we don't depend on that.
        safe_rcpt = _sanitize_header_value(rcpt_to)
        cid = _sanitize_header_value(correlation_id, max_length=120)

        # Refuse to spend a submit on a recipient that sanitized down to
        # nothing — that happens when ``rcpt_to`` was entirely non-printable
        # (e.g. ``"\r\n"``). With an empty ``X-Rcpt-To`` the Messages
        # backend's behavior is unspecified — abort fast rather than
        # gamble on it.
        if not safe_rcpt:
            logger.error(
                "Messages submit aborted: rcpt_to %r sanitized to empty "
                "(mailbox=%s cid=%s)",
                rcpt_to,
                mailbox_id,
                cid,
            )
            return False

        headers = {
            "Content-Type": "message/rfc822",
            "X-Mail-From": _sanitize_header_value(str(mailbox_id)),
            "X-Rcpt-To": safe_rcpt,
        }

        for attempt in (1, 2):
            try:
                resp = self._request(
                    "POST",
                    "/api/v1.0/submit/",
                    data=mime_bytes,
                    headers=headers,
                    timeout=SUBMIT_TIMEOUT_SECONDS,
                )
            except requests.HTTPError as exc:
                status = exc.response.status_code if exc.response is not None else 0
                body_excerpt = (
                    (exc.response.text or "")[:LOG_BODY_EXCERPT]
                    if exc.response is not None
                    else ""
                )
                # Retry once on 5xx; never on 4xx (those are deterministic).
                if status >= 500 and attempt == 1:
                    logger.warning(
                        "Messages submit 5xx (mailbox=%s rcpt=%s cid=%s status=%d "
                        "body=%r) — retrying once",
                        mailbox_id,
                        safe_rcpt,
                        cid,
                        status,
                        body_excerpt,
                    )
                    time.sleep(SUBMIT_RETRY_BACKOFF_SECONDS)
                    continue
                logger.error(
                    "Messages submit failed (mailbox=%s rcpt=%s cid=%s status=%d "
                    "attempt=%d body=%r)",
                    mailbox_id,
                    safe_rcpt,
                    cid,
                    status,
                    attempt,
                    body_excerpt,
                )
                return False
            except requests.RequestException as exc:
                if attempt == 1:
                    logger.warning(
                        "Messages submit connection error (mailbox=%s rcpt=%s "
                        "cid=%s err=%s) — retrying once",
                        mailbox_id,
                        safe_rcpt,
                        cid,
                        exc,
                    )
                    time.sleep(SUBMIT_RETRY_BACKOFF_SECONDS)
                    continue
                logger.error(
                    "Messages submit failed after retry (mailbox=%s rcpt=%s "
                    "cid=%s err=%s)",
                    mailbox_id,
                    safe_rcpt,
                    cid,
                    exc,
                )
                return False

            # 2xx response — log status + body for observability. The
            # Messages backend can return 200/202 with a rejection payload;
            # without this log line, that case was silently invisible.
            body_excerpt = (resp.text or "")[:LOG_BODY_EXCERPT]
            logger.info(
                "Messages submit accepted (mailbox=%s rcpt=%s cid=%s "
                "status=%d attempt=%d body=%r)",
                mailbox_id,
                safe_rcpt,
                cid,
                resp.status_code,
                attempt,
                body_excerpt,
            )
            return True

        return False
