"""API endpoints"""
# pylint: disable=too-many-lines

import json
import logging
import re
from urllib.parse import unquote

from django.conf import settings
from django.core.cache import cache
from django.utils.text import slugify

import rest_framework as drf
from rest_framework import response as drf_response
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.parsers import MultiPartParser
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.throttling import UserRateThrottle

from core import models
from core.services.caldav_service import CalendarService
from core.services.import_service import MAX_FILE_SIZE, ICSImportService

from . import permissions, serializers

logger = logging.getLogger(__name__)


# pylint: disable=too-many-ancestors


class NestedGenericViewSet(viewsets.GenericViewSet):
    """
    A generic Viewset aims to be used in a nested route context.
    e.g: `/api/v1.0/resource_1/<resource_1_pk>/resource_2/<resource_2_pk>/`

    It allows to define all url kwargs and lookup fields to perform the lookup.
    """

    lookup_fields: list[str] = ["pk"]
    lookup_url_kwargs: list[str] = []

    def __getattribute__(self, item):
        """
        This method is overridden to allow to get the last lookup field or lookup url kwarg
        when accessing the `lookup_field` or `lookup_url_kwarg` attribute. This is useful
        to keep compatibility with all methods used by the parent class `GenericViewSet`.
        """
        if item in ["lookup_field", "lookup_url_kwarg"]:
            return getattr(self, item + "s", [None])[-1]

        return super().__getattribute__(item)

    def get_queryset(self):
        """
        Get the list of items for this view.

        `lookup_fields` attribute is enumerated here to perform the nested lookup.
        """
        queryset = super().get_queryset()

        # The last lookup field is removed to perform the nested lookup as it corresponds
        # to the object pk, it is used within get_object method.
        lookup_url_kwargs = (
            self.lookup_url_kwargs[:-1]
            if self.lookup_url_kwargs
            else self.lookup_fields[:-1]
        )

        filter_kwargs = {}
        for index, lookup_url_kwarg in enumerate(lookup_url_kwargs):
            if lookup_url_kwarg not in self.kwargs:
                raise KeyError(
                    f"Expected view {self.__class__.__name__} to be called with a URL "
                    f'keyword argument named "{lookup_url_kwarg}". Fix your URL conf, or '
                    "set the `.lookup_fields` attribute on the view correctly."
                )

            filter_kwargs.update(
                {self.lookup_fields[index]: self.kwargs[lookup_url_kwarg]}
            )

        return queryset.filter(**filter_kwargs)


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


class Pagination(drf.pagination.PageNumberPagination):
    """Pagination to display no more than 100 objects per page sorted by creation date."""

    ordering = "-created_on"
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
    drf.mixins.UpdateModelMixin,
    viewsets.GenericViewSet,
    drf.mixins.ListModelMixin,
):
    """User ViewSet"""

    permission_classes = [permissions.IsSelf]
    queryset = models.User.objects.all().filter(is_active=True)
    serializer_class = serializers.UserSerializer
    get_me_serializer_class = serializers.UserMeSerializer
    pagination_class = None
    throttle_classes = []

    def get_throttles(self):
        self.throttle_classes = []
        if self.action == "list":
            self.throttle_classes = [UserListThrottleBurst, UserListThrottleSustained]

        return super().get_throttles()

    def get_queryset(self):
        """
        Limit listed users by querying the email field.
        If query contains "@", search exactly. Otherwise return empty.
        """
        queryset = self.queryset

        if self.action != "list":
            return queryset

        if not (query := self.request.query_params.get("q", "")) or len(query) < 5:
            return queryset.none()

        # For emails, match exactly
        if "@" in query:
            return queryset.filter(email__iexact=query).order_by("email")[
                : settings.API_USERS_LIST_LIMIT
            ]

        # For non-email queries, return empty (no fuzzy search)
        return queryset.none()

    @drf.decorators.action(
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
        return drf.response.Response(
            self.get_serializer(request.user, context=context).data
        )


class ConfigView(drf.views.APIView):
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

        return drf.response.Response(dict_settings)

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


# Regex for CalDAV path validation (shared with SubscriptionTokenViewSet)
# Pattern: /calendars/<email-or-encoded>/<calendar-id>/
CALDAV_PATH_PATTERN = re.compile(
    r"^/calendars/[^/]+/[a-zA-Z0-9-]+/$",
)


def _verify_caldav_access(user, caldav_path):
    """Verify that the user has access to the CalDAV calendar.

    Checks that:
    1. The path matches the expected pattern (prevents path injection)
    2. The user's email matches the email in the path
    """
    if not CALDAV_PATH_PATTERN.match(caldav_path):
        return False
    parts = caldav_path.strip("/").split("/")
    if len(parts) >= 2 and parts[0] == "calendars":
        path_email = unquote(parts[1])
        return path_email.lower() == user.email.lower()
    return False


def _normalize_caldav_path(caldav_path):
    """Normalize CalDAV path to consistent format.

    Strips the CalDAV API prefix (e.g. /api/v1.0/caldav/) if present,
    so that paths like /api/v1.0/caldav/calendars/user@ex.com/uuid/
    become /calendars/user@ex.com/uuid/.
    """
    if not caldav_path.startswith("/"):
        caldav_path = "/" + caldav_path
    # Strip CalDAV API prefix — keep from /calendars/ onwards
    calendars_idx = caldav_path.find("/calendars/")
    if calendars_idx > 0:
        caldav_path = caldav_path[calendars_idx:]
    if not caldav_path.endswith("/"):
        caldav_path = caldav_path + "/"
    return caldav_path


class CalendarViewSet(viewsets.GenericViewSet):
    """ViewSet for calendar operations.

    create: Create a new calendar (CalDAV only, no Django record).
    import_events: Import events from an ICS file.
    """

    permission_classes = [IsAuthenticated]
    serializer_class = serializers.CalendarCreateSerializer

    def create(self, request):
        """Create a new calendar via CalDAV.

        POST /api/v1.0/calendars/
        Body: { name, color?, description? }
        Returns: { caldav_path }
        """
        serializer = serializers.CalendarCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        service = CalendarService()
        caldav_path = service.create_calendar(
            user=request.user,
            name=serializer.validated_data["name"],
            color=serializer.validated_data.get("color", "#3174ad"),
        )

        return drf_response.Response(
            {"caldav_path": caldav_path},
            status=status.HTTP_201_CREATED,
        )

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
        Body (multipart): file=<ics>, caldav_path=/calendars/user@.../uuid/
        """
        caldav_path = request.data.get("caldav_path", "")
        if not caldav_path:
            return drf_response.Response(
                {"error": "caldav_path is required"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        caldav_path = _normalize_caldav_path(caldav_path)

        # Verify user access
        if not _verify_caldav_access(request.user, caldav_path):
            return drf_response.Response(
                {"error": "You don't have access to this calendar"},
                status=status.HTTP_403_FORBIDDEN,
            )

        # Validate file presence
        if "file" not in request.FILES:
            return drf_response.Response(
                {"error": "No file provided"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        uploaded_file = request.FILES["file"]

        # Validate file size
        if uploaded_file.size > MAX_FILE_SIZE:
            return drf_response.Response(
                {"error": "File too large. Maximum size is 10 MB."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        ics_data = uploaded_file.read()
        service = ICSImportService()
        result = service.import_events(request.user, caldav_path, ics_data)

        response_data = {
            "total_events": result.total_events,
            "imported_count": result.imported_count,
            "duplicate_count": result.duplicate_count,
            "skipped_count": result.skipped_count,
        }
        if result.errors:
            response_data["errors"] = result.errors

        return drf_response.Response(response_data, status=status.HTTP_200_OK)


class SubscriptionTokenViewSet(viewsets.GenericViewSet):
    """
    ViewSet for managing subscription tokens independently of Django Calendar model.

    This viewset operates directly with CalDAV paths, without requiring a Django
    Calendar record. The backend verifies that the user has access to the calendar
    by checking that their email is in the CalDAV path.

    Endpoints:
    - POST /api/v1.0/subscription-tokens/ - Create or get existing token
    - GET /api/v1.0/subscription-tokens/by-path/ - Get token by CalDAV path
    - DELETE /api/v1.0/subscription-tokens/by-path/ - Delete token by CalDAV path
    """

    permission_classes = [IsAuthenticated]
    serializer_class = serializers.CalendarSubscriptionTokenSerializer

    def create(self, request):
        """
        Create or get existing subscription token.

        POST body:
        - caldav_path: The CalDAV path (e.g., /calendars/user@example.com/uuid/)
        - calendar_name: Display name of the calendar (optional)
        """
        create_serializer = serializers.CalendarSubscriptionTokenCreateSerializer(
            data=request.data
        )
        create_serializer.is_valid(raise_exception=True)

        caldav_path = create_serializer.validated_data["caldav_path"]
        calendar_name = create_serializer.validated_data.get("calendar_name", "")

        # Verify user has access to this calendar
        if not _verify_caldav_access(request.user, caldav_path):
            return drf_response.Response(
                {"error": "You don't have access to this calendar"},
                status=status.HTTP_403_FORBIDDEN,
            )

        # Get or create token
        token, created = models.CalendarSubscriptionToken.objects.get_or_create(
            owner=request.user,
            caldav_path=caldav_path,
            defaults={"calendar_name": calendar_name},
        )

        # Update calendar_name if provided and different
        if not created and calendar_name and token.calendar_name != calendar_name:
            token.calendar_name = calendar_name
            token.save(update_fields=["calendar_name"])

        serializer = self.get_serializer(token, context={"request": request})
        return drf_response.Response(
            serializer.data,
            status=status.HTTP_201_CREATED if created else status.HTTP_200_OK,
        )

    @action(detail=False, methods=["get", "delete"], url_path="by-path")
    def by_path(self, request):
        """
        Get or delete subscription token by CalDAV path.

        Query parameter:
        - caldav_path: The CalDAV path (e.g., /calendars/user@example.com/uuid/)
        """
        caldav_path = request.query_params.get("caldav_path")
        if not caldav_path:
            return drf_response.Response(
                {"error": "caldav_path query parameter is required"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        caldav_path = _normalize_caldav_path(caldav_path)

        # Verify user has access to this calendar
        if not _verify_caldav_access(request.user, caldav_path):
            return drf_response.Response(
                {"error": "You don't have access to this calendar"},
                status=status.HTTP_403_FORBIDDEN,
            )

        try:
            token = models.CalendarSubscriptionToken.objects.get(
                owner=request.user,
                caldav_path=caldav_path,
            )
        except models.CalendarSubscriptionToken.DoesNotExist:
            return drf_response.Response(
                {"error": "No subscription token exists for this calendar"},
                status=status.HTTP_404_NOT_FOUND,
            )

        if request.method == "GET":
            serializer = self.get_serializer(token, context={"request": request})
            return drf_response.Response(serializer.data)

        # DELETE
        token.delete()
        return drf_response.Response(status=status.HTTP_204_NO_CONTENT)
