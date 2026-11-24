"""Entitlements service layer."""

from django.conf import settings
from django.utils.functional import SimpleLazyObject

from core.entitlements.factory import get_entitlements_backend


class EntitlementsUnavailableError(Exception):
    """Raised when the entitlements backend cannot be reached or returns an error."""


def _organization_claims(user):
    """Map the organization claim to the external_id of the user's organization.

    The mapping is empty when OIDC_USERINFO_ORGANIZATION_CLAIM is empty.
    """
    claim = settings.OIDC_USERINFO_ORGANIZATION_CLAIM
    if not claim:
        return {}
    return {claim: user.organization.external_id}


def get_user_entitlements(user, user_info=None, force_refresh=False):
    """Get user entitlements, delegating to the configured backend.

    Args:
        user: The user that the entitlements are for.
        user_info: The claims for the lookup. When None, the backend gets
            the organization claim of the stored user.
        force_refresh: If True, request fresh entitlements, also when the
            cache has an entry. When the request fails, the backend can
            return the cache entry.

    Returns:
        dict: {"can_access": bool, "can_admin": bool, ...}

    Raises:
        EntitlementsUnavailableError: If the backend cannot be reached
            and no cache exists.
    """
    if user_info is None:
        # Read the organization only when the backend reads the claims.
        user_info = SimpleLazyObject(lambda: _organization_claims(user))
    backend = get_entitlements_backend()
    return backend.get_user_entitlements(
        user.sub, user.email, user_info=user_info, force_refresh=force_refresh
    )
