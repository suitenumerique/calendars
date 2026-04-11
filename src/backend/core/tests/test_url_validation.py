"""Tests for URL validation service."""

# pylint: disable=missing-class-docstring,missing-function-docstring

import socket
from unittest.mock import MagicMock, patch

import pytest
import requests

from core.services.url_validation import (
    URLValidationError,
    fetch_ics,
    normalize_url,
    validate_subscription_url,
)

VALID_ICS = b"BEGIN:VCALENDAR\r\nVERSION:2.0\r\nEND:VCALENDAR"


class TestNormalizeUrl:
    def test_webcal_to_https(self):
        assert (
            normalize_url("webcal://example.com/cal.ics")
            == "https://example.com/cal.ics"
        )

    def test_webcal_case_insensitive(self):
        assert (
            normalize_url("WEBCAL://example.com/cal.ics")
            == "https://example.com/cal.ics"
        )

    def test_https_unchanged(self):
        assert (
            normalize_url("https://example.com/cal.ics")
            == "https://example.com/cal.ics"
        )

    def test_strips_whitespace(self):
        assert (
            normalize_url("  https://example.com/cal.ics  ")
            == "https://example.com/cal.ics"
        )


class TestValidateSubscriptionUrl:
    @patch("core.services.url_validation._resolve_and_check")
    def test_valid_https_url(self, mock_resolve):
        mock_resolve.return_value = "93.184.216.34"
        result = validate_subscription_url("https://example.com/cal.ics")
        assert result == "https://example.com/cal.ics"

    def test_rejects_http(self):
        with pytest.raises(URLValidationError, match="Only HTTPS URLs are allowed"):
            validate_subscription_url("http://example.com/cal.ics")

    @patch("core.services.url_validation._resolve_and_check")
    def test_normalizes_webcal(self, mock_resolve):
        mock_resolve.return_value = "93.184.216.34"
        result = validate_subscription_url("webcal://example.com/cal.ics")
        assert result == "https://example.com/cal.ics"

    def test_rejects_empty_hostname(self):
        with pytest.raises(URLValidationError):
            validate_subscription_url("https:///no-host")

    @patch(
        "core.services.url_validation._resolve_and_check",
        side_effect=URLValidationError("URL resolves to a private network address"),
    )
    def test_rejects_private_ip(self, _mock):
        with pytest.raises(URLValidationError, match="private network"):
            validate_subscription_url("https://internal.local/cal.ics")


class TestResolveAndCheck:
    @patch("core.services.url_validation.socket.getaddrinfo")
    def test_rejects_loopback(self, mock_getaddrinfo):
        mock_getaddrinfo.return_value = [
            (2, 1, 6, "", ("127.0.0.1", 0)),
        ]
        with pytest.raises(URLValidationError, match="private network"):
            validate_subscription_url("https://localhost/cal.ics")

    @patch("core.services.url_validation.socket.getaddrinfo")
    def test_rejects_10_network(self, mock_getaddrinfo):
        mock_getaddrinfo.return_value = [
            (2, 1, 6, "", ("10.0.0.1", 0)),
        ]
        with pytest.raises(URLValidationError, match="private network"):
            validate_subscription_url("https://internal.example.com/cal.ics")

    @patch("core.services.url_validation.socket.getaddrinfo")
    def test_rejects_172_16_network(self, mock_getaddrinfo):
        mock_getaddrinfo.return_value = [
            (2, 1, 6, "", ("172.16.0.1", 0)),
        ]
        with pytest.raises(URLValidationError, match="private network"):
            validate_subscription_url("https://internal.example.com/cal.ics")

    @patch("core.services.url_validation.socket.getaddrinfo")
    def test_rejects_192_168_network(self, mock_getaddrinfo):
        mock_getaddrinfo.return_value = [
            (2, 1, 6, "", ("192.168.1.1", 0)),
        ]
        with pytest.raises(URLValidationError, match="private network"):
            validate_subscription_url("https://router.local/cal.ics")

    @patch("core.services.url_validation.socket.getaddrinfo")
    def test_rejects_link_local(self, mock_getaddrinfo):
        mock_getaddrinfo.return_value = [
            (2, 1, 6, "", ("169.254.1.1", 0)),
        ]
        with pytest.raises(URLValidationError, match="private network"):
            validate_subscription_url("https://metadata.local/cal.ics")

    @patch("core.services.url_validation.socket.getaddrinfo")
    def test_rejects_ipv6_loopback(self, mock_getaddrinfo):
        mock_getaddrinfo.return_value = [
            (10, 1, 6, "", ("::1", 0, 0, 0)),
        ]
        with pytest.raises(URLValidationError, match="private network"):
            validate_subscription_url("https://ipv6-local.example.com/cal.ics")

    @patch("core.services.url_validation.socket.getaddrinfo")
    def test_accepts_public_ip(self, mock_getaddrinfo):
        mock_getaddrinfo.return_value = [
            (2, 1, 6, "", ("93.184.216.34", 0)),
        ]
        result = validate_subscription_url("https://example.com/cal.ics")
        assert result == "https://example.com/cal.ics"

    @patch(
        "core.services.url_validation.socket.getaddrinfo",
        side_effect=socket.gaierror("Name resolution failed"),
    )
    def test_rejects_unresolvable(self, _mock):
        with pytest.raises(URLValidationError, match="Cannot resolve"):
            validate_subscription_url("https://nonexistent.invalid/cal.ics")


class TestFetchIcs:
    @patch("core.services.url_validation._resolve_and_check")
    @patch("core.services.url_validation.requests.get")
    def test_200_returns_ics_data(self, mock_get, mock_resolve):
        mock_resolve.return_value = "93.184.216.34"
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.headers = {
            "Content-Type": "text/calendar",
            "ETag": '"abc123"',
            "Last-Modified": "Wed, 01 Jan 2026 00:00:00 GMT",
        }
        mock_response.iter_content.return_value = [VALID_ICS]
        mock_get.return_value = mock_response

        status_code, data, etag, last_mod = fetch_ics("https://example.com/cal.ics")
        assert status_code == 200
        assert data == VALID_ICS
        assert etag == '"abc123"'
        assert last_mod == "Wed, 01 Jan 2026 00:00:00 GMT"

    @patch("core.services.url_validation._resolve_and_check")
    @patch("core.services.url_validation.requests.get")
    def test_304_returns_none_data(self, mock_get, mock_resolve):
        mock_resolve.return_value = "93.184.216.34"
        mock_response = MagicMock()
        mock_response.status_code = 304
        mock_get.return_value = mock_response

        status_code, data, etag, _last_mod = fetch_ics(
            "https://example.com/cal.ics", etag='"old"', last_modified="old-date"
        )
        assert status_code == 304
        assert data is None
        assert etag == '"old"'

    @patch("core.services.url_validation._resolve_and_check")
    @patch("core.services.url_validation.requests.get")
    def test_sends_conditional_headers(self, mock_get, mock_resolve):
        mock_resolve.return_value = "93.184.216.34"
        mock_response = MagicMock()
        mock_response.status_code = 304
        mock_get.return_value = mock_response

        fetch_ics(
            "https://example.com/cal.ics",
            etag='"etag-val"',
            last_modified="last-mod-val",
        )

        call_kwargs = mock_get.call_args
        assert call_kwargs[1]["headers"]["If-None-Match"] == '"etag-val"'
        assert call_kwargs[1]["headers"]["If-Modified-Since"] == "last-mod-val"

    @patch("core.services.url_validation._resolve_and_check")
    @patch("core.services.url_validation.requests.get")
    def test_rejects_non_ics_content(self, mock_get, mock_resolve):
        mock_resolve.return_value = "93.184.216.34"
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.headers = {"Content-Type": "text/html"}
        mock_response.iter_content.return_value = [b"<html>Not a calendar</html>"]
        mock_get.return_value = mock_response

        with pytest.raises(URLValidationError, match="valid calendar data"):
            fetch_ics("https://example.com/cal.ics")

    @patch("core.services.url_validation._resolve_and_check")
    @patch("core.services.url_validation.requests.get")
    def test_rejects_oversized_response(self, mock_get, mock_resolve):
        mock_resolve.return_value = "93.184.216.34"
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.headers = {"Content-Type": "text/calendar"}
        # Return chunks that exceed 10 MB
        big_chunk = b"x" * (5 * 1024 * 1024)
        mock_response.iter_content.return_value = [big_chunk, big_chunk, big_chunk]
        mock_get.return_value = mock_response

        with pytest.raises(URLValidationError, match="too large"):
            fetch_ics("https://example.com/cal.ics")

    @patch("core.services.url_validation._resolve_and_check")
    @patch(
        "core.services.url_validation.requests.get",
        side_effect=requests.exceptions.Timeout("timed out"),
    )
    def test_timeout_raises(self, _mock_get, mock_resolve):
        mock_resolve.return_value = "93.184.216.34"
        with pytest.raises(URLValidationError, match="timed out"):
            fetch_ics("https://example.com/cal.ics")

    @patch("core.services.url_validation._resolve_and_check")
    @patch("core.services.url_validation.requests.get")
    def test_http_error_raises(self, mock_get, mock_resolve):
        mock_resolve.return_value = "93.184.216.34"
        mock_response = MagicMock()
        mock_response.status_code = 404
        mock_get.return_value = mock_response

        with pytest.raises(URLValidationError, match="HTTP 404"):
            fetch_ics("https://example.com/cal.ics")

    @patch("core.services.url_validation._resolve_and_check")
    @patch("core.services.url_validation.requests.get")
    def test_redirect_to_private_ip_blocked(self, mock_get, mock_resolve):
        mock_resolve.side_effect = [
            "93.184.216.34",  # initial URL check
            URLValidationError("URL resolves to a private network address"),  # redirect
        ]
        mock_response = MagicMock()
        mock_response.status_code = 302
        mock_response.headers = {"Location": "https://evil.internal/cal.ics"}
        mock_get.return_value = mock_response

        with pytest.raises(URLValidationError, match="private network"):
            fetch_ics("https://example.com/cal.ics")

    @patch("core.services.url_validation._resolve_and_check")
    @patch("core.services.url_validation.requests.get")
    def test_too_many_redirects(self, mock_get, mock_resolve):
        mock_resolve.return_value = "93.184.216.34"
        mock_response = MagicMock()
        mock_response.status_code = 302
        mock_response.headers = {"Location": "https://example.com/redirect"}
        mock_get.return_value = mock_response

        with pytest.raises(URLValidationError, match="Too many redirects"):
            fetch_ics("https://example.com/cal.ics")
