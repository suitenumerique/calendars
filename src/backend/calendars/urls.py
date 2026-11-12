"""URL configuration for the calendars project"""

from logging import getLogger

from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.contrib.staticfiles.urls import staticfiles_urlpatterns
from django.db import connection
from django.db.utils import OperationalError
from django.http import HttpResponse
from django.urls import include, path, re_path

from drf_spectacular.views import (
    SpectacularJSONAPIView,
    SpectacularRedocView,
    SpectacularSwaggerView,
)

from core.api.viewsets_caldav import CalDAVDiscoveryView

logger = getLogger(__name__)


def heartbeat(request):
    """Healthcheck endpoint to verify that the application is running and DB is reachable."""
    try:
        connection.ensure_connection()
    except OperationalError as e:
        logger.error("Database error: %s", e)
        return HttpResponse("DB Unavailable", status=500)
    return HttpResponse("OK")


urlpatterns = [
    path("admin/", admin.site.urls),
    # CalDAV discovery - must be at root level per RFC 6764
    path(".well-known/caldav", CalDAVDiscoveryView.as_view(), name="caldav-discovery"),
    path("__heartbeat__/", heartbeat, name="healthcheck"),
    path("", include("core.urls")),
]

if settings.DEBUG:
    from debug_toolbar.toolbar import debug_toolbar_urls

    urlpatterns = (
        urlpatterns
        + staticfiles_urlpatterns()
        + static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
        + debug_toolbar_urls()
    )

if settings.LOAD_E2E_URLS:
    urlpatterns += [path("", include("e2e.urls"))]


if settings.USE_SWAGGER or settings.DEBUG:
    urlpatterns += [
        path(
            f"api/{settings.API_VERSION}/swagger.json",
            SpectacularJSONAPIView.as_view(
                api_version=settings.API_VERSION,
                urlconf="core.urls",
            ),
            name="client-api-schema",
        ),
        path(
            f"api/{settings.API_VERSION}/swagger/",
            SpectacularSwaggerView.as_view(url_name="client-api-schema"),
            name="swagger-ui-schema",
        ),
        re_path(
            f"api/{settings.API_VERSION}/redoc/",
            SpectacularRedocView.as_view(url_name="client-api-schema"),
            name="redoc-schema",
        ),
    ]
