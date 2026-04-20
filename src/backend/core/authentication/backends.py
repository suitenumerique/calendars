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


def _resolve_org_external_id(claims, email=None):
    """Extract the organization external_id from OIDC claims or email domain.

    When ``OIDC_USERINFO_ORGANIZATION_CLAIM`` is configured, the claim
    MUST be present in the OIDC userinfo — no fallback. Deployments
    that opt into the claim want strict org identity, and silently
    falling back to the email domain would attach users to the wrong
    org. Returns ``None`` if the claim is missing so the caller can
    fail closed.

    When the setting is empty, fall back to the email domain so
    deployments without an org claim still work.
    """
    claim_key = settings.OIDC_USERINFO_ORGANIZATION_CLAIM
    if claim_key:
        return claims.get(claim_key) or None
    email = email or claims.get("email")
    return email.split("@")[-1] if email and "@" in email else None


def resolve_organization(user, claims, entitlements=None):
    """Resolve and assign the user's organization.

    The org identifier (external_id) comes from the OIDC claim configured via
    OIDC_USERINFO_ORGANIZATION_CLAIM, or falls back to the email domain.
    The org name comes from the entitlements response.
    """
    entitlements = entitlements or {}
    external_id = _resolve_org_external_id(claims, email=user.email)
    if not external_id:
        logger.error(
            "Cannot resolve organization for user %s: no org claim or email domain",
            user.email,
        )
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


class OIDCAuthenticationBackend(LaSuiteOIDCAuthenticationBackend):
    """Custom OpenID Connect (OIDC) Authentication Backend.

    This class overrides the default OIDC Authentication Backend to accommodate differences
    in the User and Identity models, and handles signed and/or encrypted UserInfo response.
    """

    def get_extra_claims(self, user_info):
        """Return extra claims from user_info.

        The org claim (``OIDC_USERINFO_ORGANIZATION_CLAIM``) is surfaced at
        the top level so ``_resolve_org_external_id`` can read it directly,
        independently of whether it's also listed in ``OIDC_STORE_CLAIMS``.
        """
        claims_to_store = {
            claim: user_info.get(claim) for claim in settings.OIDC_STORE_CLAIMS
        }
        extra = {
            "full_name": self.compute_full_name(user_info),
            "claims": claims_to_store,
        }
        org_claim = settings.OIDC_USERINFO_ORGANIZATION_CLAIM
        if org_claim:
            extra[org_claim] = user_info.get(org_claim)
        return extra

    def get_existing_user(self, sub, email):
        """Fetch existing user by sub or email."""
        try:
            return self.UserModel.objects.get_user_by_sub_or_email(sub, email)
        except DuplicateEmailError as err:
            raise SuspiciousOperation(err.message) from err

    def create_user(self, claims):
        """Create a new user, resolving their organization first.

        Organization is NOT NULL, so we must resolve it before the initial save.
        The org claim is surfaced at the top level of ``claims`` by
        ``get_extra_claims`` so we can read it here. It must be popped before
        delegating to ``super().create_user``, which forwards unknown top-level
        keys as ``User(**claims)`` kwargs and would otherwise error.
        """
        external_id = _resolve_org_external_id(claims)
        if not external_id:
            raise SuspiciousOperation(
                "Cannot create user without an organization "
                "(no org claim and no email domain)"
            )

        org_claim = settings.OIDC_USERINFO_ORGANIZATION_CLAIM
        if org_claim:
            claims.pop(org_claim, None)

        org, _ = Organization.objects.get_or_create(
            external_id=external_id,
            defaults={"name": external_id},
        )
        claims["organization"] = org
        return super().create_user(claims)

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

        resolve_organization(user, claims, entitlements)
