"""Abstract base class for entitlements backends."""

from abc import ABC, abstractmethod


class EntitlementsBackend(ABC):
    """Abstract base class that defines the interface for entitlements backends."""

    @abstractmethod
    def get_user_entitlements(
        self, user_sub, user_email, user_info=None, force_refresh=False
    ):
        """Fetch user entitlements.

        Args:
            user_sub: The user's OIDC subject identifier.
            user_email: The user's email address.
            user_info: The claims for the lookup. It can contain only the
                organization claim.
            force_refresh: If True, request fresh entitlements, also when
                the cache has an entry. When the request fails, the backend
                can return the cache entry.

        Returns:
            dict: {
                "can_access": bool,
                "can_admin": bool,
                "organization_name": str,  # optional, extracted from response
            }

        Raises:
            EntitlementsUnavailableError: If the backend cannot be reached.
        """
