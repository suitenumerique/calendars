"""URL validation for external calendar subscriptions.

Validates subscription URLs against SSRF attacks and ensures they point
to valid, reachable ICS resources.
"""

import ipaddress
import logging
import socket
from urllib.parse import urljoin, urlparse, urlunparse

import requests

logger = logging.getLogger(__name__)

USER_AGENT = "La-Suite-Calendars/1.0"
MAX_RESPONSE_SIZE = 10 * 1024 * 1024  # 10 MB
CONNECT_TIMEOUT = 10  # seconds
READ_TIMEOUT = 30  # seconds
MAX_REDIRECTS = 3


class URLValidationError(Exception):
    """Raised when a subscription URL fails validation."""


def _redact_url(url: str) -> str:
    """Strip query string and fragment to avoid leaking signed tokens.

    Subscription URLs can embed HMAC or bearer tokens in the query
    string (e.g. Google Calendar private ICS URLs). Those tokens end up
    in ``channel.settings['last_sync_error']`` and from there into the
    API response / frontend, so we strip them from any string that
    might be logged or raised.
    """
    try:
        parsed = urlparse(url)
        return urlunparse((parsed.scheme, parsed.netloc, parsed.path, "", "", ""))
    except Exception:  # noqa: BLE001  # pylint: disable=broad-exception-caught
        return "[unparseable url]"


def _is_private_ip(ip_str: str) -> bool:
    """Check if an IP address is private, loopback, or link-local."""
    try:
        addr = ipaddress.ip_address(ip_str)
    except ValueError:
        return True  # fail-closed on unparseable addresses
    # Unwrap IPv4-mapped IPv6 addresses (e.g. ::ffff:127.0.0.1)
    # before classification, since Python's IPv6Address.is_private
    # returns False for these.
    if isinstance(addr, ipaddress.IPv6Address) and addr.ipv4_mapped:
        addr = addr.ipv4_mapped
    return (
        addr.is_private
        or addr.is_loopback
        or addr.is_link_local
        or addr.is_reserved
        or addr.is_multicast
    )


def _resolve_and_check(hostname: str) -> str:
    """Resolve hostname and verify it doesn't point to a private IP.

    Returns the resolved IP address string.
    Raises URLValidationError if the IP is private.
    """
    try:
        results = socket.getaddrinfo(
            hostname, None, socket.AF_UNSPEC, socket.SOCK_STREAM
        )
    except socket.gaierror as exc:
        raise URLValidationError(f"Cannot resolve hostname: {hostname}") from exc

    if not results:
        raise URLValidationError(f"Cannot resolve hostname: {hostname}")

    # Check ALL resolved IPs — reject if any is private
    for _family, _type, _proto, _canonname, sockaddr in results:
        ip_str = sockaddr[0]
        if _is_private_ip(ip_str):
            raise URLValidationError("URL resolves to a private network address")

    return results[0][4][0]


def normalize_url(url: str) -> str:
    """Normalize a subscription URL (e.g. webcal:// to https://)."""
    url = url.strip()
    if url.lower().startswith("webcal://"):
        url = "https://" + url[len("webcal://") :]
    return url


def validate_subscription_url(url: str) -> str:
    """Validate and normalize a subscription URL.

    Checks:
    - URL is well-formed
    - Scheme is HTTPS
    - Hostname doesn't resolve to a private IP

    Returns the normalized URL.
    Raises URLValidationError on failure.
    """
    url = normalize_url(url)

    parsed = urlparse(url)
    if parsed.scheme != "https":
        raise URLValidationError("Only HTTPS URLs are allowed")

    if not parsed.hostname:
        raise URLValidationError("Invalid URL: no hostname")

    _resolve_and_check(parsed.hostname)

    return url


def _safe_get(url, headers):
    """Make a GET request with SSRF-safe redirect handling.

    Responses are streamed; intermediate redirect responses are closed
    as soon as the next request fires. Callers are responsible for
    closing the final returned response.
    """
    try:
        response = requests.get(
            url,
            headers=headers,
            timeout=(CONNECT_TIMEOUT, READ_TIMEOUT),
            stream=True,
            allow_redirects=False,
        )
    except requests.exceptions.Timeout as exc:
        raise URLValidationError("Request timed out") from exc
    except requests.exceptions.RequestException as exc:
        raise URLValidationError(f"Failed to fetch URL: {_redact_url(url)}") from exc

    # Handle redirects manually to check each hop for SSRF
    current_url = url
    redirect_count = 0
    # Strip conditional headers for redirect targets to avoid false 304s
    redirect_headers = {
        k: v
        for k, v in headers.items()
        if k not in ("If-None-Match", "If-Modified-Since")
    }
    try:
        while response.status_code in (301, 302, 303, 307, 308):
            redirect_count += 1
            if redirect_count > MAX_REDIRECTS:
                raise URLValidationError(f"Too many redirects (max {MAX_REDIRECTS})")

            location = response.headers.get("Location", "")
            if not location:
                raise URLValidationError("Redirect without Location header")

            # Resolve relative redirects against the current URL
            location = urljoin(current_url, location)
            redirect_parsed = urlparse(location)

            if redirect_parsed.scheme != "https":
                raise URLValidationError("Redirect to non-HTTPS URL")
            if not redirect_parsed.hostname:
                raise URLValidationError("Redirect to URL without hostname")
            _resolve_and_check(redirect_parsed.hostname)

            current_url = location
            # Release the previous streamed response before issuing the
            # next hop so we don't leak connections on long redirect
            # chains.
            response.close()
            try:
                response = requests.get(
                    location,
                    headers=redirect_headers,
                    timeout=(CONNECT_TIMEOUT, READ_TIMEOUT),
                    stream=True,
                    allow_redirects=False,
                )
            except requests.exceptions.Timeout as exc:
                raise URLValidationError("Request timed out during redirect") from exc
            except requests.exceptions.RequestException as exc:
                raise URLValidationError(
                    f"Failed during redirect: {_redact_url(location)}"
                ) from exc
    except BaseException:
        response.close()
        raise

    return response


def _read_response_body(response, url):
    """Read response body with size limit and ICS validation."""
    content_type = response.headers.get("Content-Type", "")
    if (
        "text/calendar" not in content_type
        and "application/octet-stream" not in content_type
    ):
        logger.warning(
            "Unexpected Content-Type %r for %s", content_type, _redact_url(url)
        )

    chunks = []
    total_size = 0
    try:
        for chunk in response.iter_content(chunk_size=8192):
            total_size += len(chunk)
            if total_size > MAX_RESPONSE_SIZE:
                raise URLValidationError(
                    f"Response too large (max {MAX_RESPONSE_SIZE // (1024 * 1024)} MB)"
                )
            chunks.append(chunk)
    except requests.exceptions.RequestException as exc:
        raise URLValidationError(
            f"Failed to read response body: {_redact_url(url)}"
        ) from exc

    ics_data = b"".join(chunks)
    if not ics_data or b"BEGIN:VCALENDAR" not in ics_data:
        raise URLValidationError("URL does not return valid calendar data")

    return ics_data


def fetch_ics(url: str, etag: str = "", last_modified: str = "") -> tuple:
    """Fetch an ICS resource with conditional request support.

    Returns (status_code, ics_data_or_None, new_etag, new_last_modified).
    Raises URLValidationError on network errors, invalid content, or SSRF.
    """
    url = normalize_url(url)
    parsed = urlparse(url)

    if parsed.scheme != "https":
        raise URLValidationError("Only HTTPS URLs are allowed")

    # Re-validate IP at fetch time (best-effort DNS rebinding mitigation).
    # Note: there is still a TOCTOU window between this check and the
    # actual TCP connection made by requests. A complete fix would require
    # a custom requests adapter that pins to the pre-resolved IP.
    # Network-level controls (e.g. firewall blocking egress to private
    # ranges) provide a stronger second layer of defence.
    if parsed.hostname:
        _resolve_and_check(parsed.hostname)

    headers = {"User-Agent": USER_AGENT}
    if etag:
        headers["If-None-Match"] = etag
    if last_modified:
        headers["If-Modified-Since"] = last_modified

    response = _safe_get(url, headers)
    try:
        if response.status_code == 304:
            return 304, None, etag, last_modified

        if response.status_code != 200:
            raise URLValidationError(f"Server returned HTTP {response.status_code}")

        ics_data = _read_response_body(response, url)
        new_etag = response.headers.get("ETag", "")
        new_last_modified = response.headers.get("Last-Modified", "")
        return 200, ics_data, new_etag, new_last_modified
    finally:
        response.close()
