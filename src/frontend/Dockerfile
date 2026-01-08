FROM node:22-alpine AS frontend-deps

WORKDIR /home/frontend/

COPY ./package.json ./package.json
COPY ./yarn.lock ./yarn.lock
COPY ./apps/calendars/package.json ./apps/calendars/package.json
COPY ./packages/open-calendar/package.json ./packages/open-calendar/package.json

RUN yarn install --frozen-lockfile

COPY .dockerignore ./.dockerignore
# COPY ./.prettierrc.js ./.prettierrc.js
#COPY ./packages/eslint-config-calendars ./packages/eslint-config-calendars
COPY ./packages/open-calendar ./packages/open-calendar
COPY ./apps/calendars ./apps/calendars

# Build open-calendar package
WORKDIR /home/frontend/packages/open-calendar
RUN yarn build
WORKDIR /home/frontend

### ---- Front-end builder image ----
FROM frontend-deps AS calendars

WORKDIR /home/frontend/apps/calendars

FROM frontend-deps AS calendars-dev

WORKDIR /home/frontend/apps/calendars

EXPOSE 3000

RUN yarn build-theme

# Build open-calendar package if dist doesn't exist, then start dev server
CMD ["/bin/sh", "-c", "cd /home/frontend/packages/open-calendar && ([ -d dist ] || yarn build) && cd /home/frontend/apps/calendars && yarn dev"]

# Tilt will rebuild calendars target so, we dissociate calendars and calendars-builder 
# to avoid rebuilding the app at every changes.
FROM calendars AS calendars-builder

WORKDIR /home/frontend/apps/calendars

ARG API_ORIGIN
ENV NEXT_PUBLIC_API_ORIGIN=${API_ORIGIN}

RUN yarn build

# ---- Front-end image ----
FROM nginxinc/nginx-unprivileged:alpine3.22 AS frontend-production

# Upgrade system packages to install security updates
USER root
RUN apk update && \
  apk upgrade && \
  rm -rf /var/cache/apk/*

# Un-privileged user running the application
ARG DOCKER_USER
USER ${DOCKER_USER}

COPY --from=calendars-builder \
    /home/frontend/apps/calendars/out \
    /usr/share/nginx/html

COPY ./apps/calendars/conf/default.conf /etc/nginx/conf.d
COPY ./docker/files/usr/local/bin/entrypoint /usr/local/bin/entrypoint

ENTRYPOINT [ "/usr/local/bin/entrypoint" ]

CMD ["nginx", "-g", "daemon off;"]
