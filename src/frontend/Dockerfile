FROM node:22-alpine AS frontend-deps

WORKDIR /home/frontend/

COPY ./package.json ./package.json
COPY ./yarn.lock ./yarn.lock
COPY ./apps/calendars/package.json ./apps/calendars/package.json


RUN yarn install --frozen-lockfile

COPY .dockerignore ./.dockerignore
# COPY ./.prettierrc.js ./.prettierrc.js
#COPY ./packages/eslint-config-calendars ./packages/eslint-config-calendars

COPY ./apps/calendars ./apps/calendars

# Build open-calendar package

WORKDIR /home/frontend

### ---- Front-end builder image ----
FROM frontend-deps AS calendars

WORKDIR /home/frontend/apps/calendars

FROM frontend-deps AS calendars-dev

WORKDIR /home/frontend/apps/calendars

EXPOSE 3000

RUN yarn build-theme

# Build open-calendar package if dist doesn't exist, then start dev server
CMD ["/bin/sh", "-c", "cd /home/frontend/apps/calendars && yarn dev"]

# Tilt will rebuild calendars target so, we dissociate calendars and calendars-builder 
# to avoid rebuilding the app at every changes.
FROM calendars AS calendars-builder

WORKDIR /home/frontend/apps/calendars

ARG API_ORIGIN
ENV NEXT_PUBLIC_API_ORIGIN=${API_ORIGIN}

RUN yarn build

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
