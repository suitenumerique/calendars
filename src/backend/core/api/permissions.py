"""Permission handlers for the calendars core app."""

import logging

from rest_framework import permissions

from core.entitlements import EntitlementsUnavailableError, get_user_entitlements

logger = logging.getLogger(__name__)


class IsAuthenticated(permissions.BasePermission):
    """
    Allows access only to authenticated users. Alternative method checking the presence
    of the auth token to avoid hitting the database.
    """

    def has_permission(self, request, view):
        return bool(request.auth) or request.user.is_authenticated


class IsSelf(IsAuthenticated):
    """
    Allows access only to authenticated users. Alternative method checking the presence
    of the auth token to avoid hitting the database.
    """

    def has_object_permission(self, request, view, obj):
        """Write permissions are only allowed to the user itself."""
        return obj == request.user


class IsEntitledToAccess(IsAuthenticated):
    """Allows access only to users with can_access entitlement.

    Fail-closed: denies access when the entitlements service is
    unavailable and no cached value exists.
    """

    def has_permission(self, request, view):
        if not super().has_permission(request, view):
            return False
        try:
            entitlements = get_user_entitlements(request.user.sub, request.user.email)
            return entitlements.get("can_access", False)
        except EntitlementsUnavailableError:
            logger.warning(
                "Entitlements unavailable, denying access for user %s",
                request.user.pk,
            )
            return False


class IsOrgAdmin(IsAuthenticated):
    """Allows access only to users with can_admin entitlement.

    Fail-closed: denies access when the entitlements service is
    unavailable and no cached value exists.
    """

    def has_permission(self, request, view):
        if not super().has_permission(request, view):
            return False
        try:
            entitlements = get_user_entitlements(request.user.sub, request.user.email)
            return entitlements.get("can_admin", False)
        except EntitlementsUnavailableError:
            logger.warning(
                "Entitlements unavailable, denying admin for user %s",
                request.user.pk,
            )
            return False
