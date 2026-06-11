# Django calendars

# ---- base image to inherit from ----
FROM python:3.13.9-alpine AS base

# Upgrade pip to its latest release to speed up dependencies installation
# We must do taht to avoid having an outdated pip version with security issues
RUN python -m pip install --upgrade pip setuptools

# Upgrade system packages to install security updates
RUN apk update && \
  apk upgrade && \
  apk add git

# ---- Back-end builder image ----
FROM base AS back-builder

ENV UV_COMPILE_BYTECODE=1 
ENV UV_LINK_MODE=copy

# Disable Python downloads, because we want to use the system interpreter
# across both images. If using a managed Python version, it needs to be
# copied from the build image into the final image; 
ENV UV_PYTHON_DOWNLOADS=0

# install uv
COPY --from=ghcr.io/astral-sh/uv:0.9.10 /uv /uvx /bin/

WORKDIR /app


RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    uv sync --locked --no-install-project --no-dev
COPY . /app
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-dev

# ---- static link collector ----
FROM base AS link-collector
ARG CALENDARS_STATIC_ROOT=/data/static

# Install pango & rdfind
RUN apk add \
  pango \
  rdfind

WORKDIR /app

# Copy the application from the builder
COPY --from=back-builder /app /app

ENV PATH="/app/.venv/bin:$PATH"


# collectstatic
RUN DJANGO_CONFIGURATION=Build \
    python manage.py collectstatic --noinput

# Replace duplicated file by a symlink to decrease the overall size of the
# final image
RUN rdfind -makesymlinks true -followsymlinks true -makeresultsfile false ${CALENDARS_STATIC_ROOT}

# ---- Core application image ----
FROM base AS core

ENV PYTHONUNBUFFERED=1

# Install required system libs
RUN apk add \
  cairo \
  file \
  font-noto \
  font-noto-emoji \
  gettext \
  gdk-pixbuf \
  libffi-dev \
  pandoc \
  pango \
  shared-mime-info

RUN wget https://svn.apache.org/repos/asf/httpd/httpd/trunk/docs/conf/mime.types -O /etc/mime.types

# Give the "root" group the same permissions as the "root" user on /etc/passwd
# to allow a user belonging to the root group to add new users; typically the
# docker user (see entrypoint).
RUN chmod g=u /etc/passwd

# Copy the application from the builder
COPY --from=back-builder /app /app

WORKDIR /app

ENV PATH="/app/.venv/bin:$PATH"



# We wrap commands run in this container by the following entrypoint that
# creates a user on-the-fly with the container user ID (see USER) and root group
# ID.
ENTRYPOINT [ "/app/entrypoint" ]

# ---- Development image ----
FROM core AS backend-development

# Switch back to the root user to install development dependencies
USER root:root

# Install psql
RUN apk add postgresql-client

# Install uv for development dependencies
COPY --from=ghcr.io/astral-sh/uv:0.9.10 /uv /uvx /bin/

# Install development dependencies (ensure venv is created and used)
RUN uv sync --all-extras --locked

# Ensure venv is accessible and PATH is set
ENV PATH="/app/.venv/bin:$PATH"
ENV VIRTUAL_ENV="/app/.venv"

# Restore the un-privileged user running the application
ARG DOCKER_USER
USER ${DOCKER_USER}

# Target database host (e.g. database engine following docker compose services
# name) & port
ENV DB_HOST=postgresql \
    DB_PORT=5432

# Run django development server
CMD ["python", "manage.py", "runserver", "0.0.0.0:8000"]

# ---- Production image ----
FROM core AS backend-production

ARG CALENDARS_STATIC_ROOT=/data/static

# Remove git, we don't need it in the production image
RUN apk del git

# Un-privileged user running the application
ARG DOCKER_USER
USER ${DOCKER_USER}

# Copy statics
COPY --from=link-collector ${CALENDARS_STATIC_ROOT} ${CALENDARS_STATIC_ROOT}

# Bundle the shared translations file. It lives in the frontend source tree
# (src/frontend/src/features/i18n/translations.json), outside this image's
# build context, so it is supplied as a buildx named build context "i18n"
# by the release workflow (.github/workflows/calendars-ghcr.yml). Without
# it the calendar email/translation service has no file to load and every
# invitation / update / reply email fails with a 500. It is baked under /app
# (image-owned, never a mounted volume) rather than /data (the static/volume
# root) so a runtime volume mount can't shadow it.
#
# Only the production stage takes this COPY: the dev image targets
# backend-development (which never builds this stage) and gets the file via
# a directory bind mount in compose.yaml instead, so local builds don't need
# the "i18n" context.
COPY --from=i18n translations.json /app/translations.json
ENV TRANSLATIONS_JSON_PATH=/app/translations.json

# The default command runs gunicorn WSGI server in calendars' main module
CMD ["gunicorn", "-c", "/app/gunicorn.conf.py", "calendars.wsgi:application"]
