"""URL configuration for the core app."""

from django.conf import settings
from django.urls import include, path, re_path

from lasuite.oidc_login.urls import urlpatterns as oidc_urls
from rest_framework.routers import DefaultRouter

from core.api import viewsets
from core.api.viewsets_caldav import CalDAVProxyView, CalDAVSchedulingCallbackView
from core.api.viewsets_channels import ChannelViewSet
from core.api.viewsets_ical import ICalExportView
from core.api.viewsets_rsvp import RSVPConfirmView, RSVPProcessView
from core.api.viewsets_task import TaskDetailView
from core.external_api import viewsets as external_api_viewsets

# - Main endpoints
router = DefaultRouter()
router.register("users", viewsets.UserViewSet, basename="users")
router.register("calendars", viewsets.CalendarViewSet, basename="calendars")
router.register("resources", viewsets.ResourceViewSet, basename="resources")
router.register("channels", ChannelViewSet, basename="channels")
router.register(
    "organization-settings",
    viewsets.OrganizationSettingsViewSet,
    basename="organization-settings",
)

urlpatterns = [
    path(
        f"api/{settings.API_VERSION}/",
        include(
            [
                *router.urls,
                *oidc_urls,
                # CalDAV scheduling callback endpoint
                path(
                    "caldav-scheduling-callback/",
                    CalDAVSchedulingCallbackView.as_view(),
                    name="caldav-scheduling-callback",
                ),
                # RSVP POST endpoint (state-changing, with DRF throttling)
                path(
                    "rsvp/",
                    RSVPProcessView.as_view(),
                    name="rsvp-process",
                ),
                # Task status polling endpoint
                path(
                    "tasks/<str:task_id>/",
                    TaskDetailView.as_view(),
                    name="task-detail",
                ),
            ]
        ),
    ),
    path(f"api/{settings.API_VERSION}/config/", viewsets.ConfigView.as_view()),
    # CalDAV proxy - top-level stable path (not versioned)
    path("caldav", CalDAVProxyView.as_view(), name="caldav-root"),
    path("caldav/", CalDAVProxyView.as_view(), name="caldav-root-slash"),
    re_path(
        r"^caldav/(?P<path>.+)$",
        CalDAVProxyView.as_view(),
        name="caldav-proxy",
    ),
    # Public iCal export endpoint (no authentication required)
    # base64url channel ID for lookup, base64url token for auth, filename cosmetic
    re_path(
        r"^ical/(?P<short_id>[A-Za-z0-9_-]+)/(?P<token>[A-Za-z0-9_-]+)/[^/]+\.ics$",
        ICalExportView.as_view(),
        name="ical-export",
    ),
    # RSVP GET endpoint (renders auto-submitting confirmation page)
    # Signed token in query string acts as authentication
    path("rsvp/", RSVPConfirmView.as_view(), name="rsvp"),
]


if settings.OIDC_RESOURCE_SERVER_ENABLED:
    # - Resource server routes
    external_api_router = DefaultRouter()

    users_access_config = settings.EXTERNAL_API.get("users", {})
    if users_access_config.get("enabled", False):
        external_api_router.register(
            "users",
            external_api_viewsets.ResourceServerUserViewSet,
            basename="resource_server_users",
        )

    external_api_urls = [*external_api_router.urls]

    if external_api_urls:
        urlpatterns.append(
            path(
                f"external_api/{settings.API_VERSION}/",
                include(external_api_urls),
            )
        )
