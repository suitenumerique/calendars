"""URL configuration for the core app."""

from django.conf import settings
from django.urls import include, path, re_path

from lasuite.oidc_login.urls import urlpatterns as oidc_urls
from rest_framework.routers import DefaultRouter

from core.api import viewsets
from core.api.viewsets_caldav import CalDAVProxyView
from core.external_api import viewsets as external_api_viewsets

# - Main endpoints
router = DefaultRouter()
router.register("users", viewsets.UserViewSet, basename="users")
router.register("calendars", viewsets.CalendarViewSet, basename="calendars")

urlpatterns = [
    path(
        f"api/{settings.API_VERSION}/",
        include(
            [
                *router.urls,
                *oidc_urls,
                # CalDAV proxy - root path (must come before catch-all to match /caldav exactly)
                path("caldav", CalDAVProxyView.as_view(), name="caldav-root"),
                path("caldav/", CalDAVProxyView.as_view(), name="caldav-root-slash"),
                # CalDAV proxy - catch all paths with content
                re_path(
                    r"^caldav/(?P<path>.+)$",
                    CalDAVProxyView.as_view(),
                    name="caldav-proxy",
                ),
            ]
        ),
    ),
    path(f"api/{settings.API_VERSION}/config/", viewsets.ConfigView.as_view()),
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
