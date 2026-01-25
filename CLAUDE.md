<!-- OPENSPEC:START -->
# OpenSpec Instructions

These instructions are for AI assistants working in this project.

Always open `@/openspec/AGENTS.md` when the request:
- Mentions planning or proposals (words like proposal, spec, change, plan)
- Introduces new capabilities, breaking changes, architecture shifts, or big performance/security work
- Sounds ambiguous and you need the authoritative spec before coding

Use `@/openspec/AGENTS.md` to learn:
- How to create and apply change proposals
- Spec format and conventions
- Project structure and guidelines

Keep this managed block so 'openspec update' can refresh the instructions.

<!-- OPENSPEC:END -->

# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

La Suite Calendars is a modern calendar application for managing events and schedules.  It's a full-stack application with:
- **Backend**: Django 5 REST API with PostgreSQL
- **Frontend**: Next.js 15 with React 19
- **CalDAV Server**: SabreDAV (PHP-based) for calendar protocol support : https://sabre.io/dav/
- **Authentication**: Keycloak OIDC provider

In this project, you can create events, invite people to events, create calendars, and invite others to share and manage those calendars, allowing them to add and manage events as well. Every invitation sends an email with an ICS file attached; this also happens for event updates and cancellations.

## Common Commands

### Development Setup
```bash
make bootstrap          # Initial setup: builds containers, runs migrations, starts services
make run                # Start all services (backend + frontend containers)
make run-backend        # Start backend services only (for local frontend development)
make stop               # Stop all containers
make down               # Stop and remove containers, networks, volumes
```

### Backend Development
```bash
make test-back -- path/to/test.py::TestClass::test_method  # Run specific test
make test-back-parallel                                     # Run all tests in parallel
make lint                                                   # Run ruff + pylint
make migrate                                                # Run Django migrations
make makemigrations                                         # Create new migrations
make shell                                                  # Django shell
make dbshell                                                # PostgreSQL shell
```

### Frontend Development
```bash
make frontend-development-install   # Install frontend dependencies locally
make run-frontend-development       # Run frontend locally (after run-backend)
make frontend-lint                  # Run ESLint on frontend
cd src/frontend/apps/calendars && yarn test              # Run frontend tests
cd src/frontend/apps/calendars && yarn test:watch        # Watch mode
```

### E2E Tests
```bash
make run-tests-e2e                           # Run all e2e tests
make run-tests-e2e -- --project chromium --headed  # Run with specific browser
```

### Internationalization
```bash
make i18n-generate         # Generate translation files
make i18n-compile          # Compile translations
make crowdin-upload        # Upload sources to Crowdin
make crowdin-download      # Download translations from Crowdin
```

## Architecture

### Backend Structure (`src/backend/`)
- `calendars/` - Django project configuration, settings, Celery app
- `core/` - Main application code:
  - `api/` - DRF viewsets and serializers
  - `models.py` - Database models
  - `services/` - Business logic
  - `authentication/` - OIDC authentication
  - `tests/` - pytest test files

### Frontend Structure (`src/frontend/`)
Yarn workspaces monorepo:
- `apps/calendars/` - Main Next.js application
  - `src/features/` - Feature modules (calendar, auth, api, i18n, etc.)
  - `src/pages/` - Next.js pages
  - `src/hooks/` - Custom React hooks
- `apps/e2e/` - Playwright end-to-end tests

### CalDAV Server (`docker/sabredav/`)
PHP SabreDAV server providing CalDAV protocol support, running against the shared PostgreSQL database.

### Service Ports (Development)
- Frontend: http://localhost:8920
- Backend API: http://localhost:8921
- CalDAV: http://localhost:8922
- Keycloak: http://localhost:8925
- PostgreSQL: 8912
- Mailcatcher: http://localhost:1081

## Key Technologies

### Backend
- Django 5 with Django REST Framework
- Celery with Redis for background tasks
- pytest for testing (use `bin/pytest` wrapper)
- Ruff for linting/formatting (100 char line length for pylint compatibility)

### Frontend
- Next.js 15 with React 19
- @tanstack/react-query for data fetching
- tsdav/ical.js/tsics for CalDAV client integration : https://tsdav.vercel.app/docs/intro / https://github.com/Neuvernetzung/ts-ics
- @gouvfr-lasuite/cunningham-react for UI components : https://github.com/suitenumerique/cunningham
- Jest for unit tests
- Playwright for e2e tests

## Code Style

### Python
- Follow PEP 8 with 100 character line limit
- Use Django REST Framework viewsets for APIs
- Business logic in models and services, keep views thin
- Use `select_related`/`prefetch_related` for query optimization

### TypeScript/React
- Feature-based folder structure under `src/features/`
- Use React Query for server state management as possible, if it is not possible, don't worry. 
- Use the vercel-react-best-practices skill when you write a react code 
- Please, make many tiny files and separate components in differentes files
- Check for Lint and TypeScript errors before telling me that you have finished

### Git

- Maximum line length: 80 characters.
- Each commit must have a title and a description.
- The commit title should start with a Gitmoji, then the area in parentheses
  (e.g. back, front, docs), then your chosen title.

# Workflow
- Be sure to typecheck when you're done making a series of code changes
- Prefer running single tests, and not the whole test suite, for performance