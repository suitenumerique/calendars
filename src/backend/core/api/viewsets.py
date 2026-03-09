"""API endpoints"""

import json
import logging

from django.conf import settings
from django.core.cache import cache
from django.db.models import Q
from django.utils.text import slugify

from rest_framework import mixins, pagination, response, status, views, viewsets
from rest_framework.decorators import action
from rest_framework.parsers import MultiPartParser
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.throttling import UserRateThrottle

from core import models
from core.services.caldav_service import (
    normalize_caldav_path,
    verify_caldav_access,
)
from core.services.import_service import MAX_FILE_SIZE
from core.services.resource_service import ResourceProvisioningError, ResourceService

from . import permissions, serializers

logger = logging.getLogger(__name__)


# pylint: disable=too-many-ancestors


class SerializerPerActionMixin:
    """
    A mixin to allow to define serializer classes for each action.

    This mixin is useful to avoid to define a serializer class for each action in the
    `get_serializer_class` method.

    Example:
    ```
    class MyViewSet(SerializerPerActionMixin, viewsets.GenericViewSet):
        serializer_class = MySerializer
        list_serializer_class = MyListSerializer
        retrieve_serializer_class = MyRetrieveSerializer
    ```
    """

    def get_serializer_class(self):
        """
        Return the serializer class to use depending on the action.
        """
        if serializer_class := getattr(self, f"{self.action}_serializer_class", None):
            return serializer_class
        return super().get_serializer_class()


class Pagination(pagination.PageNumberPagination):
    """Pagination to display no more than 100 objects per page sorted by creation date."""

    ordering = "-created_at"
    max_page_size = settings.MAX_PAGE_SIZE
    page_size_query_param = "page_size"


class UserListThrottleBurst(UserRateThrottle):
    """Throttle for the user list endpoint."""

    scope = "user_list_burst"


class UserListThrottleSustained(UserRateThrottle):
    """Throttle for the user list endpoint."""

    scope = "user_list_sustained"


class UserViewSet(
    SerializerPerActionMixin,
    mixins.UpdateModelMixin,
    viewsets.GenericViewSet,
    mixins.ListModelMixin,
):
    """User ViewSet"""

    permission_classes = [permissions.IsSelf]
    queryset = models.User.objects.all().filter(is_active=True)
    serializer_class = serializers.UserSerializer
    get_me_serializer_class = serializers.UserMeSerializer
    pagination_class = Pagination
    throttle_classes = []

    def get_throttles(self):
        self.throttle_classes = []
        if self.action == "list":
            self.throttle_classes = [UserListThrottleBurst, UserListThrottleSustained]

        return super().get_throttles()

    def get_queryset(self):
        """
        Limit listed users by querying email or full_name.
        Scoped to the requesting user's organization.
        Minimum 3 characters required.
        """
        queryset = self.queryset

        if self.action != "list":
            return queryset

        # Scope to same organization; users without an org see no results
        if not self.request.user.organization_id:
            return queryset.none()
        queryset = queryset.filter(organization_id=self.request.user.organization_id)

        if not (query := self.request.query_params.get("q", "")) or len(query) < 3:
            return queryset.none()

        # Search by email (partial, case-insensitive) or full name
        return queryset.filter(
            Q(email__icontains=query) | Q(full_name__icontains=query)
        ).order_by("full_name", "email")[:50]

    @action(
        detail=False,
        methods=["get"],
        url_name="me",
        url_path="me",
    )
    def get_me(self, request):
        """
        Return information on currently logged user
        """
        context = {"request": request}
        return response.Response(
            self.get_serializer(request.user, context=context).data
        )


class ConfigView(views.APIView):
    """API ViewSet for sharing some public settings."""

    permission_classes = [AllowAny]

    def get(self, request):
        """
        GET /api/v1.0/config/
            Return a dictionary of public settings.
        """
        array_settings = [
            "ENVIRONMENT",
            "FRONTEND_THEME",
            "FRONTEND_MORE_LINK",
            "FRONTEND_FEEDBACK_BUTTON_SHOW",
            "FRONTEND_FEEDBACK_BUTTON_IDLE",
            "FRONTEND_FEEDBACK_ITEMS",
            "FRONTEND_FEEDBACK_MESSAGES_WIDGET_ENABLED",
            "FRONTEND_FEEDBACK_MESSAGES_WIDGET_API_URL",
            "FRONTEND_FEEDBACK_MESSAGES_WIDGET_CHANNEL",
            "FRONTEND_FEEDBACK_MESSAGES_WIDGET_PATH",
            "FRONTEND_HIDE_GAUFRE",
            "MEDIA_BASE_URL",
            "LANGUAGES",
            "LANGUAGE_CODE",
            "SENTRY_DSN",
        ]
        dict_settings = {}
        for setting in array_settings:
            if hasattr(settings, setting):
                dict_settings[setting] = getattr(settings, setting)

        dict_settings["theme_customization"] = self._load_theme_customization()

        return response.Response(dict_settings)

    def _load_theme_customization(self):
        if not settings.THEME_CUSTOMIZATION_FILE_PATH:
            return {}

        cache_key = (
            f"theme_customization_{slugify(settings.THEME_CUSTOMIZATION_FILE_PATH)}"
        )
        theme_customization = cache.get(cache_key, {})
        if theme_customization:
            return theme_customization

        try:
            with open(
                settings.THEME_CUSTOMIZATION_FILE_PATH, "r", encoding="utf-8"
            ) as f:
                theme_customization = json.load(f)
        except FileNotFoundError:
            logger.error(
                "Configuration file not found: %s",
                settings.THEME_CUSTOMIZATION_FILE_PATH,
            )
        except json.JSONDecodeError:
            logger.error(
                "Configuration file is not a valid JSON: %s",
                settings.THEME_CUSTOMIZATION_FILE_PATH,
            )
        else:
            cache.set(
                cache_key,
                theme_customization,
                settings.THEME_CUSTOMIZATION_CACHE_TIMEOUT,
            )

        return theme_customization


class OrganizationSettingsViewSet(viewsets.ViewSet):
    """ViewSet for organization settings (sharing level, etc.).

    Only org admins can update settings; all org members can read them.
    """

    permission_classes = [IsAuthenticated]

    def retrieve(self, request, pk=None):  # pylint: disable=unused-argument
        """GET /api/v1.0/organization-settings/current/"""
        org = request.user.organization
        if not org:
            return response.Response(
                {"detail": "User has no organization."},
                status=status.HTTP_404_NOT_FOUND,
            )
        return response.Response(serializers.OrganizationSerializer(org).data)

    def partial_update(self, request, pk=None):  # pylint: disable=unused-argument
        """PATCH /api/v1.0/organization-settings/current/"""
        if not request.user.organization:
            return response.Response(
                {"detail": "User has no organization."},
                status=status.HTTP_404_NOT_FOUND,
            )

        # Check admin permission
        perm = permissions.IsOrgAdmin()
        if not perm.has_permission(request, self):
            return response.Response(
                {"detail": "Only org admins can update settings."},
                status=status.HTTP_403_FORBIDDEN,
            )

        org = request.user.organization
        sharing_level = request.data.get("default_sharing_level")
        if sharing_level is not None:
            valid = {c[0] for c in models.SharingLevel.choices}
            if sharing_level not in valid:
                return response.Response(
                    {
                        "detail": f"Invalid sharing level. Must be one of: {', '.join(valid)}"
                    },
                    status=status.HTTP_400_BAD_REQUEST,
                )
            org.default_sharing_level = sharing_level
            org.save(update_fields=["default_sharing_level", "updated_at"])

        return response.Response(serializers.OrganizationSerializer(org).data)


class CalendarViewSet(viewsets.GenericViewSet):
    """ViewSet for calendar operations.

    import_events: Import events from an ICS file.
    """

    permission_classes = [IsAuthenticated]

    def get_permissions(self):
        if self.action == "import_events":
            return [permissions.IsEntitledToAccess()]
        return super().get_permissions()

    @action(
        detail=False,
        methods=["post"],
        parser_classes=[MultiPartParser],
        url_path="import-events",
        url_name="import-events",
    )
    def import_events(self, request, **kwargs):
        """Import events from an ICS file into a calendar.

        POST /api/v1.0/calendars/import-events/
        Body (multipart): file=<ics>, caldav_path=/calendars/users/user@.../uuid/

        Returns a task_id that can be polled at GET /api/v1.0/tasks/{task_id}/
        """
        from core.tasks import (  # noqa: PLC0415  # pylint: disable=import-outside-toplevel
            import_events_task,
        )

        caldav_path = request.data.get("caldav_path", "")
        if not caldav_path:
            return response.Response(
                {"detail": "caldav_path is required"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        caldav_path = normalize_caldav_path(caldav_path)

        # Verify user access
        if not verify_caldav_access(request.user, caldav_path):
            return response.Response(
                {"detail": "You don't have access to this calendar"},
                status=status.HTTP_403_FORBIDDEN,
            )

        # Validate file presence
        if "file" not in request.FILES:
            return response.Response(
                {"detail": "No file provided"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        uploaded_file = request.FILES["file"]

        # Validate file size
        if uploaded_file.size > MAX_FILE_SIZE:
            return response.Response(
                {"detail": "File too large. Maximum size is 10 MB."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        ics_data = uploaded_file.read()

        # Queue the import task
        task = import_events_task.delay(
            str(request.user.id),
            caldav_path,
            ics_data.hex(),
        )
        task.track_owner(request.user.id)

        return response.Response(
            {"task_id": task.id},
            status=status.HTTP_202_ACCEPTED,
        )


class ResourceViewSet(viewsets.ViewSet):
    """ViewSet for resource provisioning (create/delete).

    Resources are CalDAV principals — this endpoint only handles
    provisioning. All metadata, sharing, and discovery goes through CalDAV.
    """

    permission_classes = [permissions.IsOrgAdmin]

    def create(self, request):
        """Create a resource principal and its default calendar.

        POST /api/v1.0/resources/
        Body: {"name": "Room 101", "resource_type": "ROOM"}
        """
        name = request.data.get("name", "").strip()
        resource_type = request.data.get("resource_type", "ROOM").strip().upper()

        if not name:
            return response.Response(
                {"detail": "name is required."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        service = ResourceService()
        try:
            result = service.create_resource(request.user, name, resource_type)
        except ResourceProvisioningError as e:
            return response.Response(
                {"detail": str(e)},
                status=status.HTTP_400_BAD_REQUEST,
            )

        return response.Response(result, status=status.HTTP_201_CREATED)

    def destroy(self, request, pk=None):
        """Delete a resource principal and its calendar.

        DELETE /api/v1.0/resources/{resource_id}/
        """
        resource_id = pk
        if not resource_id:
            return response.Response(
                {"detail": "Resource ID is required."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        service = ResourceService()
        try:
            service.delete_resource(request.user, resource_id)
        except ResourceProvisioningError as e:
            return response.Response(
                {"detail": str(e)},
                status=status.HTTP_400_BAD_REQUEST,
            )

        return response.Response(status=status.HTTP_204_NO_CONTENT)
