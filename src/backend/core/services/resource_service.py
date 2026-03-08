"""Service for managing calendar resource provisioning via CalDAV."""

import json
import logging
from uuid import UUID, uuid4

from django.conf import settings

from core.services.caldav_service import CalDAVHTTPClient

logger = logging.getLogger(__name__)


class ResourceProvisioningError(Exception):
    """Raised when resource provisioning fails."""


class ResourceService:
    """Provisions and deletes resource principals in SabreDAV.

    Resources are CalDAV principals — this service creates them by
    making HTTP requests to the SabreDAV internal API. No Django model
    is created; the CalDAV principal IS the resource.
    """

    def __init__(self):
        self._http = CalDAVHTTPClient()

    def _resource_email(self, resource_id):
        """Generate a resource scheduling address."""
        domain = settings.RESOURCE_EMAIL_DOMAIN
        if not domain:
            domain = "resource.invalid"
        return f"{resource_id}@{domain}"

    def create_resource(self, user, name, resource_type="ROOM"):
        """Provision a resource principal and its default calendar.

        Args:
            user: The admin user creating the resource (provides auth context).
            name: Display name for the resource.
            resource_type: "ROOM" or "RESOURCE".

        Returns:
            dict with resource info: id, email, principal_uri, calendar_uri.

        Raises:
            ResourceProvisioningError on failure.
        """
        if resource_type not in ("ROOM", "RESOURCE"):
            raise ResourceProvisioningError(
                "resource_type must be 'ROOM' or 'RESOURCE'."
            )

        if not settings.CALDAV_INTERNAL_API_KEY:
            raise ResourceProvisioningError(
                "CALDAV_INTERNAL_API_KEY is not configured."
            )

        resource_id = str(uuid4())
        email = self._resource_email(resource_id)
        org_id = str(user.organization_id)

        try:
            response = self._http.request(
                "POST",
                user,
                "internal-api/resources/",
                data=self._json_bytes(
                    {
                        "resource_id": resource_id,
                        "name": name,
                        "email": email,
                        "resource_type": resource_type,
                        "org_id": org_id,
                    }
                ),
                content_type="application/json",
                extra_headers={
                    "X-Internal-Api-Key": settings.CALDAV_INTERNAL_API_KEY,
                },
            )
        except Exception as e:
            logger.error("Failed to create resource principal: %s", e)
            raise ResourceProvisioningError(
                "Failed to create resource principal."
            ) from e

        if response.status_code == 409:
            raise ResourceProvisioningError(f"Resource '{resource_id}' already exists.")

        if response.status_code != 201:
            logger.error(
                "InternalApi create resource returned %s: %s",
                response.status_code,
                response.text[:500],
            )
            raise ResourceProvisioningError("Failed to create resource principal.")

        principal_uri = f"principals/resources/{resource_id}"
        calendar_uri = f"calendars/resources/{resource_id}/default/"

        return {
            "id": resource_id,
            "email": email,
            "name": name,
            "resource_type": resource_type,
            "principal_uri": principal_uri,
            "calendar_uri": calendar_uri,
        }

    @staticmethod
    def _validate_resource_id(resource_id):
        """Validate that resource_id is a proper UUID.

        Raises ResourceProvisioningError if the ID is not a valid UUID,
        preventing path traversal via crafted IDs.
        """
        try:
            UUID(str(resource_id))
        except (ValueError, AttributeError) as e:
            raise ResourceProvisioningError(
                "Invalid resource ID: must be a valid UUID."
            ) from e

    def delete_resource(self, user, resource_id):
        """Delete a resource principal and its calendar.

        Events in user calendars that reference this resource are left
        as-is — the resource address becomes unresolvable.

        Args:
            user: The admin user requesting deletion.
            resource_id: The resource UUID.

        Raises:
            ResourceProvisioningError on failure.
        """
        self._validate_resource_id(resource_id)

        if not settings.CALDAV_INTERNAL_API_KEY:
            raise ResourceProvisioningError(
                "CALDAV_INTERNAL_API_KEY is not configured."
            )

        try:
            response = self._http.request(
                "DELETE",
                user,
                f"internal-api/resources/{resource_id}",
                extra_headers={
                    "X-Internal-Api-Key": settings.CALDAV_INTERNAL_API_KEY,
                },
            )
        except Exception as e:
            logger.error("Failed to delete resource: %s", e)
            raise ResourceProvisioningError("Failed to delete resource.") from e

        if response.status_code == 404:
            raise ResourceProvisioningError(f"Resource '{resource_id}' not found.")

        if response.status_code == 403:
            try:
                error_msg = response.json().get("error", "")
            except ValueError:
                error_msg = ""
            raise ResourceProvisioningError(
                error_msg or "Cannot delete a resource from a different organization."
            )

        if response.status_code not in (200, 204):
            logger.error(
                "InternalApi delete resource returned %s: %s",
                response.status_code,
                response.text[:500],
            )
            raise ResourceProvisioningError("Failed to delete resource.")

    @staticmethod
    def _json_bytes(data):
        """Serialize a dict to JSON bytes."""
        return json.dumps(data).encode("utf-8")
