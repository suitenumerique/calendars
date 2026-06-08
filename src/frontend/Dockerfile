# When building arm64, CI passes FRONTEND_IMAGE=<amd64-tag> so BuildKit
# reuses the already-built static output and skips the slow Node build
# under QEMU.  For local / amd64 builds the default is used.
ARG FRONTEND_IMAGE=frontend-build-output

FROM node:24-alpine AS frontend-deps

# pnpm, provided by corepack (version pinned via package.json#packageManager).
RUN corepack enable
ENV COREPACK_ENABLE_DOWNLOAD_PROMPT=0
ENV HOME=/home/frontend

WORKDIR /home/frontend

# Install as the `node` user (uid/gid 1000), not root. Compose runs the
# container as `<host-uid>:1000`, and `umask 0002` makes every installed
# file group-writable — so the runtime user (which shares gid 1000) can
# rewrite node_modules (e.g. `make install-front`) WITHOUT a recursive
# `chown -R` / `chmod -R` over the whole tree. Owning the single workdir
# up front is enough; everything created below inherits node ownership.
RUN chown node:node /home/frontend
USER node

COPY --chown=node:node ./package.json ./pnpm-workspace.yaml ./pnpm-lock.yaml ./

# umask 0002 => files are born group-writable (gid 1000) => the runtime
# user can write, no post-install chown required. --frozen-lockfile keeps
# the image build reproducible (fails on package.json/lockfile drift
# instead of silently rewriting the lockfile).
RUN umask 0002 && pnpm install --frozen-lockfile

COPY --chown=node:node .dockerignore ./.dockerignore
COPY --chown=node:node . .

### ---- Front-end builder image ----
FROM frontend-deps AS calendars

WORKDIR /home/frontend

FROM frontend-deps AS calendars-dev

WORKDIR /home/frontend

EXPOSE 8930

RUN pnpm run build-theme

# Build open-calendar package if dist doesn't exist, then start dev server
CMD ["/bin/sh", "-c", "cd /home/frontend && pnpm run dev"]

# Tilt will rebuild calendars target so, we dissociate calendars and calendars-builder
# to avoid rebuilding the app at every changes.
FROM calendars AS calendars-builder

WORKDIR /home/frontend

ARG API_ORIGIN
ENV NEXT_PUBLIC_API_ORIGIN=${API_ORIGIN}

RUN pnpm run build

# Scratch stage that normalises the build output path.
# When FRONTEND_IMAGE keeps its default value, BuildKit uses this stage.
FROM scratch AS frontend-build-output
COPY --from=calendars-builder /home/frontend/dist /srv

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
