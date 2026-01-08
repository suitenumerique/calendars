"""API endpoints"""
# pylint: disable=too-many-lines

import json
import logging
import re
from urllib.parse import unquote, urlparse

from django.conf import settings
from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.db import models as db
from django.db import transaction
from django.urls import reverse
from django.utils.decorators import method_decorator
from django.utils.text import slugify

import rest_framework as drf
from corsheaders.middleware import (
    ACCESS_CONTROL_ALLOW_METHODS,
    ACCESS_CONTROL_ALLOW_ORIGIN,
)
from lasuite.oidc_login.decorators import refresh_oidc_access_token
from rest_framework import filters, mixins, status, viewsets
from rest_framework import response as drf_response
from rest_framework.decorators import action
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.throttling import UserRateThrottle
from rest_framework_api_key.permissions import HasAPIKey

from core import enums, models
from core.services.caldav_service import CalendarService

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


# CalDAV ViewSets
class CalendarViewSet(
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.CreateModelMixin,
    mixins.UpdateModelMixin,
    mixins.DestroyModelMixin,
    viewsets.GenericViewSet,
):
    """
    ViewSet for managing user calendars.

    list: Get all calendars accessible by the user (owned + shared)
    retrieve: Get a specific calendar
    create: Create a new calendar
    update: Update calendar properties
    destroy: Delete a calendar
    """

    permission_classes = [IsAuthenticated]
    serializer_class = serializers.CalendarSerializer

    def get_queryset(self):
        """Return calendars owned by or shared with the current user."""
        user = self.request.user
        owned = models.Calendar.objects.filter(owner=user)
        shared_ids = models.CalendarShare.objects.filter(shared_with=user).values_list(
            "calendar_id", flat=True
        )
        shared = models.Calendar.objects.filter(id__in=shared_ids)
        return owned.union(shared).order_by("-is_default", "name")

    def get_serializer_class(self):
        if self.action == "create":
            return serializers.CalendarCreateSerializer
        return serializers.CalendarSerializer

    def perform_create(self, serializer):
        """Create a new calendar via CalendarService."""
        service = CalendarService()
        calendar = service.create_calendar(
            user=self.request.user,
            name=serializer.validated_data["name"],
            color=serializer.validated_data.get("color", "#3174ad"),
        )
        # Update the serializer instance with the created calendar
        serializer.instance = calendar

    def perform_destroy(self, instance):
        """Delete calendar. Prevent deletion of default calendar."""
        if instance.is_default:
            raise ValueError("Cannot delete the default calendar.")
        if instance.owner != self.request.user:
            raise PermissionError("You can only delete your own calendars.")
        instance.delete()

    @action(detail=True, methods=["patch"])
    def toggle_visibility(self, request, pk=None):
        """Toggle calendar visibility."""
        calendar = self.get_object()

        # Check if it's a shared calendar
        share = models.CalendarShare.objects.filter(
            calendar=calendar, shared_with=request.user
        ).first()

        if share:
            share.is_visible = not share.is_visible
            share.save()
            is_visible = share.is_visible
        elif calendar.owner == request.user:
            calendar.is_visible = not calendar.is_visible
            calendar.save()
            is_visible = calendar.is_visible
        else:
            return drf_response.Response(
                {"error": "Permission denied"}, status=status.HTTP_403_FORBIDDEN
            )

        return drf_response.Response({"is_visible": is_visible})

    @action(
        detail=True,
        methods=["post"],
        serializer_class=serializers.CalendarShareSerializer,
    )
    def share(self, request, pk=None):
        """Share calendar with another user."""
        calendar = self.get_object()

        if calendar.owner != request.user:
            return drf_response.Response(
                {"error": "Only the owner can share this calendar"},
                status=status.HTTP_403_FORBIDDEN,
            )

        serializer = serializers.CalendarShareSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        email = serializer.validated_data["shared_with_email"]
        try:
            user_to_share = models.User.objects.get(email=email)
        except models.User.DoesNotExist:
            return drf_response.Response(
                {"error": "User not found"}, status=status.HTTP_404_NOT_FOUND
            )

        share, created = models.CalendarShare.objects.get_or_create(
            calendar=calendar,
            shared_with=user_to_share,
            defaults={
                "permission": serializer.validated_data.get("permission", "read")
            },
        )

        if not created:
            share.permission = serializer.validated_data.get(
                "permission", share.permission
            )
            share.save()

        return drf_response.Response(
            serializers.CalendarShareSerializer(share).data,
            status=status.HTTP_201_CREATED if created else status.HTTP_200_OK,
        )
