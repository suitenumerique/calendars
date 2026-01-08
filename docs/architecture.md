# Calendar Application Architecture

## Overview

The Calendar application is a modern, self-hosted calendar solution that combines a Django REST API backend with a separate CalDAV server (DAViCal) for standards-compliant calendar data storage and synchronization. This architecture provides both a modern web interface and full CalDAV protocol support for compatibility with standard calendar clients.

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
│         DAViCal Server                      │
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
│  - DAViCal schema (calendar data)            │
└──────────────────────────────────────────────┘
```

## Component Responsibilities

### Django Backend

The Django backend serves as the **orchestration layer** and **business logic engine** for the application.

**Primary Responsibilities:**
- **User Management & Authentication**: OIDC authentication via Keycloak, user profiles, sessions, authorization
- **Calendar Metadata Management**: Calendar creation/deletion, sharing, visibility settings, display preferences
- **REST API Layer**: Modern RESTful API for the web frontend (JSON, standard HTTP methods, versioned at `/api/v1.0/`)
- **CalDAV Proxy**: Proxies CalDAV requests to DAViCal, handles authentication translation, URL routing, discovery endpoint
- **Business Logic**: Calendar sharing logic, permission checks, data validation, integration coordination

**Data Storage:**
- User accounts
- Calendar metadata (name, color, visibility, owner)
- Sharing relationships
- Application configuration

**Important**: Django does NOT store actual calendar events. Events are stored in DAViCal.

### DAViCal CalDAV Server

DAViCal is a **standards-compliant CalDAV server** that handles all calendar data storage and protocol operations.

**Primary Responsibilities:**
- **Calendar Data Storage**: Stores actual calendar events in iCalendar format, manages calendar collections
- **CalDAV Protocol Implementation**: Full RFC 4791 implementation (PROPFIND, REPORT, MKCALENDAR, PUT, DELETE)
- **iCalendar Format Management**: Parses and generates iCalendar files, validates syntax, handles VEVENT/VTODO components
- **Database Schema**: Uses PostgreSQL with its own schema for calendar data

**Authentication Integration:**
- Trusts authentication from Django backend via `X-Forwarded-User` header
- Users with password `*` are externally authenticated
- Custom authentication hook validates forwarded user headers

### Frontend (Next.js)

The frontend provides the user interface and interacts with both REST API and CalDAV protocol:
- Modern React-based UI
- Uses REST API for calendar metadata operations
- Uses CalDAV protocol directly for event operations
- Supports multiple languages and themes

## Why This Architecture?

### Design Decision: CalDAV Server Separation

The decision to use a separate CalDAV server (DAViCal) rather than implementing CalDAV directly in Django was made for several reasons:

1. **Standards Compliance**: DAViCal is a mature, well-tested CalDAV server that fully implements RFC 4791. Implementing CalDAV from scratch would be error-prone and time-consuming.

2. **Protocol Complexity**: CalDAV is built on WebDAV, involving complex XML handling, property management, and collection hierarchies. DAViCal handles all of this complexity.

3. **Maintenance**: Using a proven, maintained CalDAV server reduces maintenance burden and ensures compatibility with various CalDAV clients.

4. **Focus**: Django backend can focus on business logic, user management, and REST API, while DAViCal handles calendar protocol operations.

5. **Shared database**: DAViCal was specifically selected because it stores its data into Postgres, which use use in all LaSuite projects.

### Benefits

1. **Standards Compliance**
   - Full CalDAV protocol support enables compatibility with any CalDAV client (Apple Calendar, Thunderbird, etc.)
   - Users can sync calendars with external applications
   - Follows industry standards (RFC 4791)

2. **Separation of Concerns**
   - Django handles business logic and user management
   - DAViCal handles calendar protocol and data storage
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
   - DAViCal is optimized for CalDAV operations
   - Django can focus on application logic
   - Database can be optimized separately for each use case

## Data Flow

### Creating a Calendar

TODO: should this only be via caldav too?

1. **Frontend** → POST `/api/v1.0/calendars` (REST API)
2. **Django Backend**: Validates request, creates `Calendar` model, calls DAViCal to create calendar collection
3. **DAViCal**: Receives MKCALENDAR request, creates calendar collection, returns calendar path
4. **Django Backend**: Stores DAViCal path in `Calendar.davical_path`, returns calendar data to frontend

### Creating an Event

Events are created directly via CalDAV protocol:

1. **Frontend** → PUT `/api/v1.0/caldav/{user}/{calendar}/{event_uid}.ics` (CalDAV)
2. **Django Backend**: `CalDAVProxyView` authenticates user, forwards request to DAViCal with authentication headers
3. **DAViCal**: Receives PUT request with iCalendar data, stores event in calendar collection
4. **Django Backend**: Forwards CalDAV response to frontend

### CalDAV Client Access

1. **CalDAV Client** → PROPFIND `/api/v1.0/caldav/` (CalDAV protocol)
2. **Django Backend**: Authenticates user via Django session, forwards request to DAViCal with `X-Forwarded-User` header
3. **DAViCal**: Processes CalDAV request, returns CalDAV response
4. **Django Backend**: Forwards response to client

## Integration Points

### User Synchronization

When a user is created in Django, they must also exist in DAViCal. The `ensure_user_exists()` method automatically creates DAViCal users when needed, called before any DAViCal operation.

### Calendar Creation

When creating a calendar via REST API:
1. Django creates `Calendar` model with metadata
2. Django calls DAViCal via HTTP to create calendar collection
3. Django stores DAViCal path in `Calendar.davical_path`

### Authentication Translation

Django sessions are translated to DAViCal authentication:
- Django adds `X-Forwarded-User` header with user email
- DAViCal's custom authentication hook validates this header
- Users have password `*` indicating external authentication

### URL Routing

CalDAV clients expect specific URL patterns. The CalDAV proxy handles path translation:
- Discovery endpoint at `.well-known/caldav` redirects to `/api/v1.0/caldav/`
- Proxy forwards requests to DAViCal with correct paths

## Database Schema

Both Django and DAViCal use the same PostgreSQL database in a local Docker install, but maintain separate schemas:

**Django Schema (public schema):**
- `calendars_user` - User accounts
- `caldav_calendar` - Calendar metadata
- `caldav_calendarshare` - Sharing relationships
- Other Django app tables

**DAViCal Schema (public schema, same database):**
- `usr` - DAViCal user records
- `principal` - DAViCal principals
- `collection` - Calendar collections
- `dav_resource` - Calendar resources (events)
- Other DAViCal-specific tables

This allows them to share the database locally while keeping data organized.
