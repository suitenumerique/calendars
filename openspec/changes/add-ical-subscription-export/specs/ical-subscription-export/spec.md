## ADDED Requirements

### Requirement: Calendar Subscription Token Management

The system SHALL allow calendar owners to generate a private subscription token
for their calendars using CalDAV paths directly, enabling read-only access via
iCal URL from external calendar applications without requiring Django Calendar
model synchronization.

#### Scenario: Owner generates subscription token

- **GIVEN** a user owns a calendar with CalDAV path `/calendars/<email>/<uuid>/`
- **WHEN** the user requests a subscription token with that CalDAV path
- **THEN** the system verifies the user's email matches the path
- **AND** generates a unique UUID token stored with the CalDAV path
- **AND** returns the subscription URL in format `/ical/<token>.ics`

#### Scenario: Owner retrieves existing subscription token

- **GIVEN** a user owns a calendar with an existing subscription token
- **WHEN** the user requests the subscription token by CalDAV path
- **THEN** the system returns the existing token and URL

#### Scenario: Owner regenerates subscription token

- **GIVEN** a user owns a calendar with an existing subscription token
- **WHEN** the user deletes the token and creates a new one
- **THEN** the old token is invalidated
- **AND** a new unique token is generated
- **AND** the old subscription URL no longer works

#### Scenario: Owner revokes subscription token

- **GIVEN** a user owns a calendar with an existing subscription token
- **WHEN** the user requests to delete the token by CalDAV path
- **THEN** the system removes the token
- **AND** the subscription URL returns 404

#### Scenario: Non-owner cannot manage subscription token

- **GIVEN** a user attempts to create a token for a CalDAV path not containing their email
- **WHEN** the user sends a request with that CalDAV path
- **THEN** the system rejects the request with a 403 permission error

#### Scenario: One token per calendar path per owner

- **GIVEN** a user already has a subscription token for a CalDAV path
- **WHEN** the user requests to create another token for the same path
- **THEN** the system returns the existing token instead of creating a duplicate

---

### Requirement: Public iCal Export Endpoint

The system SHALL provide a public endpoint that serves calendar data in iCal
format when accessed with a valid subscription token, without requiring user
authentication, using the CalDAV path stored directly in the token.

#### Scenario: Valid token returns calendar data

- **GIVEN** a valid and active subscription token exists with a CalDAV path
- **WHEN** an HTTP GET request is made to `/ical/<token>.ics`
- **THEN** the system proxies to SabreDAV using the token's caldav_path and owner email
- **AND** returns the calendar events in iCal format
- **AND** the response Content-Type is `text/calendar`
- **AND** the response is RFC 5545 compliant
- **AND** no authentication headers are required

#### Scenario: Invalid token returns 404

- **GIVEN** a token that does not exist in the system
- **WHEN** an HTTP GET request is made to `/ical/<invalid-token>.ics`
- **THEN** the system returns HTTP 404 Not Found

#### Scenario: Deleted token returns 404

- **GIVEN** a subscription token that has been deleted
- **WHEN** an HTTP GET request is made to `/ical/<deleted-token>.ics`
- **THEN** the system returns HTTP 404 Not Found

#### Scenario: Access tracking

- **GIVEN** a valid subscription token
- **WHEN** the iCal endpoint is accessed successfully
- **THEN** the system updates the token's last accessed timestamp

#### Scenario: Security headers are set

- **GIVEN** a valid subscription URL
- **WHEN** the iCal endpoint returns a response
- **THEN** the response includes `Cache-Control: no-store, private`
- **AND** the response includes `Referrer-Policy: no-referrer`

#### Scenario: Compatible with external calendar apps

- **GIVEN** a valid subscription URL
- **WHEN** the URL is added to Apple Calendar as a subscription
- **THEN** Apple Calendar successfully subscribes and displays events
- **AND** events sync automatically on refresh

---

### Requirement: Subscription URL User Interface

The system SHALL provide a user interface for calendar owners to obtain and
manage subscription URLs using CalDAV paths extracted from calendar URLs.

#### Scenario: Access subscription URL from calendar menu

- **GIVEN** a user is viewing their calendars
- **WHEN** the user opens the context menu for a calendar they own
- **THEN** an option to get the subscription URL is available

#### Scenario: Subscription option hidden for non-owned calendars

- **GIVEN** a user has shared access to a calendar but is not the owner
- **WHEN** the user opens the context menu for that calendar
- **THEN** the subscription URL option is NOT displayed

#### Scenario: Display subscription URL modal

- **GIVEN** a user clicks the subscription URL option for their calendar
- **WHEN** the modal opens
- **THEN** the frontend extracts the CalDAV path from the calendar URL
- **AND** creates or retrieves the token using the CalDAV path
- **AND** the full subscription URL is displayed
- **AND** a "Copy to clipboard" button is available
- **AND** a warning about keeping the URL private is shown
- **AND** an option to regenerate the URL is available

#### Scenario: Copy URL to clipboard

- **GIVEN** the subscription URL modal is open
- **WHEN** the user clicks "Copy to clipboard"
- **THEN** the URL is copied to the system clipboard
- **AND** visual feedback confirms the copy was successful

#### Scenario: Regenerate token from modal

- **GIVEN** the subscription URL modal is open
- **WHEN** the user clicks to regenerate the URL
- **THEN** a confirmation dialog is shown
- **AND** upon confirmation, the old token is deleted
- **AND** a new token is generated
- **AND** the modal updates to show the new URL

#### Scenario: Error handling in modal

- **GIVEN** the subscription URL modal is open
- **WHEN** the initial token fetch returns 404 (no existing token)
- **THEN** the system automatically creates a new token
- **AND** no error message is displayed to the user
- **BUT** if token creation fails, an error message is displayed

---

### Requirement: Standalone Token Storage

The system SHALL store subscription tokens independently of the Django Calendar
model, using CalDAV paths directly to enable token management without requiring
CalDAV-to-Django synchronization.

#### Scenario: Token stores CalDAV path directly

- **GIVEN** a subscription token is created
- **THEN** the token record includes the full CalDAV path
- **AND** the token record includes the owner (user) reference
- **AND** the token record includes an optional calendar display name
- **AND** no foreign key to Django Calendar model is required

#### Scenario: Permission verification via path

- **GIVEN** a user requests a subscription token
- **WHEN** the system verifies permissions
- **THEN** it checks that the user's email appears in the CalDAV path
- **AND** does not require querying the CalDAV server
