# When building arm64, CI passes FRONTEND_IMAGE=<amd64-tag> so BuildKit
# reuses the already-built static output and skips the slow Node build
# under QEMU.  For local / amd64 builds the default is used.
ARG FRONTEND_IMAGE=frontend-build-output

FROM node:24-alpine AS frontend-deps

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

COPY --chown=node:node ./package.json ./package-lock.json ./.npmrc ./

# umask 0002 => files are born group-writable (gid 1000) => the runtime
# user can write, no post-install chown required. `npm ci` keeps the
# image build reproducible (fails on package.json/lockfile drift
# instead of silently rewriting the lockfile).
RUN umask 0002 && npm ci

COPY --chown=node:node .dockerignore ./.dockerignore
COPY --chown=node:node . .

### ---- Front-end builder image ----
FROM frontend-deps AS calendars

WORKDIR /home/frontend

FROM frontend-deps AS calendars-dev

WORKDIR /home/frontend

EXPOSE 8930

RUN npm run build-theme

# Build open-calendar package if dist doesn't exist, then start dev server
CMD ["/bin/sh", "-c", "cd /home/frontend && npm run dev"]

# Tilt will rebuild calendars target so, we dissociate calendars and calendars-builder
# to avoid rebuilding the app at every changes.
FROM calendars AS calendars-builder

WORKDIR /home/frontend

ARG API_ORIGIN
ENV NEXT_PUBLIC_API_ORIGIN=${API_ORIGIN}

RUN npm run build

# Scratch stage that normalises the build output path.
# When FRONTEND_IMAGE keeps its default value, BuildKit uses this stage.
FROM scratch AS frontend-build-output
COPY --from=calendars-builder /home/frontend/dist /srv

# When FRONTEND_IMAGE is overridden to an external image tag, BuildKit
# pulls that image instead and skips every stage above.
FROM ${FRONTEND_IMAGE} AS frontend-source

# ---- Runtime tools (checksummed downloads for the distroless image) ----
FROM alpine:3.21@sha256:48b0309ca019d89d40f670aa1bc06e426dc0931948452e8491e3d65087abc07d AS tools-download
ARG TARGETARCH

ARG CADDY_VERSION=2.11.4
# When upgrading, run
# for arch in amd64 arm64; do printf "CADDY_SHA256_%s=%s\n" "$(echo $arch | tr a-z A-Z)" "$(wget -qO- "https://github.com/caddyserver/caddy/releases/download/v${CADDY_VERSION}/caddy_${CADDY_VERSION}_linux_${arch}.tar.gz" | sha256sum | cut -d' ' -f1)"; done
# and update checksums accordingly
ARG CADDY_SHA256_AMD64=527fbf917c39189a1e3b31d34fa955601680b2d5c8055d2a87b8b9588dec7bb9
ARG CADDY_SHA256_ARM64=52d42ae12b3462097e9868da6dfed3c9648ae12edd3b3638102312af84cb6904
RUN wget -qO /tmp/caddy.tar.gz "https://github.com/caddyserver/caddy/releases/download/v${CADDY_VERSION}/caddy_${CADDY_VERSION}_linux_${TARGETARCH}.tar.gz" \
    && case "${TARGETARCH}" in \
         amd64) echo "${CADDY_SHA256_AMD64}  /tmp/caddy.tar.gz" | sha256sum -c - ;; \
         arm64) echo "${CADDY_SHA256_ARM64}  /tmp/caddy.tar.gz" | sha256sum -c - ;; \
         *) echo "Unsupported architecture: ${TARGETARCH}" && exit 1 ;; \
       esac \
    && tar -xzf /tmp/caddy.tar.gz caddy \
    && mv caddy /usr/bin/caddy \
    && rm /tmp/caddy.tar.gz

ARG LPROBE_VERSION=v0.2.0
# When upgrading, run
# for arch in amd64 arm64; do printf "LPROBE_SHA256_%s=%s\n" "$(echo $arch | tr a-z A-Z)" "$(wget -qO- "https://github.com/fivexl/lprobe/releases/download/${LPROBE_VERSION}/lprobe-linux-${arch}" | sha256sum | cut -d' ' -f1)"; done
# and update checksums accordingly
ARG LPROBE_SHA256_AMD64=8b55ddb15c2d8c5e1773c73c1413b26c7041e5836dabdbcef5f806ba6b9d17a2
ARG LPROBE_SHA256_ARM64=3f31eee19167f23dc64c645021b75306956da245e5b9763c90abd12797d0a72a
RUN wget -qO /usr/bin/lprobe "https://github.com/fivexl/lprobe/releases/download/${LPROBE_VERSION}/lprobe-linux-${TARGETARCH}" \
    && case "${TARGETARCH}" in \
         amd64) echo "${LPROBE_SHA256_AMD64}  /usr/bin/lprobe" | sha256sum -c - ;; \
         arm64) echo "${LPROBE_SHA256_ARM64}  /usr/bin/lprobe" | sha256sum -c - ;; \
         *) echo "Unsupported architecture: ${TARGETARCH}" && exit 1 ;; \
       esac \
    && chmod +x /usr/bin/lprobe

# ---- Front-end image ----
FROM gcr.io/distroless/static-debian13:nonroot AS frontend-production

COPY --from=tools-download /usr/bin/caddy /usr/bin/caddy
COPY --from=tools-download /usr/bin/lprobe /usr/bin/lprobe
COPY --from=frontend-source /srv /srv
COPY ./Caddyfile /etc/caddy/Caddyfile

ENTRYPOINT ["caddy", "run", "--config", "/etc/caddy/Caddyfile", "--adapter", "caddyfile"]

# Port is hardcoded below because distroless has no shell to expand variables;
# it must match the :8080 site address in the Caddyfile.
HEALTHCHECK --interval=30s --timeout=3s --start-period=10s \
  CMD ["/usr/bin/lprobe", "-mode=http", "-port=8080", "-endpoint=/__lbheartbeat__"]
