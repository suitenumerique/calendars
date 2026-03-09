# Note to developers:
#
# While editing this file, please respect the following statements:
#
# 1. Every variable should be defined in the ad hoc VARIABLES section with a
#    relevant subsection
# 2. Every new rule should be defined in the ad hoc RULES section with a
#    relevant subsection depending on the targeted service
# 3. Rules should be sorted alphabetically within their section
# 4. When a rule has multiple dependencies, you should:
#    - duplicate the rule name to add the help string (if required)
#    - write one dependency per line to increase readability and diffs
# 5. .PHONY rule statement should be written after the corresponding rule
# ==============================================================================
# VARIABLES

BOLD := \033[1m
RESET := \033[0m
GREEN := \033[1;32m
BLUE := \033[1;34m

# -- Docker
# Get the current user ID to use for docker run and docker exec commands
DOCKER_UID          = $(shell id -u)
DOCKER_GID          = $(shell id -g)
DOCKER_USER         = $(DOCKER_UID):$(DOCKER_GID)
COMPOSE             = DOCKER_USER=$(DOCKER_USER) docker compose
COMPOSE_EXEC        = $(COMPOSE) exec
COMPOSE_EXEC_APP    = $(COMPOSE_EXEC) backend-dev
COMPOSE_RUN         = $(COMPOSE) run --rm
COMPOSE_RUN_APP     = $(COMPOSE_RUN) backend-dev
COMPOSE_RUN_APP_NO_DEPS = $(COMPOSE_RUN) --no-deps backend-dev

# -- Backend
MANAGE              = $(COMPOSE_RUN_APP) python manage.py
MANAGE_EXEC         = $(COMPOSE_EXEC_APP) python manage.py
PSQL_E2E            = ./bin/postgres_e2e

# ==============================================================================
# RULES

default: help

data/media:
	@mkdir -p data/media

data/static:
	@mkdir -p data/static

# -- Project

create-env-files: ## Create empty .local env files for local development
create-env-files: \
	env.d/development/postgresql.local \
	env.d/development/keycloak.local \
	env.d/development/backend.local \
	env.d/development/frontend.local \
	env.d/development/caldav.local
.PHONY: create-env-files

env.d/development/%.local:
	@echo "# Local development overrides for $(notdir $*)" > $@
	@echo "# Add your local-specific environment variables below:" >> $@
	@echo "# Example: DJANGO_DEBUG=True" >> $@
	@echo "" >> $@

create-docker-network: ## create the docker network if it doesn't exist
	@docker network create lasuite-network || true
.PHONY: create-docker-network

bootstrap: ## Prepare the project for local development
bootstrap: \
	data/media \
	data/static \
	create-env-files \
	build \
	create-docker-network \
	migrate \
	migrate-caldav \
	start
.PHONY: bootstrap

update: ## Update the project with latest changes
	@$(MAKE) data/media
	@$(MAKE) data/static
	@$(MAKE) create-env-files
	@$(MAKE) build
	@$(MAKE) migrate
	@$(MAKE) migrate-caldav
	@$(MAKE) install-frozen-front
.PHONY: update

# -- Docker/compose

build: cache ?=  # --no-cache
build: ## build the project containers
	@$(COMPOSE) build $(cache)
.PHONY: build

down: ## stop and remove containers, networks, images, and volumes
	@$(COMPOSE) down
	rm -rf data/postgresql.*
.PHONY: down

logs: ## display all services logs (follow mode)
	@$(COMPOSE) logs -f
.PHONY: logs

start: ## start all development services
	@$(COMPOSE) up --force-recreate -d worker-dev frontend-dev
.PHONY: start

start-back: ## start backend services only (for local frontend development)
	@$(COMPOSE) up --force-recreate -d worker-dev
.PHONY: start-back

status: ## an alias for "docker compose ps"
	@$(COMPOSE) ps
.PHONY: status

stop: ## stop all development services
	@$(COMPOSE) stop
.PHONY: stop

restart: ## restart all development services
restart: \
	stop \
	start
.PHONY: restart

migrate-caldav: ## Initialize CalDAV server database schema
	@echo "$(BOLD)Initializing CalDAV server database schema...$(RESET)"
	@$(COMPOSE) run --rm caldav /usr/local/bin/init-database.sh
	@echo "$(GREEN)CalDAV server initialized$(RESET)"
.PHONY: migrate-caldav

# -- Linters

lint: ## run all linters
lint: \
	lint-back \
	lint-front
.PHONY: lint

lint-back: ## run back-end linters (with auto-fix)
lint-back: \
	format-back \
	check-back \
	analyze-back
.PHONY: lint-back

format-back: ## format back-end python sources with ruff
	@$(COMPOSE_RUN_APP_NO_DEPS) ruff format .
.PHONY: format-back

check-back: ## check back-end python sources with ruff
	@$(COMPOSE_RUN_APP_NO_DEPS) ruff check . --fix
.PHONY: check-back

analyze-back: ## lint all back-end python sources with pylint
	@$(COMPOSE_RUN_APP_NO_DEPS) pylint .
.PHONY: analyze-back

lint-front: ## run the frontend linter
	@$(COMPOSE) run --rm frontend-dev sh -c "cd apps/calendars && npm run lint"
.PHONY: lint-front

typecheck-front: ## run the frontend type checker
	@$(COMPOSE) run --rm frontend-dev sh -c "cd apps/calendars && npx tsc --noEmit"
.PHONY: typecheck-front

# -- Tests

test: ## run all tests
test: \
	test-back-parallel \
	test-front
.PHONY: test

test-back: ## run back-end tests
	@echo "$(BOLD)Running tests...$(RESET)"
	@args="$(filter-out $@,$(MAKECMDGOALS))" && \
	bin/pytest $${args:-${1}}
.PHONY: test-back

test-back-parallel: ## run all back-end tests in parallel
	@args="$(filter-out $@,$(MAKECMDGOALS))" && \
	bin/pytest -n auto $${args:-${1}}
.PHONY: test-back-parallel

test-front: ## run the frontend tests
	@args="$(filter-out $@,$(MAKECMDGOALS))" && \
	$(COMPOSE) run --rm frontend-dev sh -c "cd apps/calendars && npm test -- $${args:-${1}}"
.PHONY: test-front

# -- E2E Tests

bootstrap-e2e: ## bootstrap the backend for e2e tests, without frontend
bootstrap-e2e: \
	data/media \
	data/static \
	create-env-files \
	build \
	create-docker-network \
	start-back-e2e
.PHONY: bootstrap-e2e

clear-db-e2e: ## quickly clears the database for e2e tests
	$(PSQL_E2E) -c "$$(cat bin/clear_db_e2e.sql)"
.PHONY: clear-db-e2e

start-back-e2e: ## start the backend for e2e tests
	@$(MAKE) stop
	rm -rf data/postgresql.e2e
	@ENV_OVERRIDE=e2e $(MAKE) start-back
	@ENV_OVERRIDE=e2e $(MAKE) migrate
.PHONY: start-back-e2e

test-e2e: ## run the e2e tests, example: make test-e2e -- --project chromium --headed
	@$(MAKE) start-back-e2e
	@args="$(filter-out $@,$(MAKECMDGOALS))" && \
	cd src/frontend/apps/e2e && npm test $${args:-${1}}
.PHONY: test-e2e

# -- Backend

makemigrations: ## run django makemigrations
	@echo "$(BOLD)Running makemigrations$(RESET)"
	@$(COMPOSE) up -d postgresql
	@$(MANAGE) makemigrations
.PHONY: makemigrations

migrate: ## run django migrations
	@echo "$(BOLD)Running migrations$(RESET)"
	@$(COMPOSE) up -d postgresql
	@$(MANAGE) migrate
.PHONY: migrate

superuser: ## Create an admin superuser with password "admin"
	@echo "$(BOLD)Creating a Django superuser$(RESET)"
	@$(MANAGE) createsuperuser --email admin@example.com --password admin
.PHONY: superuser

shell-back: ## open a shell in the backend container
	@$(COMPOSE) run --rm --build backend-dev /bin/sh
.PHONY: shell-back

exec-back: ## open a shell in the running backend-dev container
	@$(COMPOSE) exec backend-dev /bin/sh
.PHONY: exec-back

shell-back-django: ## connect to django shell
	@$(MANAGE) shell
.PHONY: shell-back-django

back-lock: ## regenerate the uv.lock file
	@echo "$(BOLD)Regenerating uv.lock$(RESET)"
	@docker run --rm -v $(PWD)/src/backend:/app -w /app ghcr.io/astral-sh/uv:python3.13-alpine uv lock
.PHONY: back-lock

# -- Database

shell-db: ## connect to database shell
	@$(COMPOSE) exec backend-dev python manage.py dbshell
.PHONY: shell-db

reset-db: FLUSH_ARGS ?=
reset-db: ## flush database
	@echo "$(BOLD)Flush database$(RESET)"
	@$(MANAGE) flush $(FLUSH_ARGS)
.PHONY: reset-db

demo: ## flush db then create a demo
	@$(MAKE) reset-db
	@$(MANAGE) create_demo
.PHONY: demo

# -- Frontend

install-front: ## install the frontend dependencies
	@$(COMPOSE) run --rm frontend-dev sh -c "npm install"
.PHONY: install-front

install-frozen-front: ## install frontend dependencies from lockfile
	@echo "Installing frontend dependencies..."
	@$(COMPOSE) run --rm frontend-dev sh -c "npm ci"
.PHONY: install-frozen-front

shell-front: ## open a shell in the frontend container
	@$(COMPOSE) run --rm frontend-dev /bin/sh
.PHONY: shell-front

# -- Misc

clean: ## restore repository state as it was freshly cloned
	git clean -idx
.PHONY: clean

clean-media: ## remove all media files
	rm -rf data/media/*
.PHONY: clean-media

help:
	@echo "$(BOLD)calendar Makefile"
	@echo "Please use 'make $(BOLD)target$(RESET)' where $(BOLD)target$(RESET) is one of:"
	@grep -E '^[a-zA-Z0-9_-]+:.*?## .*$$' $(firstword $(MAKEFILE_LIST)) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "$(GREEN)%-30s$(RESET) %s\n", $$1, $$2}'
.PHONY: help
