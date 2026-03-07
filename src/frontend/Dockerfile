FROM node:22-alpine AS frontend-deps

WORKDIR /home/frontend/

COPY ./package.json ./package.json
COPY ./pnpm-lock.yaml ./pnpm-lock.yaml
COPY ./pnpm-workspace.yaml ./pnpm-workspace.yaml
COPY ./apps/calendars/package.json ./apps/calendars/package.json
COPY ./packages/ts-ics/package.json ./packages/ts-ics/package.json

RUN corepack enable && corepack prepare pnpm@9.15.9 --activate
RUN pnpm install --frozen-lockfile

COPY .dockerignore ./.dockerignore
# COPY ./.prettierrc.js ./.prettierrc.js
#COPY ./packages/eslint-config-calendars ./packages/eslint-config-calendars

COPY ./apps/calendars ./apps/calendars
COPY ./packages/ts-ics ./packages/ts-ics

# Build open-calendar package

WORKDIR /home/frontend

### ---- Front-end builder image ----
FROM frontend-deps AS calendars

WORKDIR /home/frontend/apps/calendars

FROM frontend-deps AS calendars-dev

WORKDIR /home/frontend

EXPOSE 3000

RUN cd apps/calendars && pnpm run build-theme

# Build open-calendar package if dist doesn't exist, then start dev server
CMD ["/bin/sh", "-c", "cd /home/frontend/apps/calendars && pnpm dev"]

# Tilt will rebuild calendars target so, we dissociate calendars and calendars-builder
# to avoid rebuilding the app at every changes.
FROM calendars AS calendars-builder

WORKDIR /home/frontend/apps/calendars

ARG API_ORIGIN
ENV NEXT_PUBLIC_API_ORIGIN=${API_ORIGIN}

RUN pnpm build

# ---- Front-end image ----
FROM caddy:2-alpine AS frontend-production

# Upgrade system packages to install security updates
RUN apk update && \
  apk upgrade && \
  rm -rf /var/cache/apk/*

COPY --from=calendars-builder \
  /home/frontend/apps/calendars/out \
  /srv

COPY ./Caddyfile /etc/caddy/Caddyfile

CMD ["caddy", "run", "--config", "/etc/caddy/Caddyfile", "--adapter", "caddyfile"]
