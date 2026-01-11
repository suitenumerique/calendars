# Calendar Application Architecture

## Overview

The Calendar application is a modern, self-hosted calendar solution that combines a Django REST API backend with a separate CalDAV server for standards-compliant calendar data storage and synchronization. This architecture provides both a modern web interface and full CalDAV protocol support for compatibility with standard calendar clients.

## System Architecture

```
┌─────────────────┐
│   Frontend      │
│   (Next.js)     │
└────────┬────────┘
         │
         │ HTTP/REST API + CalDAV Protocol
         │
┌────────▼─────────────────────────────────────┐
│         Django Backend                       │
│  ┌──────────────────────────────────────┐  │
│  │  REST API Endpoints                  │  │
│  │  - /api/v1.0/calendars               │  │
│  │  - /api/v1.0/users                   │  │
│  └──────────────────────────────────────┘  │
│  ┌──────────────────────────────────────┐  │
│  │  CalDAV Proxy                        │  │
│  │  - /api/v1.0/caldav/*               │  │
│  │  - /.well-known/caldav              │  │
│  └──────────────────────────────────────┘  │
│  ┌──────────────────────────────────────┐  │
│  │  Authentication (OIDC/Keycloak)      │  │
│  └──────────────────────────────────────┘  │
└────────┬───────────────────────────────────┘
         │
         │ HTTP/CalDAV Protocol
         │
┌────────▼─────────────────────────────────────┐
│         CalDAV Server                      │
│  (CalDAV Protocol Implementation)            │
│  - Calendar storage                          │
│  - Event storage (iCalendar format)          │
│  - CalDAV protocol handling                  │
└────────┬─────────────────────────────────────┘
         │
         │ PostgreSQL
         │
┌────────▼─────────────────────────────────────┐
│         PostgreSQL Database                  │
│  - Django models (users, calendars metadata) │
│  - CalDAV server schema (calendar data)      │
└──────────────────────────────────────────────┘
```

## Component Responsibilities

### Django Backend

The Django backend serves as the **orchestration layer** and **business logic engine** for the application.

**Primary Responsibilities:**
- **User Management & Authentication**: OIDC authentication via Keycloak, user profiles, sessions, authorization
- **Calendar Metadata Management**: Calendar creation/deletion, sharing, visibility settings, display preferences
- **REST API Layer**: Modern RESTful API for the web frontend (JSON, standard HTTP methods, versioned at `/api/v1.0/`)
- **CalDAV Proxy**: Proxies CalDAV requests to CalDAV server, handles authentication translation, URL routing, discovery endpoint
- **Business Logic**: Calendar sharing logic, permission checks, data validation, integration coordination

**Data Storage:**
- User accounts
- Calendar metadata (name, color, visibility, owner)
- Sharing relationships
- Application configuration

**Important**: Django does NOT store actual calendar events. Events are stored in the CalDAV server.

### CalDAV Server

The CalDAV server is a **standards-compliant CalDAV server** that handles all calendar data storage and protocol operations.

**Primary Responsibilities:**
- **Calendar Data Storage**: Stores actual calendar events in iCalendar format, manages calendar collections
- **CalDAV Protocol Implementation**: Full RFC 4791 implementation (PROPFIND, REPORT, MKCALENDAR, PUT, DELETE)
- **iCalendar Format Management**: Parses and generates iCalendar files, validates syntax, handles VEVENT/VTODO components
- **Database Schema**: Uses PostgreSQL with its own schema for calendar data

**Authentication Integration:**
- Uses Apache authentication backend which reads `REMOTE_USER` environment variable
- Django proxy sets `X-Forwarded-User` header, which the CalDAV server converts to `REMOTE_USER`
- All communication is via HTTP - no direct database access from Django

### Frontend (Next.js)

The frontend provides the user interface and interacts with both REST API and CalDAV protocol:
- Modern React-based UI
- Uses REST API for calendar metadata operations
- Uses CalDAV protocol directly for event operations
- Supports multiple languages and themes

## Why This Architecture?

### Design Decision: CalDAV Server Separation

The decision to use a separate CalDAV server rather than implementing CalDAV directly in Django was made for several reasons:

1. **Standards Compliance**: Using a mature, well-tested CalDAV server that fully implements RFC 4791. Implementing CalDAV from scratch would be error-prone and time-consuming.

2. **Protocol Complexity**: CalDAV is built on WebDAV, involving complex XML handling, property management, and collection hierarchies. A dedicated CalDAV server handles all of this complexity.

3. **Maintenance**: Using a proven, maintained CalDAV server reduces maintenance burden and ensures compatibility with various CalDAV clients.

4. **Focus**: Django backend can focus on business logic, user management, and REST API, while the CalDAV server handles calendar protocol operations.

5. **Shared database**: The CalDAV server stores its data into Postgres, which we use in all LaSuite projects.

6. **Clean separation**: All communication between Django and the CalDAV server is via HTTP, ensuring clean separation of concerns and no direct database access.

### Benefits

1. **Standards Compliance**
   - Full CalDAV protocol support enables compatibility with any CalDAV client (Apple Calendar, Thunderbird, etc.)
   - Users can sync calendars with external applications
   - Follows industry standards (RFC 4791)

2. **Separation of Concerns**
   - Django handles business logic and user management
   - CalDAV server handles calendar protocol and data storage
   - Each component focuses on its core competency

3. **Flexibility**
   - Can expose both REST API (for web app) and CalDAV (for external clients)
   - Different clients can use different protocols
   - Future-proof architecture

4. **Maintainability**
   - Clear boundaries between components
   - Easier to test and debug
   - Can update components independently

5. **Performance**
   - CalDAV server is optimized for CalDAV operations
   - Django can focus on application logic
   - Database can be optimized separately for each use case

## Data Flow

### Creating a Calendar

TODO: should this only be via caldav too?

1. **Frontend** → POST `/api/v1.0/calendars` (REST API)
2. **Django Backend**: Validates request, creates `Calendar` model, calls CalDAV server to create calendar collection
3. **CalDAV Server**: Receives MKCALENDAR request, creates calendar collection, returns calendar path
4. **Django Backend**: Stores CalDAV server path in `Calendar.caldav_path`, returns calendar data to frontend

### Creating an Event

Events are created directly via CalDAV protocol:

1. **Frontend** → PUT `/api/v1.0/caldav/{user}/{calendar}/{event_uid}.ics` (CalDAV)
2. **Django Backend**: `CalDAVProxyView` authenticates user, forwards request to CalDAV server with authentication headers
3. **CalDAV Server**: Receives PUT request with iCalendar data, stores event in calendar collection
4. **Django Backend**: Forwards CalDAV response to frontend

### CalDAV Client Access

1. **CalDAV Client** → PROPFIND `/api/v1.0/caldav/` (CalDAV protocol)
2. **Django Backend**: Authenticates user via Django session, forwards request to CalDAV server with `X-Forwarded-User` header
3. **CalDAV Server**: Processes CalDAV request, returns CalDAV response
4. **Django Backend**: Forwards response to client

## Integration Points

### User Synchronization

Users are automatically created in the CalDAV server when they first access it. The CalDAV server's Apache authentication backend reads the `REMOTE_USER` environment variable, which is set from the `X-Forwarded-User` header sent by Django. No explicit user creation is needed - the CalDAV server will create principals on-demand.

### Calendar Creation

When creating a calendar via REST API:
1. Django creates `Calendar` model with metadata
2. Django calls CalDAV server via HTTP to create calendar collection
3. Django stores CalDAV server path in `Calendar.caldav_path`

### Authentication Translation

Django sessions are translated to CalDAV server authentication:
- Django adds `X-Forwarded-User` header with user email
- CalDAV server converts `X-Forwarded-User` to `REMOTE_USER` environment variable
- CalDAV server's Apache authentication backend reads `REMOTE_USER` for authentication
- All communication is via HTTP - no direct database access

### URL Routing

CalDAV clients expect specific URL patterns. The CalDAV proxy handles path translation:
- Discovery endpoint at `.well-known/caldav` redirects to `/api/v1.0/caldav/`
- Proxy forwards requests to CalDAV server with correct paths

## Database Schema

Both Django and the CalDAV server use the same PostgreSQL database in a local Docker install, but maintain separate schemas:

**Django Schema (public schema):**
- `calendars_user` - User accounts
- `caldav_calendar` - Calendar metadata
- `caldav_calendarshare` - Sharing relationships
- Other Django app tables

**CalDAV Server Schema (public schema, same database):**
- `users` - CalDAV server user records (for digest auth, not used with Apache auth)
- `principals` - CalDAV server principals
- `calendars` - Calendar collections
- `calendarinstances` - Calendar instance metadata
- `calendarobjects` - Calendar resources (events)
- `calendarchanges` - Change tracking
- Other CalDAV server-specific tables

This allows them to share the database locally while keeping data organized. Note that Django never directly accesses CalDAV server tables - all communication is via HTTP.
