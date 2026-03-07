"""Authentication Backends for the Calendars core app."""

import logging

from django.conf import settings
from django.core.exceptions import SuspiciousOperation

from lasuite.oidc_login.backends import (
    OIDCAuthenticationBackend as LaSuiteOIDCAuthenticationBackend,
)

from core.entitlements import EntitlementsUnavailableError, get_user_entitlements
from core.models import DuplicateEmailError, Organization

logger = logging.getLogger(__name__)


class OIDCAuthenticationBackend(LaSuiteOIDCAuthenticationBackend):
    """Custom OpenID Connect (OIDC) Authentication Backend.

    This class overrides the default OIDC Authentication Backend to accommodate differences
    in the User and Identity models, and handles signed and/or encrypted UserInfo response.
    """

    def get_extra_claims(self, user_info):
        """
        Return extra claims from user_info.

        Args:
          user_info (dict): The user information dictionary.

        Returns:
          dict: A dictionary of extra claims.
        """

        # We need to add the claims that we want to store so that they are
        # available in the post_get_or_create_user method.
        claims_to_store = {
            claim: user_info.get(claim) for claim in settings.OIDC_STORE_CLAIMS
        }
        return {
            "full_name": self.compute_full_name(user_info),
            "claims": claims_to_store,
        }

    def get_existing_user(self, sub, email):
        """Fetch existing user by sub or email."""

        try:
            return self.UserModel.objects.get_user_by_sub_or_email(sub, email)
        except DuplicateEmailError as err:
            raise SuspiciousOperation(err.message) from err

    def post_get_or_create_user(self, user, claims, is_new_user):
        """Warm the entitlements cache and resolve organization on login."""
        entitlements = {}
        try:
            entitlements = get_user_entitlements(
                user_sub=user.sub,
                user_email=user.email,
                user_info=claims,
                force_refresh=True,
            )
        except EntitlementsUnavailableError:
            logger.warning(
                "Entitlements unavailable for %s during login",
                user.email,
            )

        self._resolve_organization(user, claims, entitlements)

    @staticmethod
    def _resolve_organization(user, claims, entitlements):
        """Resolve and assign the user's organization.

        The org identifier (external_id) comes from the OIDC claim
        configured via OIDC_USERINFO_ORGANIZATION_CLAIM, or falls back to the
        email domain. The org name comes from the entitlements response.
        """
        claim_key = settings.OIDC_USERINFO_ORGANIZATION_CLAIM
        if claim_key:
            external_id = claims.get(claim_key)
        else:
            # Default: derive org from email domain
            external_id = (
                user.email.split("@")[-1] if user.email and "@" in user.email else None
            )

        if not external_id:
            return

        org_name = entitlements.get("organization_name", "") or external_id

        org, created = Organization.objects.get_or_create(
            external_id=external_id,
            defaults={"name": org_name},
        )
        if not created and org_name and org.name != org_name:
            org.name = org_name
            org.save(update_fields=["name"])

        if user.organization_id != org.id:
            user.organization = org
            user.save(update_fields=["organization"])
