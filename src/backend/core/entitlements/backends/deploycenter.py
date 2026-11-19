"""DeployCenter (Espace Operateur) entitlements backend."""

import logging
from urllib.parse import urlencode

from django.conf import settings
from django.core.cache import cache

import requests

from core.entitlements import EntitlementsUnavailableError
from core.entitlements.backends.base import EntitlementsBackend

logger = logging.getLogger(__name__)


class DeployCenterEntitlementsBackend(EntitlementsBackend):
    """Backend that fetches entitlements from the DeployCenter API.

    Args:
        base_url: Full URL of the entitlements endpoint
            (e.g. "https://dc.example.com/api/v1.0/entitlements/").
        service_id: The service identifier in DeployCenter.
        api_key: API key for X-Service-Auth header.
        timeout: HTTP request timeout in seconds.
        oidc_claims: List of OIDC claim names to extract from user_info
            and forward as query params (e.g. ["siret"]). DeployCenter
            refuses a request without "siret".
    """

    def __init__(  # pylint: disable=too-many-arguments
        self,
        base_url,
        service_id,
        api_key,
        *,
        timeout=10,
        oidc_claims=None,
    ):
        self.base_url = base_url
        self.service_id = service_id
        self.api_key = api_key
        self.timeout = timeout
        self.oidc_claims = oidc_claims or []

    def _claims(self, user_info):
        """Return the configured claims that have a truthy value in *user_info*."""
        user_info = user_info or {}
        return {
            claim: user_info[claim]
            for claim in self.oidc_claims
            if user_info.get(claim)
        }

    def _cache_key(self, user_sub, claims):
        return f"entitlements:user:{user_sub}:{urlencode(claims)}"

    def _make_request(self, user_email, claims):
        """Make a request to the DeployCenter entitlements API.

        Returns:
            dict | None: The response data, or None on failure.
        """
        params = {
            "service_id": self.service_id,
            "account_type": "user",
            "account_email": user_email,
            **claims,
        }

        headers = {
            "X-Service-Auth": f"Bearer {self.api_key}",
        }

        try:
            response = requests.get(
                self.base_url,
                params=params,
                headers=headers,
                timeout=self.timeout,
            )
            response.raise_for_status()
            return response.json()
        except (requests.RequestException, ValueError):
            email_domain = user_email.split("@")[-1] if "@" in user_email else "?"
            logger.warning(
                "DeployCenter entitlements request failed for user@%s",
                email_domain,
                exc_info=True,
            )
            return None

    def get_user_entitlements(
        self, user_sub, user_email, user_info=None, force_refresh=False
    ):
        """Fetch user entitlements from DeployCenter with caching.

        On a cache miss or with force_refresh, call the API. When the call
        fails, return the cache entry if it has not expired. Otherwise raise
        EntitlementsUnavailableError. A returned entry keeps its expiry time.

        A cache entry is for one user and one set of forwarded claims. An
        answer for one organization is thus never served for another one.
        """
        claims = self._claims(user_info)
        cache_key = self._cache_key(user_sub, claims)

        if not force_refresh:
            cached = cache.get(cache_key)
            if cached is not None:
                return cached

        data = self._make_request(user_email, claims)

        if data is None:
            # API failed — try stale cache as fallback
            cached = cache.get(cache_key)
            if cached is not None:
                return cached
            raise EntitlementsUnavailableError(
                "Failed to fetch user entitlements from DeployCenter"
            )

        entitlements = data.get("entitlements", {})
        result = {
            "can_access": entitlements.get("can_access", False),
            # DeployCenter names the administrator entitlement "is_admin".
            "can_admin": entitlements.get("is_admin", False),
        }

        # Organization name from DeployCenter response (if present)
        org = data.get("organization") or {}
        org_name = org.get("name", "")
        if org_name:
            result["organization_name"] = org_name

        cache.set(cache_key, result, settings.ENTITLEMENTS_CACHE_TIMEOUT)
        return result
