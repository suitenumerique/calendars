# When building arm64, CI passes FRONTEND_IMAGE=<amd64-tag> so BuildKit
# reuses the already-built static output and skips the slow Node build
# under QEMU.  For local / amd64 builds the default is used.
ARG FRONTEND_IMAGE=frontend-build-output

FROM node:24-alpine AS frontend-deps

WORKDIR /home/frontend/

COPY ./package.json ./package.json
COPY ./package-lock.json ./package-lock.json
COPY ./apps/calendars/package.json ./apps/calendars/package.json

RUN npm ci

COPY .dockerignore ./.dockerignore
# COPY ./.prettierrc.js ./.prettierrc.js
#COPY ./packages/eslint-config-calendars ./packages/eslint-config-calendars

COPY ./apps/calendars ./apps/calendars

# Build open-calendar package

WORKDIR /home/frontend

# Make the image and any anonymous volumes derived from it writable by
# any host user whose group ID is `node` (1000). Compose runs the
# container as `${DOCKER_USER:-1000}` which resolves to the host
# uid:gid — on macOS that's typically 501:20 / 501:1000, on Linux often
# 1000:1000. Owning everything by `node:node` plus `g+w` lets npm
# rename/rewrite packages from either case, so `make install-front`
# Just Works without a root-owned anonymous-volume fight.
#
# Also pre-create the npm cache + log directories under HOME so npm
# doesn't try to write to `/.npm/_logs` (which it can't, as a non-root
# user with no $HOME).
RUN mkdir -p /home/frontend/.npm \
 && chown -R node:node /home/frontend \
 && chmod -R g+w /home/frontend
ENV HOME=/home/frontend
ENV NPM_CONFIG_CACHE=/home/frontend/.npm

### ---- Front-end builder image ----
FROM frontend-deps AS calendars

WORKDIR /home/frontend/apps/calendars

FROM frontend-deps AS calendars-dev

WORKDIR /home/frontend

EXPOSE 3000

RUN cd apps/calendars && npm run build-theme

# Build open-calendar package if dist doesn't exist, then start dev server
CMD ["/bin/sh", "-c", "cd /home/frontend/apps/calendars && npm run dev"]

# Tilt will rebuild calendars target so, we dissociate calendars and calendars-builder
# to avoid rebuilding the app at every changes.
FROM calendars AS calendars-builder

WORKDIR /home/frontend/apps/calendars

ARG API_ORIGIN
ENV NEXT_PUBLIC_API_ORIGIN=${API_ORIGIN}

RUN npm run build

# Scratch stage that normalises the build output path.
# When FRONTEND_IMAGE keeps its default value, BuildKit uses this stage.
FROM scratch AS frontend-build-output
COPY --from=calendars-builder /home/frontend/apps/calendars/out /srv

# When FRONTEND_IMAGE is overridden to an external image tag, BuildKit
# pulls that image instead and skips every stage above.
FROM ${FRONTEND_IMAGE} AS frontend-source

# ---- Front-end image ----
FROM caddy:2-alpine AS frontend-production

# Upgrade system packages to install security updates
RUN apk update && \
  apk upgrade && \
  rm -rf /var/cache/apk/*

COPY --from=frontend-source /srv /srv

COPY ./Caddyfile /etc/caddy/Caddyfile

CMD ["caddy", "run", "--config", "/etc/caddy/Caddyfile", "--adapter", "caddyfile"]
