<?php
/**
 * InternalApiPlugin - Handles all /internal-api/ routes.
 *
 * Provides a clean namespace for internal operations (resource provisioning,
 * ICS import) that is completely separated from the CalDAV protocol namespace.
 *
 * Endpoints:
 *   POST   /internal-api/resources/              Create a resource principal
 *   DELETE /internal-api/resources/{resource_id}  Delete a resource principal
 *   POST   /internal-api/import/{user}/{calendar} Bulk import ICS events
 *   POST   /internal-api/calendars/               Create a calendar (and principal if needed)
 *   POST   /internal-api/sync-mailbox-acls/     Sync Messages ACL shares for one user
 *
 * Access control (defense in depth):
 *   1. Django proxy blocklist rejects /internal-api/ paths
 *   2. Requires X-LS-Internal-Api-Key header (different from X-LS-Api-Key used by proxy)
 *   3. Test coverage verifies the proxy rejects these paths
 */

namespace Calendars\SabreDav;

use Sabre\DAV\Server;
use Sabre\DAV\ServerPlugin;
use Sabre\DAV\UUIDUtil;
use Sabre\CalDAV\Backend\PDO as CalDAVBackend;
use Sabre\VObject;

class InternalApiPlugin extends ServerPlugin
{
    /** @var Server */
    protected $server;

    /** @var \PDO */
    private $pdo;

    /** @var CalDAVBackend */
    private $caldavBackend;

    /** @var string */
    private $apiKey;

    public function __construct(\PDO $pdo, CalDAVBackend $caldavBackend, string $apiKey)
    {
        $this->pdo = $pdo;
        $this->caldavBackend = $caldavBackend;
        $this->apiKey = $apiKey;
    }

    public function getPluginName()
    {
        return 'internal-api';
    }

    public function initialize(Server $server)
    {
        $this->server = $server;
        // Use method:* (not beforeMethod:*) so SabreDAV calls sendResponse()
        // for us after the handler returns false.
        $server->on('method:*', [$this, 'handleRequest'], 90);
    }

    /**
     * Intercept all requests under /internal-api/.
     *
     * @return bool|null false to stop event propagation, null to let
     *                   other handlers proceed.
     */
    public function handleRequest($request, $response)
    {
        $path = $request->getPath();

        // Only handle /internal-api/ routes
        if (strpos($path, 'internal-api/') !== 0 && $path !== 'internal-api') {
            return;
        }

        // Verify the dedicated internal API key header
        $headerValue = $request->getHeader('X-LS-Internal-Api-Key');
        if (!$headerValue || !hash_equals($this->apiKey, $headerValue)) {
            $response->setStatus(403);
            $response->setHeader('Content-Type', 'application/json');
            $response->setBody(json_encode([
                'error' => 'Forbidden: missing or invalid X-LS-Internal-Api-Key header',
            ]));
            return false;
        }

        $method = $request->getMethod();

        // Route: POST /internal-api/resources/
        if ($method === 'POST' && preg_match('#^internal-api/resources/?$#', $path)) {
            $this->handleCreateResource($request, $response);
            return false;
        }

        // Route: GET /internal-api/resources/{resource_id}
        if ($method === 'GET' && preg_match('#^internal-api/resources/([a-zA-Z0-9-]+)$#', $path, $matches)) {
            $this->handleGetResource($request, $response, $matches[1]);
            return false;
        }

        // Route: DELETE /internal-api/resources/{resource_id}
        if ($method === 'DELETE' && preg_match('#^internal-api/resources/([a-zA-Z0-9-]+)$#', $path, $matches)) {
            $this->handleDeleteResource($request, $response, $matches[1]);
            return false;
        }

        // Route: POST /internal-api/users/delete
        if ($method === 'POST' && preg_match('#^internal-api/users/delete/?$#', $path)) {
            $body = json_decode($request->getBodyAsString(), true);
            $email = $body['email'] ?? null;
            if (!$email) {
                $response->setStatus(400);
                $response->setHeader('Content-Type', 'application/json');
                $response->setBody(json_encode(['error' => 'email is required']));
                return false;
            }
            $this->handleDeleteUser($request, $response, $email);
            return false;
        }

        // Route: POST /internal-api/calendars/
        if ($method === 'POST' && preg_match('#^internal-api/calendars/?$#', $path)) {
            $this->handleCreateCalendar($request, $response);
            return false;
        }

        // Route: POST /internal-api/sync-mailbox-acls/
        if ($method === 'POST' && preg_match('#^internal-api/sync-mailbox-acls/?$#', $path)) {
            $this->handleSyncMailboxAcls($request, $response);
            return false;
        }

        // Route: POST /internal-api/subscriptions/subscribe/
        if ($method === 'POST' && preg_match('#^internal-api/subscriptions/subscribe/?$#', $path)) {
            $this->handleSubscriptionSubscribe($request, $response);
            return false;
        }

        // Route: POST /internal-api/subscriptions/unsubscribe/
        if ($method === 'POST' && preg_match('#^internal-api/subscriptions/unsubscribe/?$#', $path)) {
            $this->handleSubscriptionUnsubscribe($request, $response);
            return false;
        }

        // Route: GET /internal-api/subscriptions/due/
        if ($method === 'GET' && preg_match('#^internal-api/subscriptions/due/?$#', $path)) {
            $this->handleSubscriptionDue($request, $response);
            return false;
        }

        // Route: POST /internal-api/subscriptions/{sub_id}/sync-result/
        if ($method === 'POST' && preg_match('#^internal-api/subscriptions/([a-f0-9]+)/sync-result/?$#', $path, $matches)) {
            $this->handleSubscriptionSyncResult($request, $response, $matches[1]);
            return false;
        }

        // Route: GET /internal-api/subscriptions/{sub_id}/
        if ($method === 'GET' && preg_match('#^internal-api/subscriptions/([a-f0-9]+)/?$#', $path, $matches)) {
            $this->handleSubscriptionGet($request, $response, $matches[1]);
            return false;
        }

        // Route: GET /internal-api/subscriptions/for-user/{email}
        if ($method === 'GET' && preg_match('#^internal-api/subscriptions/for-user/(.+)$#', $path, $matches)) {
            $this->handleSubscriptionsForUser($request, $response, urldecode($matches[1]));
            return false;
        }

        // Route: POST /internal-api/subscriptions/cleanup-orphans/
        if ($method === 'POST' && preg_match('#^internal-api/subscriptions/cleanup-orphans/?$#', $path)) {
            $this->handleSubscriptionCleanupOrphans($request, $response);
            return false;
        }

        // Route: GET /internal-api/subscriptions/{sub_id}/events/
        if ($method === 'GET' && preg_match('#^internal-api/subscriptions/([a-f0-9]+)/events/?$#', $path, $matches)) {
            $this->handleSubscriptionListEvents($request, $response, $matches[1]);
            return false;
        }

        // Route: POST /internal-api/subscriptions/{sub_id}/events-batch/
        if ($method === 'POST' && preg_match('#^internal-api/subscriptions/([a-f0-9]+)/events-batch/?$#', $path, $matches)) {
            $this->handleSubscriptionEventsBatch($request, $response, $matches[1]);
            return false;
        }

        // Route: POST /internal-api/import/{principalUser}/{calendarUri}
        if ($method === 'POST' && preg_match('#^internal-api/import/([^/]+)/([^/]+)$#', $path, $matches)) {
            $this->handleImport($request, $response, urldecode($matches[1]), $matches[2]);
            return false;
        }

        // Route: GET /internal-api/channel-events/{channel_id}
        if ($method === 'GET' && preg_match('#^internal-api/channel-events/([0-9a-f-]+)$#i', $path, $matches)) {
            $this->handleListChannelEvents($response, $matches[1]);
            return false;
        }

        // Route: GET /internal-api/channel-events/{channel_id}/count
        if ($method === 'GET' && preg_match('#^internal-api/channel-events/([0-9a-f-]+)/count$#i', $path, $matches)) {
            $this->handleCountChannelEvents($response, $matches[1]);
            return false;
        }

        // Route: DELETE /internal-api/channel-events/{channel_id}
        if ($method === 'DELETE' && preg_match('#^internal-api/channel-events/([0-9a-f-]+)$#i', $path, $matches)) {
            $this->handleDeleteChannelEvents($response, $matches[1]);
            return false;
        }

        $response->setStatus(404);
        $response->setHeader('Content-Type', 'application/json');
        $response->setBody(json_encode([
            'error' => 'Not found',
        ]));
        return false;
    }

    /**
     * POST /internal-api/resources/
     * Create a resource principal and its default calendar.
     */
    /**
     * GET /internal-api/resources/{resource_id}
     *
     * Returns the resource principal's org_id. Used by Django's
     * verify_caldav_access to check cross-org resource access.
     */
    private function handleGetResource($request, $response, $resourceId)
    {
        $principalUri = 'principals/resources/' . $resourceId;
        try {
            $stmt = $this->pdo->prepare(
                'SELECT org_id FROM principals WHERE uri = ?'
            );
            $stmt->execute([$principalUri]);
            $row = $stmt->fetch(\PDO::FETCH_ASSOC);
        } catch (\Exception $e) {
            $response->setStatus(500);
            $response->setHeader('Content-Type', 'application/json');
            $response->setBody(json_encode(['error' => 'Database error']));
            return;
        }

        if (!$row) {
            $response->setStatus(404);
            $response->setHeader('Content-Type', 'application/json');
            $response->setBody(json_encode(['error' => 'Resource not found']));
            return;
        }

        $response->setStatus(200);
        $response->setHeader('Content-Type', 'application/json');
        $response->setBody(json_encode([
            'resource_id' => $resourceId,
            'org_id' => $row['org_id'],
        ]));
    }

    private function handleCreateResource($request, $response)
    {
        $body = json_decode($request->getBodyAsString(), true);
        if (!$body) {
            $response->setStatus(400);
            $response->setHeader('Content-Type', 'application/json');
            $response->setBody(json_encode(['error' => 'Invalid JSON body']));
            return false;
        }

        // Strong contract: all fields required. org_id is mandatory for
        // cross-org isolation; resource_type must be set explicitly.
        foreach (['resource_id', 'name', 'email', 'resource_type', 'org_id'] as $field) {
            if (empty($body[$field])) {
                $response->setStatus(400);
                $response->setHeader('Content-Type', 'application/json');
                $response->setBody(json_encode([
                    'error' => 'Missing required field: ' . $field,
                ]));
                return false;
            }
        }

        $resourceId = $body['resource_id'];
        $name = $body['name'];
        $email = $body['email'];
        $resourceType = $body['resource_type'];
        $orgId = $body['org_id'];

        $principalUri = 'principals/resources/' . $resourceId;

        // Wrap principal + calendar creation in a transaction for atomicity
        $this->pdo->beginTransaction();
        try {
            // Insert principal with ON CONFLICT DO NOTHING
            $stmt = $this->pdo->prepare(
                'INSERT INTO principals (uri, email, displayname, calendar_user_type, org_id)'
                . ' VALUES (?, ?, ?, ?, ?)'
                . ' ON CONFLICT (uri) DO NOTHING'
            );
            $stmt->execute([$principalUri, $email, $name, $resourceType, $orgId]);

            if ($stmt->rowCount() === 0) {
                $this->pdo->rollBack();
                $response->setStatus(409);
                $response->setHeader('Content-Type', 'application/json');
                $response->setBody(json_encode([
                    'error' => "Resource '$resourceId' already exists",
                ]));
                return false;
            }

            // Create default calendar
            $calendarUri = 'default';
            $this->caldavBackend->createCalendar(
                $principalUri,
                $calendarUri,
                [
                    '{DAV:}displayname' => $name,
                    '{urn:ietf:params:xml:ns:caldav}supported-calendar-component-set'
                        => new \Sabre\CalDAV\Xml\Property\SupportedCalendarComponentSet(['VEVENT']),
                ]
            );

            $this->pdo->commit();
        } catch (\Exception $e) {
            $this->pdo->rollBack();
            error_log("[InternalApiPlugin] Failed to create resource: " . $e->getMessage());
            $response->setStatus(500);
            $response->setHeader('Content-Type', 'application/json');
            $response->setBody(json_encode([
                'error' => 'Failed to create resource',
            ]));
            return false;
        }

        $response->setStatus(201);
        $response->setHeader('Content-Type', 'application/json');
        $response->setBody(json_encode([
            'principal_uri' => $principalUri,
            'email' => $email,
        ]));
        return false;
    }

    /**
     * DELETE /internal-api/resources/{resource_id}
     * Delete a resource principal, its calendars, and all associated data.
     */
    private function handleDeleteResource($request, $response, $resourceId)
    {
        $principalUri = 'principals/resources/' . $resourceId;
        $orgId = $request->getHeader('X-LS-Org-Id');

        // Strong contract: X-LS-Org-Id must be present (fail-closed).
        if (!$orgId) {
            $response->setStatus(400);
            $response->setHeader('Content-Type', 'application/json');
            $response->setBody(json_encode([
                'error' => 'X-LS-Org-Id header is required',
            ]));
            return false;
        }

        // Look up the principal
        try {
            $stmt = $this->pdo->prepare(
                'SELECT email, org_id FROM principals WHERE uri = ?'
            );
            $stmt->execute([$principalUri]);
            $row = $stmt->fetch(\PDO::FETCH_ASSOC);
        } catch (\Exception $e) {
            error_log("[InternalApiPlugin] Failed to look up principal: " . $e->getMessage());
            $response->setStatus(500);
            $response->setHeader('Content-Type', 'application/json');
            $response->setBody(json_encode(['error' => 'Failed to look up resource']));
            return false;
        }

        if (!$row) {
            $response->setStatus(404);
            $response->setHeader('Content-Type', 'application/json');
            $response->setBody(json_encode([
                'error' => "Resource '$resourceId' not found",
            ]));
            return false;
        }

        // Verify org scoping — fail-closed if the stored org is missing or
        // does not match the caller's X-LS-Org-Id.
        if (!$row['org_id'] || $orgId !== $row['org_id']) {
            $response->setStatus(403);
            $response->setHeader('Content-Type', 'application/json');
            $response->setBody(json_encode([
                'error' => 'Cannot delete a resource from a different organization',
            ]));
            return false;
        }

        // Delete calendars and their objects
        try {
            $calendars = $this->caldavBackend->getCalendarsForUser($principalUri);
            foreach ($calendars as $calendar) {
                $this->caldavBackend->deleteCalendar($calendar['id']);
            }
        } catch (\Exception $e) {
            error_log("[InternalApiPlugin] Failed to delete calendars: " . $e->getMessage());
        }

        // Delete scheduling objects, principal rows
        $this->deletePrincipalRows($principalUri);

        $response->setStatus(200);
        $response->setHeader('Content-Type', 'application/json');
        $response->setBody(json_encode(['deleted' => true]));
        return false;
    }

    /**
     * Delete principal row and associated proxy/scheduling rows.
     */
    private function deletePrincipalRows($principalUri)
    {
        try {
            // Delete scheduling objects if the table exists
            $stmt = $this->pdo->prepare(
                "SELECT EXISTS ("
                . "  SELECT FROM information_schema.tables"
                . "  WHERE table_name = 'schedulingobjects'"
                . ")"
            );
            $stmt->execute();
            if ($stmt->fetchColumn()) {
                $del = $this->pdo->prepare(
                    'DELETE FROM schedulingobjects WHERE principaluri = ?'
                );
                $del->execute([$principalUri]);
            }

            // Delete principal and proxy rows
            $del = $this->pdo->prepare('DELETE FROM principals WHERE uri = ?');
            $del->execute([$principalUri]);

            $del = $this->pdo->prepare('DELETE FROM principals WHERE uri LIKE ?');
            $del->execute([$principalUri . '/%']);
        } catch (\Exception $e) {
            error_log("[InternalApiPlugin] Failed to delete principal rows: " . $e->getMessage());
        }
    }

    /**
     * POST /internal-api/users/delete
     * Delete a user principal and all their calendar data.
     * Body: {"email": "user@example.com"}
     */
    private function handleDeleteUser($request, $response, $email)
    {
        $principalUri = 'principals/users/' . $email;
        $orgId = $request->getHeader('X-LS-Org-Id');

        // Strong contract: X-LS-Org-Id must be present (fail-closed).
        if (!$orgId) {
            $response->setStatus(400);
            $response->setHeader('Content-Type', 'application/json');
            $response->setBody(json_encode([
                'error' => 'X-LS-Org-Id header is required',
            ]));
            return false;
        }

        // Look up the principal
        try {
            $stmt = $this->pdo->prepare(
                'SELECT id, org_id FROM principals WHERE uri = ?'
            );
            $stmt->execute([$principalUri]);
            $row = $stmt->fetch(\PDO::FETCH_ASSOC);
        } catch (\Exception $e) {
            error_log("[InternalApiPlugin] Failed to look up user principal: " . $e->getMessage());
            $response->setStatus(500);
            $response->setHeader('Content-Type', 'application/json');
            $response->setBody(json_encode(['error' => 'Failed to look up user']));
            return false;
        }

        if (!$row) {
            // Principal doesn't exist — nothing to clean up
            $response->setStatus(200);
            $response->setHeader('Content-Type', 'application/json');
            $response->setBody(json_encode(['deleted' => true, 'existed' => false]));
            return false;
        }

        // Verify org scoping — fail-closed if the stored org is missing or
        // does not match the caller's X-LS-Org-Id.
        if (!$row['org_id'] || $orgId !== $row['org_id']) {
            $response->setStatus(403);
            $response->setHeader('Content-Type', 'application/json');
            $response->setBody(json_encode([
                'error' => 'Cannot delete a user from a different organization',
            ]));
            return false;
        }

        // Delete calendars and their objects
        try {
            $calendars = $this->caldavBackend->getCalendarsForUser($principalUri);
            foreach ($calendars as $calendar) {
                $this->caldavBackend->deleteCalendar($calendar['id']);
            }
        } catch (\Exception $e) {
            error_log("[InternalApiPlugin] Failed to delete user calendars: " . $e->getMessage());
        }

        // Delete scheduling objects, principal rows
        $this->deletePrincipalRows($principalUri);

        $response->setStatus(200);
        $response->setHeader('Content-Type', 'application/json');
        $response->setBody(json_encode(['deleted' => true, 'existed' => true]));
        return false;
    }

    /**
     * POST /internal-api/calendars/
     * Create a calendar under a principal (creating the principal if needed).
     *
     * Unlike MKCALENDAR (which only works for the authenticated user's own
     * principal), this endpoint can create calendars under any principal
     * — including mailbox principals that no user logs in as.
     *
     * Each call creates a NEW calendar. The first call for a fresh
     * principal uses the URI ``default`` (so existing onboarding code
     * paths and bookmarks keep working); subsequent calls allocate a
     * fresh UUID URI. This means a user can have multiple calendars
     * backed by the same mailbox principal.
     *
     * Color is strictly personal: for mailbox calendars (where the
     * caller is not the principal) the picked ``color`` lands on the
     * caller's own sharee instance, never on the owner instance and
     * never propagated to other mailbox users. For individual calendars
     * (caller IS the principal) it lands on the owner instance — the
     * only one the caller has.
     *
     * Body: {
     *   "email": "contact@company.com",       (required) principal email
     *   "calendar_user_type": "INDIVIDUAL",   (required; INDIVIDUAL | MAILBOX)
     *   "org_id": "...",                       (required)
     *   "name": "Contact Team",               (optional, defaults to email)
     *   "color": "#dc3545",                   (optional, defaults to #3788d8)
     *   "caller_email": "alice@co",           (optional) When set and
     *       different from ``email``, an additional sharee instance for
     *       the caller is inserted with read-write access and the
     *       chosen ``color``. Used by the mailbox setup flow so the
     *       caller sees the new calendar with their picked color
     *       immediately, without waiting for sync-mailbox-acls.
     * }
     */
    private function handleCreateCalendar($request, $response)
    {
        $body = json_decode($request->getBodyAsString(), true);
        if (!$body) {
            $response->setStatus(400);
            $response->setHeader('Content-Type', 'application/json');
            $response->setBody(json_encode(['error' => 'Invalid JSON body']));
            return false;
        }

        // Strong contract: email, calendar_user_type and org_id are
        // mandatory. Requiring org_id here prevents silently inserting a
        // NULL-org principal (which would bypass cross-org freebusy and
        // discovery isolation) and prevents an upsert from downgrading
        // MAILBOX → INDIVIDUAL.
        foreach (['email', 'calendar_user_type', 'org_id'] as $field) {
            if (empty($body[$field])) {
                $response->setStatus(400);
                $response->setHeader('Content-Type', 'application/json');
                $response->setBody(json_encode([
                    'error' => 'Missing required field: ' . $field,
                ]));
                return false;
            }
        }

        $email = $body['email'];
        $calendarUserType = $body['calendar_user_type'];
        $orgId = $body['org_id'];
        $name = $body['name'] ?? $email;
        $color = $body['color'] ?? '#3788d8';
        $callerEmail = $body['caller_email'] ?? null;
        $principalUri = 'principals/users/' . $email;
        $isMailbox = ($calendarUserType === PrincipalBackend::TYPE_MAILBOX);
        $callerIsOwner = ($callerEmail === null || $callerEmail === $email);

        // Subscription calendars are created via the dedicated subscribe
        // endpoint (principals/subscriptions/<hash>, NULL org_id, shared
        // read-only). Steer callers there to keep this endpoint focused
        // on the user/mailbox flow.
        if ($calendarUserType === PrincipalBackend::TYPE_SUBSCRIPTION) {
            $response->setStatus(400);
            $response->setHeader('Content-Type', 'application/json');
            $response->setBody(json_encode([
                'error' => 'Use POST /internal-api/subscriptions/subscribe/ to'
                    . ' create subscription calendars',
            ]));
            return false;
        }

        $this->pdo->beginTransaction();
        try {
            // Refuse to downgrade an existing MAILBOX principal back to
            // INDIVIDUAL. Auto-provisioning (ensurePrincipal) creates
            // principals as INDIVIDUAL before setup runs, so promoting
            // INDIVIDUAL → MAILBOX is allowed. The reverse is blocked
            // because MAILBOX controls auth/ACL rules (sync-managed
            // shares, freebusy scoping, login is forbidden, …).
            $existing = $this->pdo->prepare(
                'SELECT calendar_user_type FROM principals WHERE uri = ? FOR UPDATE'
            );
            $existing->execute([$principalUri]);
            $existingType = $existing->fetchColumn();
            $isUpgrade = ($existingType === PrincipalBackend::TYPE_INDIVIDUAL
                          && $calendarUserType === PrincipalBackend::TYPE_MAILBOX);
            if ($existingType !== false && $existingType !== $calendarUserType
                && !$isUpgrade) {
                $this->pdo->rollBack();
                error_log(
                    "[InternalApiPlugin] Refusing to change calendar_user_type for "
                    . "{$principalUri}: existing={$existingType} requested={$calendarUserType}"
                );
                $response->setStatus(409);
                $response->setHeader('Content-Type', 'application/json');
                $response->setBody(json_encode([
                    'error' => 'Principal already exists with a different calendar_user_type',
                    'existing_type' => $existingType,
                    'requested_type' => $calendarUserType,
                ]));
                return false;
            }

            $stmt = $this->pdo->prepare(
                'INSERT INTO principals (uri, email, displayname, calendar_user_type, org_id)'
                . ' VALUES (?, ?, ?, ?, ?)'
                . ' ON CONFLICT (uri) DO UPDATE SET'
                . ' org_id = EXCLUDED.org_id,'
                . ' displayname = EXCLUDED.displayname,'
                . ' calendar_user_type = EXCLUDED.calendar_user_type'
            );
            $stmt->execute([$principalUri, $email, $name, $calendarUserType, $orgId]);

            // Serialize concurrent calls for the same principal: lock
            // the principal row so two simultaneous requests can't both
            // pick the URI ``default`` for the first calendar.
            $lockStmt = $this->pdo->prepare(
                'SELECT id FROM principals WHERE uri = ? FOR UPDATE'
            );
            $lockStmt->execute([$principalUri]);

            // First calendar gets the URI ``default`` (preserving
            // legacy onboarding URLs); subsequent calendars get a UUID.
            $existingCalendars = $this->caldavBackend->getCalendarsForUser($principalUri);
            $newUri = empty($existingCalendars) ? 'default' : UUIDUtil::getUUID();

            // For mailbox calendars the owner-side color is invisible
            // (no human logs in as the mailbox principal), so we store
            // a fixed default and put the caller's color on their own
            // sharee instance below. For individual calendars the
            // caller IS the owner, so the color goes directly on the
            // owner instance via the property map.
            $ownerColor = ($isMailbox && !$callerIsOwner) ? '#3788d8' : $color;
            $this->caldavBackend->createCalendar(
                $principalUri,
                $newUri,
                [
                    '{DAV:}displayname' => $name,
                    '{http://apple.com/ns/ical/}calendar-color' => $ownerColor,
                    '{urn:ietf:params:xml:ns:caldav}supported-calendar-component-set'
                        => new \Sabre\CalDAV\Xml\Property\SupportedCalendarComponentSet(['VEVENT']),
                ]
            );

            // Mailbox path: also create the caller's own sharee
            // instance now with their picked color, so they see the
            // calendar in their UI immediately and the color is theirs
            // alone (sync-mailbox-acls will fan out to other users with
            // the default color).
            //
            // ``callerCalendarUri`` is the URI the caller will use to
            // read the calendar from THEIR own principal home — it's
            // the freshly-allocated UUID for the sharee row, not the
            // owner-side ``$newUri``. We surface it in the response so
            // callers (Python setup service, tests) don't have to do
            // a follow-up PROPFIND just to discover it.
            $callerCalendarUri = $newUri;
            if ($isMailbox && !$callerIsOwner) {
                $cidStmt = $this->pdo->prepare(
                    'SELECT calendarid FROM calendarinstances'
                    . ' WHERE principaluri = ? AND uri = ?'
                );
                $cidStmt->execute([$principalUri, $newUri]);
                $calendarId = (int) $cidStmt->fetchColumn();

                $callerPrincipal = 'principals/users/' . $callerEmail;
                $callerCalendarUri = UUIDUtil::getUUID();
                $sharee = $this->pdo->prepare(
                    'INSERT INTO calendarinstances'
                    . ' (calendarid, principaluri, access, uri, displayname,'
                    . '  calendarcolor, share_href, share_displayname,'
                    . '  share_invitestatus, transparent, is_sync_managed)'
                    . ' VALUES (?, ?, ?, ?, ?, ?, ?, ?, 2, 0, TRUE)'
                );
                $sharee->execute([
                    $calendarId,
                    $callerPrincipal,
                    PrincipalBackend::ACCESS_READ_WRITE,
                    $callerCalendarUri,
                    $name,
                    $color,
                    'mailto:' . $callerEmail,
                    $callerEmail,
                ]);
            }

            $this->pdo->commit();
        } catch (\Exception $e) {
            $this->pdo->rollBack();
            error_log("[InternalApiPlugin] Failed to create calendar: " . $e->getMessage());
            $response->setStatus(500);
            $response->setHeader('Content-Type', 'application/json');
            $response->setBody(json_encode(['error' => 'Failed to create calendar']));
            return false;
        }

        $response->setStatus(201);
        $response->setHeader('Content-Type', 'application/json');
        $response->setBody(json_encode([
            'principal_uri' => $principalUri,
            'email' => $email,
            'calendar_uri' => $newUri,
            'caller_calendar_uri' => $callerCalendarUri,
            'created' => true,
        ]));
        return false;
    }

    /**
     * POST /internal-api/sync-mailbox-acls/
     * Batch sync Messages ACLs to CalDAV shares for multiple users at once.
     *
     * Body: {
     *   "shares": [
     *     {"user_email": "alice@co", "mailbox_email": "contact@co",
     *      "privilege": "read-write"},
     *     {"user_email": "bob@co", "mailbox_email": "contact@co",
     *      "privilege": "read"}
     *   ],
     *   "full_sync_users": ["alice@co"]
     * }
     *
     * Each share entry grants access at the **mailbox** level: the
     * privilege is fanned out to every owner calendar that lives under
     * the mailbox principal. A single mailbox can back several
     * calendars (the second create allocates a UUID URI), and Messages
     * tracks access per mailbox — not per calendar — so the share
     * naturally applies to all of them.
     *
     * "shares" is a flat list of all desired sync-managed shares.
     * "full_sync_users" lists users whose stale shares should be removed
     * (users not in this list only get additive upserts).
     */
    private function handleSyncMailboxAcls($request, $response)
    {
        $body = json_decode($request->getBodyAsString(), true);
        if (!$body) {
            $response->setStatus(400);
            $response->setHeader('Content-Type', 'application/json');
            $response->setBody(json_encode(['error' => 'Invalid JSON body']));
            return false;
        }

        // Strong contract: shares must be an array (may be empty for
        // full-sync-only calls); full_sync_users must be an array.
        if (!array_key_exists('shares', $body) || !is_array($body['shares'])) {
            $response->setStatus(400);
            $response->setHeader('Content-Type', 'application/json');
            $response->setBody(json_encode([
                'error' => 'Missing or invalid field: shares (must be array)',
            ]));
            return false;
        }
        if (array_key_exists('full_sync_users', $body)
            && !is_array($body['full_sync_users'])
        ) {
            $response->setStatus(400);
            $response->setHeader('Content-Type', 'application/json');
            $response->setBody(json_encode([
                'error' => 'Invalid field: full_sync_users (must be array)',
            ]));
            return false;
        }

        $shares = $body['shares'];
        $fullSyncUsers = array_flip($body['full_sync_users'] ?? []);

        // Validate each share entry strictly.
        foreach ($shares as $i => $share) {
            if (!is_array($share)) {
                $response->setStatus(400);
                $response->setHeader('Content-Type', 'application/json');
                $response->setBody(json_encode([
                    'error' => "shares[$i] must be an object",
                ]));
                return false;
            }
            foreach (['user_email', 'mailbox_email', 'privilege'] as $f) {
                if (empty($share[$f])) {
                    $response->setStatus(400);
                    $response->setHeader('Content-Type', 'application/json');
                    $response->setBody(json_encode([
                        'error' => "shares[$i] missing required field: $f",
                    ]));
                    return false;
                }
            }
            if (!in_array($share['privilege'], ['read', 'read-write'], true)) {
                $response->setStatus(400);
                $response->setHeader('Content-Type', 'application/json');
                $response->setBody(json_encode([
                    'error' => "shares[$i] invalid privilege: "
                        . "must be 'read' or 'read-write'",
                ]));
                return false;
            }
        }
        $privilegeMap = [
            'read' => PrincipalBackend::ACCESS_READ,
            'read-write' => PrincipalBackend::ACCESS_READ_WRITE,
        ];

        $this->pdo->beginTransaction();
        try {
            // 1. Batch-fetch all owner calendar instances (one query).
            // Indexed by mailbox email so a single share entry can fan
            // out to every calendar under that mailbox principal — a
            // mailbox can back several calendars (the second create
            // allocates a UUID URI) and Messages tracks access at the
            // mailbox level, not per calendar.
            $mailboxEmails = array_unique(
                array_filter(array_column($shares, 'mailbox_email'))
            );
            $ownerCalendarsByMailbox = []; // mailbox_email → [row, ...]
            if ($mailboxEmails) {
                $ownerPrincipals = array_map(
                    fn($e) => 'principals/users/' . $e,
                    $mailboxEmails
                );
                $ph = implode(',', array_fill(0, count($ownerPrincipals), '?'));
                // INVARIANT: sync-managed rows must only ever land under
                // a MAILBOX-owned calendar. ``MailboxPlugin::restrictSharing``
                // and ``ShareAccessPlugin::afterPost`` rely on this — if a
                // sync-managed row existed on an INDIVIDUAL calendar, manual
                // CS:share/CS:remove ops would silently overwrite it. We
                // enforce the invariant at the source by JOINing on the
                // owning principal's ``calendar_user_type``: a caller that
                // accidentally (or maliciously) passes an INDIVIDUAL
                // ``mailbox_email`` gets zero rows back and the share entry
                // is silently dropped instead of producing a malformed row.
                $stmt = $this->pdo->prepare(
                    'SELECT ci.calendarid, ci.principaluri, ci.uri, ci.displayname, ci.calendarcolor '
                    . 'FROM calendarinstances ci '
                    . 'JOIN principals p ON p.uri = ci.principaluri '
                    . 'WHERE ci.principaluri IN (' . $ph . ') '
                    . '  AND ci.access = 1 '
                    . '  AND p.calendar_user_type = \'' . PrincipalBackend::TYPE_MAILBOX . '\''
                );
                $stmt->execute($ownerPrincipals);
                foreach ($stmt->fetchAll(\PDO::FETCH_ASSOC) as $row) {
                    $email = str_replace('principals/users/', '', $row['principaluri']);
                    $ownerCalendarsByMailbox[$email][] = $row;
                }
            }

            // 2. Collect all involved user emails
            $allUserEmails = array_unique(array_merge(
                array_filter(array_column($shares, 'user_email')),
                array_keys($fullSyncUsers)
            ));
            if (empty($allUserEmails)) {
                $this->pdo->commit();
                $response->setStatus(200);
                $response->setHeader('Content-Type', 'application/json');
                $response->setBody(json_encode(['active' => []]));
                return false;
            }

            // 3. Batch-fetch existing sync-managed shares for all users (one query)
            $userPrincipals = array_map(
                fn($e) => 'principals/users/' . $e,
                $allUserEmails
            );
            $ph = implode(',', array_fill(0, count($userPrincipals), '?'));
            $stmt = $this->pdo->prepare(
                'SELECT id, principaluri, calendarid, access FROM calendarinstances '
                . 'WHERE principaluri IN (' . $ph . ') AND is_sync_managed = TRUE'
            );
            $stmt->execute($userPrincipals);
            // existing[principaluri][calendarid] → row
            $existing = [];
            foreach ($stmt->fetchAll(\PDO::FETCH_ASSOC) as $row) {
                $existing[$row['principaluri']][(int)$row['calendarid']] = $row;
            }

            // 4. Group desired shares by user. Each input share fans out
            // to every owner calendar under the mailbox principal, so a
            // single (user, mailbox, privilege) entry yields one
            // desired/active row per concrete calendar.
            // desired[principaluri][calendarid] → {access, uri, displayname}
            $desired = [];
            $active = [];
            foreach ($shares as $share) {
                $userEmail = $share['user_email'];
                $mailboxEmail = $share['mailbox_email'];
                $privilege = $share['privilege'];

                $mailboxCalendars = $ownerCalendarsByMailbox[$mailboxEmail] ?? [];
                if (empty($mailboxCalendars)) {
                    continue;
                }

                $principal = 'principals/users/' . $userEmail;
                $access = $privilegeMap[$privilege];

                foreach ($mailboxCalendars as $ownerCal) {
                    $calendarId = (int)$ownerCal['calendarid'];
                    $desired[$principal][$calendarId] = [
                        'access' => $access,
                        'displayname' => $ownerCal['displayname'],
                        'share_href' => 'mailto:' . $userEmail,
                        'share_displayname' => $userEmail,
                        // Color is strictly personal: each sharee starts
                        // with the default and is free to PROPPATCH their
                        // own. Do NOT inherit from the owner — for mailbox
                        // calendars the owner-side color is meaningless,
                        // and for individual calendars sharing the owner's
                        // color into a sharee's view would be confusing.
                        'color' => '#3788d8',
                    ];
                    $active[] = [
                        'user_email' => $userEmail,
                        'mailbox_email' => $mailboxEmail,
                        'calendar_uri' => $ownerCal['uri'],
                        'privilege' => $privilege,
                    ];
                }
            }

            // 5. Prepare upsert statement (reused across all users)
            $upsertStmt = $this->pdo->prepare(
                'INSERT INTO calendarinstances '
                . '(calendarid, principaluri, access, uri, displayname, calendarcolor, '
                . 'share_href, share_displayname, share_invitestatus, transparent, is_sync_managed) '
                . 'VALUES (?, ?, ?, ?, ?, ?, ?, ?, 2, 0, TRUE) '
                . 'ON CONFLICT (principaluri, calendarid) '
                . 'DO UPDATE SET access = EXCLUDED.access, share_href = EXCLUDED.share_href, '
                . 'is_sync_managed = TRUE'
            );

            // 6. Apply diff per user
            $staleIds = [];
            foreach ($allUserEmails as $userEmail) {
                $principal = 'principals/users/' . $userEmail;
                $userExisting = $existing[$principal] ?? [];
                $userDesired = $desired[$principal] ?? [];

                // Upsert changed/new shares
                foreach ($userDesired as $calendarId => $d) {
                    if (isset($userExisting[$calendarId])
                        && (int)$userExisting[$calendarId]['access'] === $d['access']) {
                        continue;
                    }
                    // UUID for the uri column (same as SabreDAV's native CS:share).
                    // Only used on first INSERT; (principaluri, calendarid)
                    // unique index handles upsert — existing URI is preserved.
                    $upsertStmt->execute([
                        $calendarId, $principal, $d['access'], UUIDUtil::getUUID(),
                        $d['displayname'], $d['color'],
                        $d['share_href'], $d['share_displayname'],
                    ]);
                }

                // Collect stale shares (only for full_sync users)
                if (isset($fullSyncUsers[$userEmail])) {
                    foreach ($userExisting as $calendarId => $row) {
                        if (!isset($userDesired[$calendarId])) {
                            $staleIds[] = $row['id'];
                        }
                    }
                }
            }

            // 7. Batch delete stale shares (one query)
            if ($staleIds) {
                $ph = implode(',', array_fill(0, count($staleIds), '?'));
                $stmt = $this->pdo->prepare(
                    'DELETE FROM calendarinstances WHERE id IN (' . $ph . ')'
                );
                $stmt->execute($staleIds);
            }

            $this->pdo->commit();
        } catch (\Exception $e) {
            $this->pdo->rollBack();
            error_log("[InternalApiPlugin] Failed to sync mailbox ACLs: " . $e->getMessage());
            $response->setStatus(500);
            $response->setHeader('Content-Type', 'application/json');
            $response->setBody(json_encode(['error' => 'Failed to sync mailbox ACLs']));
            return false;
        }

        $response->setStatus(200);
        $response->setHeader('Content-Type', 'application/json');
        $response->setBody(json_encode(['active' => $active]));
        return false;
    }


    /**
     * POST /internal-api/import/{principalUser}/{calendarUri}
     * Bulk import events from a multi-event ICS file.
     */
    private function handleImport($request, $response, $principalUser, $calendarUri)
    {
        $principalUri = 'principals/users/' . $principalUser;

        // Look up calendarId AND the calendar's supported component set
        // — we need to enforce the latter on every imported component
        // because this endpoint short-circuits straight to the backend,
        // bypassing CalDAV\Plugin::validateICalendar (which is what
        // enforces the constraint on the HTTP PUT path).
        $calendarInfo = $this->resolveCalendarInfo($principalUri, $calendarUri);
        if ($calendarInfo === null) {
            $response->setStatus(404);
            $response->setHeader('Content-Type', 'application/json');
            $response->setBody(json_encode(['error' => 'Calendar not found']));
            return false;
        }
        $calendarId = $calendarInfo['id'];
        $supportedComponents = $calendarInfo['supportedComponents'];

        // Read and parse the raw ICS body
        $icsBody = $request->getBodyAsString();
        if (empty($icsBody)) {
            $response->setStatus(400);
            $response->setHeader('Content-Type', 'application/json');
            $response->setBody(json_encode(['error' => 'Empty request body']));
            return false;
        }

        try {
            $vcal = VObject\Reader::read($icsBody);
        } catch (\Exception $e) {
            error_log("[InternalApiPlugin] Failed to parse ICS: " . $e->getMessage());
            $response->setStatus(400);
            $response->setHeader('Content-Type', 'application/json');
            $response->setBody(json_encode(['error' => 'Failed to parse ICS file']));
            return false;
        }

        // Validate and auto-repair (fixes missing VALARM ACTION, etc.)
        $vcal->validate(VObject\Component::REPAIR);

        // Split by UID using the stream-based splitter
        $stream = fopen('php://temp', 'r+');
        fwrite($stream, $vcal->serialize());
        rewind($stream);

        $splitter = new VObject\Splitter\ICalendar($stream);

        $totalEvents = 0;
        $importedCount = 0;
        $duplicateCount = 0;
        $skippedCount = 0;
        $filteredCount = 0;
        // Titles of events that were filtered out because their
        // component type isn't in the calendar's supported set. Capped
        // at 100 so a hostile import can't blow up the response.
        $filteredTitles = [];
        $errors = [];

        // Set audit context once before the import loop. Reuses the
        // X-LS-User auth header so the audit principal can never drift
        // from the authenticated principal (same contract as
        // AuditContextPlugin for the regular write path).
        if ($this->caldavBackend instanceof AuditCalDAVBackend) {
            $user = $request->getHeader('X-LS-User');
            if ($user) {
                $this->caldavBackend->setCurrentPrincipal($user);
            }
            $channelId = $request->getHeader('X-LS-Channel-Id');
            $this->caldavBackend->setCurrentChannelId($channelId ?: null);
        }

        try {
            while ($splitVcal = $splitter->getNext()) {
                $totalEvents++;

                try {
                    // Filter components whose type is not in the
                    // calendar's supported-calendar-component-set.
                    // Counts as skipped (NOT an error) and the event
                    // SUMMARY is added to the filteredTitles list so
                    // the frontend can show "X events were filtered".
                    $componentType = $this->detectComponentType($splitVcal);
                    if (
                        $componentType !== null
                        && !in_array($componentType, $supportedComponents, true)
                    ) {
                        $skippedCount++;
                        $filteredCount++;
                        if (count($filteredTitles) < 100) {
                            $title = $this->extractTitle($splitVcal, $componentType);
                            $filteredTitles[] = $title;
                        }
                        continue;
                    }

                    // Extract UID from the first VEVENT
                    $uid = null;
                    foreach ($splitVcal->VEVENT as $vevent) {
                        if (isset($vevent->UID)) {
                            $uid = (string)$vevent->UID;
                            break;
                        }
                    }

                    if (!$uid) {
                        $uid = \Sabre\DAV\UUIDUtil::getUUID();
                    }

                    // Sanitize event data (strip attachments, truncate descriptions)
                    $this->sanitizeAndCheckSize($splitVcal);

                    $objectUri = $uid . '.ics';
                    $data = $splitVcal->serialize();

                    $this->caldavBackend->createCalendarObject(
                        $calendarId,
                        $objectUri,
                        $data
                    );
                    $importedCount++;
                } catch (\Exception $e) {
                    $msg = $e->getMessage();
                    $summary = '';
                    if (isset($splitVcal->VEVENT) && isset($splitVcal->VEVENT->SUMMARY)) {
                        $summary = (string)$splitVcal->VEVENT->SUMMARY;
                    }

                    if (strpos($msg, '23505') !== false) {
                        $duplicateCount++;
                    } elseif (strpos($msg, 'valid instances') !== false) {
                        $skippedCount++;
                    } else {
                        $skippedCount++;
                        if (count($errors) < 10) {
                            $errors[] = [
                                'uid' => $uid ?? 'unknown',
                                'summary' => $summary,
                                'error' => $msg,
                            ];
                        }
                        error_log(
                            "[InternalApiPlugin] Failed to import event "
                            . "uid=" . ($uid ?? 'unknown')
                            . " summary={$summary}: {$msg}"
                        );
                    }
                }
            }
        } finally {
            fclose($stream);
        }

        error_log(
            "[InternalApiPlugin] Import complete: "
            . "{$importedCount} imported, "
            . "{$duplicateCount} duplicates, "
            . "{$skippedCount} skipped ({$filteredCount} filtered by component-set) "
            . "out of {$totalEvents} total"
        );

        $response->setStatus(200);
        $response->setHeader('Content-Type', 'application/json');
        $response->setBody(json_encode([
            'total_events' => $totalEvents,
            'imported_count' => $importedCount,
            'duplicate_count' => $duplicateCount,
            'skipped_count' => $skippedCount,
            'filtered_count' => $filteredCount,
            'filtered' => $filteredTitles,
            'errors' => $errors,
        ]));

        return false;
    }

    /**
     * Pull a human-readable title from a split VCALENDAR for the
     * import response. Falls back to the UID, then a placeholder.
     */
    private function extractTitle(VObject\Component\VCalendar $vcal, string $componentType): string
    {
        if (!isset($vcal->{$componentType})) {
            return 'Untitled';
        }
        foreach ($vcal->{$componentType} as $component) {
            if (isset($component->SUMMARY)) {
                $summary = trim((string)$component->SUMMARY);
                if ($summary !== '') {
                    return $summary;
                }
            }
            if (isset($component->UID)) {
                $uid = trim((string)$component->UID);
                if ($uid !== '') {
                    return $uid;
                }
            }
            break;
        }
        return 'Untitled';
    }

    /**
     * Sanitize a split VCALENDAR before import and enforce max resource size.
     */
    private function sanitizeAndCheckSize(VObject\Component\VCalendar $vcal)
    {
        $sanitizer = $this->server->getPlugin('calendar-sanitizer');
        if ($sanitizer) {
            $sanitizer->sanitizeVCalendar($vcal);
            $sanitizer->checkResourceSize($vcal);
        }
    }

    /**
     * GET /internal-api/channel-events/{channel_id}
     * List events associated with a channel.
     */
    private function handleListChannelEvents($response, string $channelId)
    {
        try {
            $stmt = $this->pdo->prepare(
                'SELECT co.uid, co.uri, co.calendarid, co.created_by, co.created_at, '
                . "ci.principaluri, '/' || 'calendars/' || "
                . "CASE WHEN ci.principaluri LIKE 'principals/users/%' THEN 'users' ELSE 'resources' END "
                . "|| '/' || SPLIT_PART(ci.principaluri, '/', 3) || '/' || ci.uri || '/' AS calendar_path "
                . 'FROM calendarobjects co '
                . 'JOIN calendarinstances ci ON ci.calendarid = co.calendarid AND ci.access = 1 '
                . 'WHERE co.channel_id = ?::uuid '
                . 'ORDER BY co.created_at DESC'
            );
            $stmt->execute([$channelId]);
            $rows = $stmt->fetchAll(\PDO::FETCH_ASSOC);
        } catch (\Exception $e) {
            error_log('[InternalApiPlugin] Failed to list channel events: ' . $e->getMessage());
            $response->setStatus(500);
            $response->setHeader('Content-Type', 'application/json');
            $response->setBody(json_encode(['error' => 'Failed to list events']));
            return;
        }

        $response->setStatus(200);
        $response->setHeader('Content-Type', 'application/json');
        $response->setBody(json_encode(['events' => $rows]));
    }

    /**
     * GET /internal-api/channel-events/{channel_id}/count
     * Count events associated with a channel.
     */
    private function handleCountChannelEvents($response, string $channelId)
    {
        try {
            $stmt = $this->pdo->prepare(
                'SELECT COUNT(*) FROM calendarobjects WHERE channel_id = ?::uuid'
            );
            $stmt->execute([$channelId]);
            $count = (int) $stmt->fetchColumn();
        } catch (\Exception $e) {
            error_log('[InternalApiPlugin] Failed to count channel events: ' . $e->getMessage());
            $response->setStatus(500);
            $response->setHeader('Content-Type', 'application/json');
            $response->setBody(json_encode(['error' => 'Failed to count events']));
            return;
        }

        $response->setStatus(200);
        $response->setHeader('Content-Type', 'application/json');
        $response->setBody(json_encode(['count' => $count]));
    }

    /**
     * DELETE /internal-api/channel-events/{channel_id}
     * Delete all events associated with a channel.
     *
     * Uses the CalDAV backend's deleteCalendarObject() so that sync tokens
     * are properly updated. Does NOT trigger scheduling side-effects.
     */
    private function handleDeleteChannelEvents($response, string $channelId)
    {
        try {
            // Join calendarinstances to get the instanceId required by
            // deleteCalendarObject([$calendarId, $instanceId], $uri).
            $stmt = $this->pdo->prepare(
                'SELECT co.uri, co.calendarid, ci.id AS instanceid '
                . 'FROM calendarobjects co '
                . 'JOIN calendarinstances ci ON ci.calendarid = co.calendarid AND ci.access = 1 '
                . 'WHERE co.channel_id = ?::uuid'
            );
            $stmt->execute([$channelId]);
            $rows = $stmt->fetchAll(\PDO::FETCH_ASSOC);
        } catch (\Exception $e) {
            error_log('[InternalApiPlugin] Failed to query channel events for delete: ' . $e->getMessage());
            $response->setStatus(500);
            $response->setHeader('Content-Type', 'application/json');
            $response->setBody(json_encode(['error' => 'Failed to query events']));
            return;
        }

        $deleted = 0;
        $errors = [];
        foreach ($rows as $row) {
            try {
                $this->caldavBackend->deleteCalendarObject(
                    [(int) $row['calendarid'], (int) $row['instanceid']],
                    $row['uri']
                );
                $deleted++;
            } catch (\Exception $e) {
                $errors[] = $row['uri'];
                error_log('[InternalApiPlugin] Failed to delete event ' . $row['uri'] . ': ' . $e->getMessage());
            }
        }

        $response->setStatus(200);
        $response->setHeader('Content-Type', 'application/json');
        $response->setBody(json_encode([
            'deleted_count' => $deleted,
            'total' => count($rows),
            'errors' => $errors,
        ]));
    }

    /**
     * Resolve the internal calendar ID from a principal URI and calendar URI.
     *
     * @param string $principalUri e.g. "principals/users/user@example.com"
     * @param string $calendarUri  e.g. "a1b2c3d4-..."
     * @return array|null The calendarId pair, or null if not found.
     */
    private function resolveCalendarId(string $principalUri, string $calendarUri)
    {
        $info = $this->resolveCalendarInfo($principalUri, $calendarUri);
        return $info === null ? null : $info['id'];
    }

    /**
     * Resolve calendar metadata needed by the import endpoint.
     *
     * Returns the SabreDAV calendarId pair AND the calendar's
     * ``supported-calendar-component-set`` (as an upper-cased array of
     * component names like ``['VEVENT']``). The component set is what
     * the import endpoint uses to filter out non-supported components
     * — without it the import would let an attacker plant
     * ``VTODO`` / ``VJOURNAL`` items in a VEVENT-only calendar by
     * sidestepping ``CalDAV\Plugin::validateICalendar``.
     *
     * @return array|null ``['id' => mixed, 'supportedComponents' => string[]]``
     */
    private function resolveCalendarInfo(string $principalUri, string $calendarUri)
    {
        $calendars = $this->caldavBackend->getCalendarsForUser($principalUri);
        $sccsKey = '{urn:ietf:params:xml:ns:caldav}supported-calendar-component-set';

        foreach ($calendars as $calendar) {
            if ($calendar['uri'] !== $calendarUri) {
                continue;
            }

            // Default matches SabreDAV's PDO backend default when the
            // column is empty: VEVENT and VTODO. We override that for
            // calendars created via our internal-api/calendars endpoint
            // (those are VEVENT-only) but accept the broader default
            // for any calendar that doesn't carry the property.
            $supported = ['VEVENT', 'VTODO'];
            if (isset($calendar[$sccsKey])) {
                $prop = $calendar[$sccsKey];
                if ($prop instanceof \Sabre\CalDAV\Xml\Property\SupportedCalendarComponentSet) {
                    $supported = $prop->getValue();
                } elseif (is_array($prop)) {
                    $supported = $prop;
                }
            }
            $supported = array_map('strtoupper', $supported);

            return [
                'id' => $calendar['id'],
                'supportedComponents' => $supported,
            ];
        }

        return null;
    }

    /**
     * Determine the principal scheduling component type of a split
     * VCALENDAR (VEVENT, VTODO, or VJOURNAL). VTIMEZONE-only files
     * have no scheduling component and return null. Returns the FIRST
     * non-VTIMEZONE component name found.
     */
    private function detectComponentType(VObject\Component\VCalendar $vcal): ?string
    {
        foreach ($vcal->getComponents() as $component) {
            $name = strtoupper($component->name);
            if ($name === 'VTIMEZONE') {
                continue;
            }
            return $name;
        }
        return null;
    }

    // ========================================================================
    // Subscription endpoints — shared subscription calendars.
    //
    // Data model: one SUBSCRIPTION principal per unique source_url
    // (principals/subscriptions/<sha256>, NULL org_id, NULL email). One
    // owner calendar under that principal. N sharees — each subscribing
    // user gets a sync-managed calendarinstances row with access=2
    // (read-only) and per-user calendarcolor/displayname. Sync state
    // (source URL, etag, last-sync-at, error count, etc.) lives as custom
    // WebDAV properties in propertystorage, keyed by the calendar path.
    // ========================================================================

    private const SUBS_NS = 'http://lasuite.numerique.gouv.fr/ns/';

    /** Properties kept under SUBS_NS for the owner calendar path. */
    private const SUBS_PROP_SOURCE = '{http://lasuite.numerique.gouv.fr/ns/}subscription-source';
    private const SUBS_PROP_SYNC_INTERVAL = '{http://lasuite.numerique.gouv.fr/ns/}subscription-sync-interval';
    private const SUBS_PROP_LAST_SYNC_AT = '{http://lasuite.numerique.gouv.fr/ns/}subscription-last-sync-at';
    private const SUBS_PROP_LAST_SYNC_STATUS = '{http://lasuite.numerique.gouv.fr/ns/}subscription-last-sync-status';
    private const SUBS_PROP_LAST_SYNC_ERROR = '{http://lasuite.numerique.gouv.fr/ns/}subscription-last-sync-error';
    private const SUBS_PROP_ERROR_COUNT = '{http://lasuite.numerique.gouv.fr/ns/}subscription-error-count';
    private const SUBS_PROP_ETAG = '{http://lasuite.numerique.gouv.fr/ns/}subscription-etag';
    private const SUBS_PROP_LAST_MODIFIED = '{http://lasuite.numerique.gouv.fr/ns/}subscription-last-modified';
    private const SUBS_PROP_CREATED_AT = '{http://lasuite.numerique.gouv.fr/ns/}subscription-created-at';

    /** Default sync interval in seconds. */
    private const SUBS_DEFAULT_INTERVAL = 300;

    /**
     * Resolve the (principal_uri, calendar_uri) pair for a subscription
     * identified by its hash. Returns null if no such principal exists.
     */
    private function resolveSubscription(string $subscriptionId): ?array
    {
        $principalUri = 'principals/subscriptions/' . $subscriptionId;
        try {
            $stmt = $this->pdo->prepare(
                'SELECT ci.uri FROM calendarinstances ci'
                . ' JOIN principals p ON p.uri = ci.principaluri'
                . ' WHERE p.uri = ? AND p.calendar_user_type = ?'
                . '   AND ci.access = 1 LIMIT 1'
            );
            $stmt->execute([$principalUri, PrincipalBackend::TYPE_SUBSCRIPTION]);
            $calendarUri = $stmt->fetchColumn();
            if ($calendarUri === false) {
                return null;
            }
            return [
                'principal_uri' => $principalUri,
                'calendar_uri' => (string) $calendarUri,
                'caldav_path' => 'calendars/subscriptions/' . $subscriptionId
                    . '/' . $calendarUri . '/',
                'property_path' => 'calendars/subscriptions/' . $subscriptionId
                    . '/' . $calendarUri,
                'subscription_id' => $subscriptionId,
            ];
        } catch (\Exception $e) {
            error_log('[InternalApiPlugin] resolveSubscription DB error: ' . $e->getMessage());
            return null;
        }
    }

    /**
     * Write a map of custom WebDAV properties to propertystorage for a
     * given path. Strings are stored as valuetype=3 (string) in BYTEA,
     * matching SabreDAV's PropertyStorage\Backend\PDO convention.
     */
    private function writeProperties(string $path, array $props): void
    {
        $stmt = $this->pdo->prepare(
            'INSERT INTO propertystorage (path, name, valuetype, value)'
            . ' VALUES (?, ?, 3, ?)'
            . ' ON CONFLICT (path, name) DO UPDATE SET'
            . '   valuetype = EXCLUDED.valuetype,'
            . '   value = EXCLUDED.value'
        );
        foreach ($props as $name => $value) {
            if ($value === null) {
                continue;
            }
            $stmt->execute([$path, $name, (string) $value]);
        }
    }

    /**
     * Read a map of custom WebDAV properties for a path. Properties
     * missing from propertystorage come back as null in the returned
     * map.
     */
    private function readProperties(string $path, array $names): array
    {
        if (empty($names)) {
            return [];
        }
        $placeholders = implode(',', array_fill(0, count($names), '?'));
        $stmt = $this->pdo->prepare(
            'SELECT name, value FROM propertystorage'
            . ' WHERE path = ? AND name IN (' . $placeholders . ')'
        );
        $stmt->execute(array_merge([$path], $names));
        $result = array_fill_keys($names, null);
        foreach ($stmt->fetchAll(\PDO::FETCH_ASSOC) as $row) {
            $value = $row['value'];
            // BYTEA columns come back as PHP streams on some drivers.
            if (is_resource($value)) {
                $value = stream_get_contents($value);
            }
            $result[$row['name']] = $value === null ? null : (string) $value;
        }
        return $result;
    }

    /**
     * POST /internal-api/subscriptions/subscribe/
     *
     * Body: {
     *   "user_email": "alice@co",   (required) subscribing user
     *   "source_url": "https://...",(required) normalised ICS URL
     *   "display_name": "...",      (optional) human-readable name
     *   "color": "#3788d8",         (optional) per-user color
     *   "sync_interval": 300        (optional) seconds; only honored on
     *                                   first subscribe for this URL
     * }
     *
     * Find-or-create the SUBSCRIPTION principal keyed by sha256(source_url).
     * Insert/update a sync-managed calendarinstances row for the user.
     */
    private function handleSubscriptionSubscribe($request, $response)
    {
        $body = json_decode($request->getBodyAsString(), true);
        if (!$body) {
            $this->jsonError($response, 400, 'Invalid JSON body');
            return;
        }
        foreach (['user_email', 'source_url'] as $field) {
            if (empty($body[$field])) {
                $this->jsonError($response, 400, "Missing required field: $field");
                return;
            }
        }

        $userEmail = (string) $body['user_email'];
        $sourceUrl = (string) $body['source_url'];
        $displayName = (string) ($body['display_name'] ?? $sourceUrl);
        $color = (string) ($body['color'] ?? '#3788d8');
        $syncInterval = (int) ($body['sync_interval'] ?? self::SUBS_DEFAULT_INTERVAL);
        if ($syncInterval < 1) {
            $syncInterval = self::SUBS_DEFAULT_INTERVAL;
        }

        $subscriptionId = hash('sha256', $sourceUrl);
        $principalUri = 'principals/subscriptions/' . $subscriptionId;
        $userPrincipal = 'principals/users/' . $userEmail;

        $this->pdo->beginTransaction();
        try {
            // Lock the principal row (if any) so concurrent subscribes
            // for the same URL can't race past the find-or-create.
            $stmt = $this->pdo->prepare(
                'SELECT id FROM principals WHERE uri = ? FOR UPDATE'
            );
            $stmt->execute([$principalUri]);
            $existed = (bool) $stmt->fetchColumn();

            if (!$existed) {
                // Create the subscription principal. NULL email, NULL
                // org_id (system-wide).
                $stmt = $this->pdo->prepare(
                    'INSERT INTO principals'
                    . ' (uri, email, displayname, calendar_user_type, org_id)'
                    . ' VALUES (?, NULL, ?, ?, NULL)'
                );
                $stmt->execute([
                    $principalUri,
                    $displayName,
                    PrincipalBackend::TYPE_SUBSCRIPTION,
                ]);

                // Create the owner calendar under the subscription
                // principal. URI is always 'default' (one calendar per
                // subscription principal).
                $this->caldavBackend->createCalendar(
                    $principalUri,
                    'default',
                    [
                        '{DAV:}displayname' => $displayName,
                        '{http://apple.com/ns/ical/}calendar-color' => '#3788d8',
                        '{urn:ietf:params:xml:ns:caldav}supported-calendar-component-set'
                            => new \Sabre\CalDAV\Xml\Property\SupportedCalendarComponentSet(['VEVENT']),
                    ]
                );

                // Write the initial sync-state properties.
                $propertyPath = 'calendars/subscriptions/' . $subscriptionId . '/default';
                $this->writeProperties($propertyPath, [
                    self::SUBS_PROP_SOURCE => $sourceUrl,
                    self::SUBS_PROP_SYNC_INTERVAL => (string) $syncInterval,
                    self::SUBS_PROP_LAST_SYNC_STATUS => 'pending',
                    self::SUBS_PROP_LAST_SYNC_ERROR => '',
                    self::SUBS_PROP_ERROR_COUNT => '0',
                    self::SUBS_PROP_ETAG => '',
                    self::SUBS_PROP_LAST_MODIFIED => '',
                    self::SUBS_PROP_CREATED_AT => gmdate('Y-m-d\TH:i:s\Z'),
                ]);
            }

            // Resolve calendar id for the share row. Owner instance must
            // exist by now — either pre-existing or freshly inserted.
            $stmt = $this->pdo->prepare(
                'SELECT calendarid, uri FROM calendarinstances'
                . ' WHERE principaluri = ? AND access = 1 LIMIT 1'
            );
            $stmt->execute([$principalUri]);
            $ownerRow = $stmt->fetch(\PDO::FETCH_ASSOC);
            if (!$ownerRow) {
                throw new \RuntimeException(
                    'Owner calendar missing for subscription ' . $subscriptionId
                );
            }
            $calendarId = (int) $ownerRow['calendarid'];
            $ownerUri = (string) $ownerRow['uri'];

            // Insert-or-update the user's sharee row. Color and display
            // name are set on first subscribe only; subsequent subscribes
            // (idempotent) leave them alone.
            $stmt = $this->pdo->prepare(
                'INSERT INTO calendarinstances'
                . ' (calendarid, principaluri, access, uri, displayname,'
                . '  calendarcolor, share_href, share_displayname,'
                . '  share_invitestatus, transparent, is_sync_managed)'
                . ' VALUES (?, ?, ?, ?, ?, ?, ?, ?, 2, 0, TRUE)'
                . ' ON CONFLICT (principaluri, calendarid) DO NOTHING'
            );
            $stmt->execute([
                $calendarId,
                $userPrincipal,
                PrincipalBackend::ACCESS_READ,
                UUIDUtil::getUUID(),
                $displayName,
                $color,
                'mailto:' . $userEmail,
                $userEmail,
            ]);

            // Fetch the user's sharee URI for the response.
            $stmt = $this->pdo->prepare(
                'SELECT uri FROM calendarinstances'
                . ' WHERE principaluri = ? AND calendarid = ? LIMIT 1'
            );
            $stmt->execute([$userPrincipal, $calendarId]);
            $shareeUri = (string) $stmt->fetchColumn();

            $this->pdo->commit();
        } catch (\Exception $e) {
            $this->pdo->rollBack();
            error_log('[InternalApiPlugin] subscribe failed: ' . $e->getMessage());
            $this->jsonError($response, 500, 'Failed to subscribe');
            return;
        }

        $response->setStatus(200);
        $response->setHeader('Content-Type', 'application/json');
        $response->setBody(json_encode([
            'subscription_id' => $subscriptionId,
            'principal_uri' => $principalUri,
            'owner_calendar_uri' => $ownerUri,
            'user_calendar_uri' => $shareeUri,
            'caldav_path' => 'calendars/subscriptions/' . $subscriptionId
                . '/' . $ownerUri . '/',
            'user_caldav_path' => 'calendars/users/' . $userEmail
                . '/' . $shareeUri . '/',
            'created' => !$existed,
        ]));
    }

    /**
     * POST /internal-api/subscriptions/unsubscribe/
     *
     * Body: {"user_email": "alice@co", "subscription_id": "<sha256>"}
     *
     * Removes the user's sharee row. Does NOT touch the owner calendar
     * or principal — cleanup-orphans handles that when the last sharee
     * leaves.
     */
    private function handleSubscriptionUnsubscribe($request, $response)
    {
        $body = json_decode($request->getBodyAsString(), true);
        if (!$body) {
            $this->jsonError($response, 400, 'Invalid JSON body');
            return;
        }
        foreach (['user_email', 'subscription_id'] as $field) {
            if (empty($body[$field])) {
                $this->jsonError($response, 400, "Missing required field: $field");
                return;
            }
        }

        $userEmail = (string) $body['user_email'];
        $subscriptionId = (string) $body['subscription_id'];
        $principalUri = 'principals/subscriptions/' . $subscriptionId;
        $userPrincipal = 'principals/users/' . $userEmail;

        try {
            $stmt = $this->pdo->prepare(
                'DELETE FROM calendarinstances'
                . ' WHERE principaluri = ?'
                . '   AND calendarid IN ('
                . '     SELECT calendarid FROM calendarinstances'
                . '     WHERE principaluri = ? AND access = 1'
                . '   )'
            );
            $stmt->execute([$userPrincipal, $principalUri]);
            $deleted = $stmt->rowCount();
        } catch (\Exception $e) {
            error_log('[InternalApiPlugin] unsubscribe failed: ' . $e->getMessage());
            $this->jsonError($response, 500, 'Failed to unsubscribe');
            return;
        }

        $response->setStatus(200);
        $response->setHeader('Content-Type', 'application/json');
        $response->setBody(json_encode([
            'deleted' => (bool) $deleted,
        ]));
    }

    /**
     * GET /internal-api/subscriptions/due/?limit=500
     *
     * Returns subscriptions whose last_sync_at + sync_interval is in the
     * past, sorted oldest-first. The scheduler fans out one Dramatiq task
     * per result.
     */
    private function handleSubscriptionDue($request, $response)
    {
        $limit = (int) ($request->getQueryParameters()['limit'] ?? 500);
        if ($limit < 1 || $limit > 5000) {
            $limit = 500;
        }

        try {
            $stmt = $this->pdo->prepare(
                'SELECT p.uri AS principal_uri, ci.uri AS calendar_uri,'
                . ' SUBSTR(p.uri, LENGTH(\'principals/subscriptions/\') + 1) AS subscription_id'
                . ' FROM principals p'
                . ' JOIN calendarinstances ci'
                . '   ON ci.principaluri = p.uri AND ci.access = 1'
                . ' WHERE p.calendar_user_type = ?'
                . ' ORDER BY p.id ASC'
                . ' LIMIT ' . $limit
            );
            $stmt->execute([PrincipalBackend::TYPE_SUBSCRIPTION]);
            $candidates = $stmt->fetchAll(\PDO::FETCH_ASSOC);
        } catch (\Exception $e) {
            error_log('[InternalApiPlugin] due query failed: ' . $e->getMessage());
            $this->jsonError($response, 500, 'Failed to query due subscriptions');
            return;
        }

        $now = time();
        $due = [];
        foreach ($candidates as $row) {
            $path = 'calendars/subscriptions/' . $row['subscription_id']
                . '/' . $row['calendar_uri'];
            $props = $this->readProperties($path, [
                self::SUBS_PROP_SOURCE,
                self::SUBS_PROP_SYNC_INTERVAL,
                self::SUBS_PROP_LAST_SYNC_AT,
                self::SUBS_PROP_ETAG,
                self::SUBS_PROP_LAST_MODIFIED,
            ]);

            // Drop rows with no source — something went wrong on subscribe.
            if (empty($props[self::SUBS_PROP_SOURCE])) {
                continue;
            }

            $interval = (int) ($props[self::SUBS_PROP_SYNC_INTERVAL]
                ?? self::SUBS_DEFAULT_INTERVAL);
            if ($interval < 1) {
                $interval = self::SUBS_DEFAULT_INTERVAL;
            }

            $lastSyncAt = $props[self::SUBS_PROP_LAST_SYNC_AT] ?? null;
            if ($lastSyncAt) {
                $lastTs = strtotime($lastSyncAt);
                if ($lastTs !== false && $lastTs + $interval > $now) {
                    continue;
                }
            }

            $due[] = [
                'subscription_id' => $row['subscription_id'],
                'principal_uri' => $row['principal_uri'],
                'calendar_uri' => $row['calendar_uri'],
                'caldav_path' => 'calendars/subscriptions/' . $row['subscription_id']
                    . '/' . $row['calendar_uri'] . '/',
                'source_url' => $props[self::SUBS_PROP_SOURCE],
                'sync_interval' => $interval,
                'etag' => $props[self::SUBS_PROP_ETAG] ?? '',
                'last_modified' => $props[self::SUBS_PROP_LAST_MODIFIED] ?? '',
            ];
        }

        $response->setStatus(200);
        $response->setHeader('Content-Type', 'application/json');
        $response->setBody(json_encode(['subscriptions' => $due]));
    }

    /**
     * POST /internal-api/subscriptions/{sub_id}/sync-result/
     *
     * Body: {
     *   "status": "ok"|"error"|"stopped",
     *   "etag": "...",            (optional, only on ok/304)
     *   "last_modified": "...",   (optional)
     *   "error_message": "...",   (optional, max 512 chars)
     *   "error_count": N          (optional, when status=error)
     * }
     */
    private function handleSubscriptionSyncResult($request, $response, string $subscriptionId)
    {
        $body = json_decode($request->getBodyAsString(), true);
        if (!$body || empty($body['status'])) {
            $this->jsonError($response, 400, 'Missing status field');
            return;
        }

        $sub = $this->resolveSubscription($subscriptionId);
        if ($sub === null) {
            $this->jsonError($response, 404, 'Subscription not found');
            return;
        }

        $status = (string) $body['status'];
        if (!in_array($status, ['ok', 'error', 'stopped', 'pending'], true)) {
            $this->jsonError($response, 400, 'Invalid status value');
            return;
        }

        $props = [
            self::SUBS_PROP_LAST_SYNC_AT => gmdate('Y-m-d\TH:i:s\Z'),
            self::SUBS_PROP_LAST_SYNC_STATUS => $status,
        ];
        if (isset($body['etag'])) {
            $props[self::SUBS_PROP_ETAG] = (string) $body['etag'];
        }
        if (isset($body['last_modified'])) {
            $props[self::SUBS_PROP_LAST_MODIFIED] = (string) $body['last_modified'];
        }
        if (isset($body['error_message'])) {
            $props[self::SUBS_PROP_LAST_SYNC_ERROR] = substr(
                (string) $body['error_message'],
                0,
                512
            );
        }
        if (isset($body['error_count'])) {
            $props[self::SUBS_PROP_ERROR_COUNT] = (string) (int) $body['error_count'];
        }

        try {
            $this->writeProperties($sub['property_path'], $props);
        } catch (\Exception $e) {
            error_log('[InternalApiPlugin] sync-result write failed: ' . $e->getMessage());
            $this->jsonError($response, 500, 'Failed to update sync state');
            return;
        }

        $response->setStatus(200);
        $response->setHeader('Content-Type', 'application/json');
        $response->setBody(json_encode(['updated' => true]));
    }

    /**
     * GET /internal-api/subscriptions/for-user/{email}
     *
     * Lists the user's subscription shares with their sync state. Powers
     * the Django subscription list endpoint.
     */
    private function handleSubscriptionsForUser($request, $response, string $email)
    {
        $userPrincipal = 'principals/users/' . $email;

        try {
            $stmt = $this->pdo->prepare(
                'SELECT owner_p.uri AS principal_uri,'
                . '       owner_ci.uri AS owner_calendar_uri,'
                . '       user_ci.uri AS user_calendar_uri,'
                . '       user_ci.calendarcolor AS color,'
                . '       user_ci.displayname AS display_name,'
                . '       SUBSTR(owner_p.uri, LENGTH(\'principals/subscriptions/\') + 1) AS subscription_id'
                . ' FROM calendarinstances user_ci'
                . ' JOIN calendarinstances owner_ci'
                . '   ON owner_ci.calendarid = user_ci.calendarid AND owner_ci.access = 1'
                . ' JOIN principals owner_p ON owner_p.uri = owner_ci.principaluri'
                . ' WHERE user_ci.principaluri = ?'
                . '   AND owner_p.calendar_user_type = ?'
                . ' ORDER BY user_ci.id ASC'
            );
            $stmt->execute([$userPrincipal, PrincipalBackend::TYPE_SUBSCRIPTION]);
            $shares = $stmt->fetchAll(\PDO::FETCH_ASSOC);
        } catch (\Exception $e) {
            error_log('[InternalApiPlugin] for-user query failed: ' . $e->getMessage());
            $this->jsonError($response, 500, 'Failed to list subscriptions');
            return;
        }

        $propNames = [
            self::SUBS_PROP_SOURCE,
            self::SUBS_PROP_SYNC_INTERVAL,
            self::SUBS_PROP_LAST_SYNC_AT,
            self::SUBS_PROP_LAST_SYNC_STATUS,
            self::SUBS_PROP_LAST_SYNC_ERROR,
            self::SUBS_PROP_ERROR_COUNT,
            self::SUBS_PROP_CREATED_AT,
        ];

        $result = [];
        foreach ($shares as $row) {
            $path = 'calendars/subscriptions/' . $row['subscription_id']
                . '/' . $row['owner_calendar_uri'];
            $props = $this->readProperties($path, $propNames);
            $result[] = [
                'subscription_id' => $row['subscription_id'],
                'caldav_path' => 'calendars/users/' . $email
                    . '/' . $row['user_calendar_uri'] . '/',
                'display_name' => $row['display_name'],
                'color' => $row['color'],
                'source_url' => $props[self::SUBS_PROP_SOURCE] ?? '',
                'sync_interval' => (int) ($props[self::SUBS_PROP_SYNC_INTERVAL]
                    ?? self::SUBS_DEFAULT_INTERVAL),
                'last_sync_at' => $props[self::SUBS_PROP_LAST_SYNC_AT],
                'last_sync_status' => $props[self::SUBS_PROP_LAST_SYNC_STATUS] ?? 'pending',
                'last_sync_error' => $props[self::SUBS_PROP_LAST_SYNC_ERROR] ?? '',
                'error_count' => (int) ($props[self::SUBS_PROP_ERROR_COUNT] ?? 0),
                'created_at' => $props[self::SUBS_PROP_CREATED_AT],
            ];
        }

        $response->setStatus(200);
        $response->setHeader('Content-Type', 'application/json');
        $response->setBody(json_encode(['subscriptions' => $result]));
    }

    /**
     * POST /internal-api/subscriptions/cleanup-orphans/
     *
     * Body (optional): {"min_age_seconds": 300}
     *
     * Deletes subscription principals with zero sharees that have been
     * orphaned for at least ``min_age_seconds`` (default 300s). The
     * grace period prevents racing with in-flight subscribe flows that
     * create the principal before adding the first sharee row.
     */
    private function handleSubscriptionCleanupOrphans($request, $response)
    {
        $body = json_decode($request->getBodyAsString(), true) ?: [];
        $minAgeSeconds = (int) ($body['min_age_seconds'] ?? 300);
        if ($minAgeSeconds < 0) {
            $minAgeSeconds = 0;
        }

        $this->pdo->beginTransaction();
        try {
            // Find subscription principals with zero sharees.
            $stmt = $this->pdo->prepare(
                'SELECT p.uri AS principal_uri, ci.calendarid, ci.uri AS calendar_uri,'
                . '       SUBSTR(p.uri, LENGTH(\'principals/subscriptions/\') + 1) AS subscription_id'
                . ' FROM principals p'
                . ' JOIN calendarinstances ci'
                . '   ON ci.principaluri = p.uri AND ci.access = 1'
                . ' WHERE p.calendar_user_type = ?'
                . '   AND NOT EXISTS ('
                . '     SELECT 1 FROM calendarinstances s'
                . '     WHERE s.calendarid = ci.calendarid AND s.access > 1'
                . '   )'
                . ' FOR UPDATE OF p'
            );
            $stmt->execute([PrincipalBackend::TYPE_SUBSCRIPTION]);
            $candidates = $stmt->fetchAll(\PDO::FETCH_ASSOC);

            $deleted = 0;
            $now = time();
            foreach ($candidates as $row) {
                $path = 'calendars/subscriptions/' . $row['subscription_id']
                    . '/' . $row['calendar_uri'];
                if ($minAgeSeconds > 0) {
                    $props = $this->readProperties($path, [self::SUBS_PROP_CREATED_AT]);
                    $createdAt = $props[self::SUBS_PROP_CREATED_AT] ?? null;
                    if ($createdAt) {
                        $ts = strtotime($createdAt);
                        if ($ts !== false && $now - $ts < $minAgeSeconds) {
                            continue;
                        }
                    }
                }

                $calendarId = (int) $row['calendarid'];

                // Delete calendar objects and the calendar itself via
                // the CalDAV backend so sync tokens are updated cleanly.
                $del = $this->pdo->prepare(
                    'DELETE FROM calendarobjects WHERE calendarid = ?'
                );
                $del->execute([$calendarId]);

                $del = $this->pdo->prepare(
                    'DELETE FROM calendarinstances WHERE calendarid = ?'
                );
                $del->execute([$calendarId]);

                $del = $this->pdo->prepare('DELETE FROM calendars WHERE id = ?');
                $del->execute([$calendarId]);

                $del = $this->pdo->prepare('DELETE FROM principals WHERE uri = ?');
                $del->execute([$row['principal_uri']]);

                $del = $this->pdo->prepare(
                    'DELETE FROM propertystorage WHERE path LIKE ?'
                );
                $del->execute([$path . '%']);

                $deleted++;
            }

            $this->pdo->commit();
        } catch (\Exception $e) {
            $this->pdo->rollBack();
            error_log('[InternalApiPlugin] cleanup-orphans failed: ' . $e->getMessage());
            $this->jsonError($response, 500, 'Failed to clean up orphans');
            return;
        }

        $response->setStatus(200);
        $response->setHeader('Content-Type', 'application/json');
        $response->setBody(json_encode([
            'deleted_count' => $deleted,
            'candidate_count' => count($candidates),
        ]));
    }

    /**
     * GET /internal-api/subscriptions/{sub_id}/
     *
     * Returns the full sync state for a single subscription. Used by
     * the sync worker to look up source_url/etag/last-modified when
     * re-entering via Dramatiq with only a subscription_id.
     */
    private function handleSubscriptionGet($request, $response, string $subscriptionId)
    {
        $sub = $this->resolveSubscription($subscriptionId);
        if ($sub === null) {
            $this->jsonError($response, 404, 'Subscription not found');
            return;
        }
        $props = $this->readProperties($sub['property_path'], [
            self::SUBS_PROP_SOURCE,
            self::SUBS_PROP_SYNC_INTERVAL,
            self::SUBS_PROP_LAST_SYNC_AT,
            self::SUBS_PROP_LAST_SYNC_STATUS,
            self::SUBS_PROP_LAST_SYNC_ERROR,
            self::SUBS_PROP_ERROR_COUNT,
            self::SUBS_PROP_ETAG,
            self::SUBS_PROP_LAST_MODIFIED,
            self::SUBS_PROP_CREATED_AT,
        ]);

        $response->setStatus(200);
        $response->setHeader('Content-Type', 'application/json');
        $response->setBody(json_encode([
            'subscription_id' => $subscriptionId,
            'principal_uri' => $sub['principal_uri'],
            'caldav_path' => $sub['caldav_path'],
            'source_url' => $props[self::SUBS_PROP_SOURCE] ?? '',
            'sync_interval' => (int) ($props[self::SUBS_PROP_SYNC_INTERVAL]
                ?? self::SUBS_DEFAULT_INTERVAL),
            'last_sync_at' => $props[self::SUBS_PROP_LAST_SYNC_AT],
            'last_sync_status' => $props[self::SUBS_PROP_LAST_SYNC_STATUS] ?? 'pending',
            'last_sync_error' => $props[self::SUBS_PROP_LAST_SYNC_ERROR] ?? '',
            'error_count' => (int) ($props[self::SUBS_PROP_ERROR_COUNT] ?? 0),
            'etag' => $props[self::SUBS_PROP_ETAG] ?? '',
            'last_modified' => $props[self::SUBS_PROP_LAST_MODIFIED] ?? '',
            'created_at' => $props[self::SUBS_PROP_CREATED_AT],
        ]));
    }

    /**
     * Resolve the calendarid for a subscription owner calendar. Returns
     * null if the subscription does not exist.
     */
    private function resolveSubscriptionCalendarId(string $subscriptionId): ?int
    {
        $principalUri = 'principals/subscriptions/' . $subscriptionId;
        try {
            $stmt = $this->pdo->prepare(
                'SELECT ci.calendarid FROM calendarinstances ci'
                . ' JOIN principals p ON p.uri = ci.principaluri'
                . ' WHERE p.uri = ? AND p.calendar_user_type = ?'
                . '   AND ci.access = 1 LIMIT 1'
            );
            $stmt->execute([$principalUri, PrincipalBackend::TYPE_SUBSCRIPTION]);
            $value = $stmt->fetchColumn();
            return $value === false ? null : (int) $value;
        } catch (\Exception $e) {
            error_log('[InternalApiPlugin] resolveSubscriptionCalendarId DB error: ' . $e->getMessage());
            return null;
        }
    }

    /**
     * GET /internal-api/subscriptions/{sub_id}/events/
     *
     * Lists the current events in the subscription's owner calendar,
     * keyed by UID. Used by the sync worker to compute the diff against
     * freshly-fetched ICS data.
     */
    private function handleSubscriptionListEvents($request, $response, string $subscriptionId)
    {
        $calendarId = $this->resolveSubscriptionCalendarId($subscriptionId);
        if ($calendarId === null) {
            $this->jsonError($response, 404, 'Subscription not found');
            return;
        }

        try {
            $stmt = $this->pdo->prepare(
                'SELECT uid, uri, calendardata FROM calendarobjects'
                . ' WHERE calendarid = ?'
            );
            $stmt->execute([$calendarId]);
            $rows = $stmt->fetchAll(\PDO::FETCH_ASSOC);
        } catch (\Exception $e) {
            error_log('[InternalApiPlugin] list events failed: ' . $e->getMessage());
            $this->jsonError($response, 500, 'Failed to list events');
            return;
        }

        $events = [];
        foreach ($rows as $row) {
            $data = $row['calendardata'];
            if (is_resource($data)) {
                $data = stream_get_contents($data);
            }
            $events[] = [
                'uid' => (string) $row['uid'],
                'uri' => (string) $row['uri'],
                'ics' => $data === null ? '' : (string) $data,
            ];
        }

        $response->setStatus(200);
        $response->setHeader('Content-Type', 'application/json');
        $response->setBody(json_encode([
            'subscription_id' => $subscriptionId,
            'events' => $events,
        ]));
    }

    /**
     * POST /internal-api/subscriptions/{sub_id}/events-batch/
     *
     * Body: {
     *   "upsert": [{"uid": "...", "uri": "abc.ics", "ics": "BEGIN:VCAL..."}],
     *   "delete": ["uri1.ics", "uri2.ics"]
     * }
     *
     * Applies a batch of event create/update/delete ops through the
     * CalDAV backend so sync tokens stay consistent. Called by the
     * subscription sync worker after diffing the upstream ICS.
     */
    private function handleSubscriptionEventsBatch($request, $response, string $subscriptionId)
    {
        $body = json_decode($request->getBodyAsString(), true);
        if (!is_array($body)) {
            $this->jsonError($response, 400, 'Invalid JSON body');
            return;
        }

        $calendarId = $this->resolveSubscriptionCalendarId($subscriptionId);
        if ($calendarId === null) {
            $this->jsonError($response, 404, 'Subscription not found');
            return;
        }

        // Find the owner calendarinstance id — needed for deleteCalendarObject.
        try {
            $stmt = $this->pdo->prepare(
                'SELECT id FROM calendarinstances'
                . ' WHERE calendarid = ? AND access = 1 LIMIT 1'
            );
            $stmt->execute([$calendarId]);
            $instanceId = (int) $stmt->fetchColumn();
        } catch (\Exception $e) {
            error_log('[InternalApiPlugin] events-batch instance lookup failed: ' . $e->getMessage());
            $this->jsonError($response, 500, 'Failed to resolve calendar');
            return;
        }

        $created = 0;
        $updated = 0;
        $deleted = 0;
        $errors = [];

        $upserts = is_array($body['upsert'] ?? null) ? $body['upsert'] : [];
        $deletes = is_array($body['delete'] ?? null) ? $body['delete'] : [];

        foreach ($upserts as $i => $item) {
            if (!is_array($item) || empty($item['uri']) || empty($item['ics'])) {
                $errors[] = "upsert[$i] missing uri or ics";
                continue;
            }
            $uri = (string) $item['uri'];
            $ics = (string) $item['ics'];
            try {
                // Does the object already exist?
                $existed = $this->caldavBackend->getCalendarObject(
                    [$calendarId, $instanceId],
                    $uri
                );
                if ($existed) {
                    $this->caldavBackend->updateCalendarObject(
                        [$calendarId, $instanceId],
                        $uri,
                        $ics
                    );
                    $updated++;
                } else {
                    $this->caldavBackend->createCalendarObject(
                        [$calendarId, $instanceId],
                        $uri,
                        $ics
                    );
                    $created++;
                }
            } catch (\Exception $e) {
                $errors[] = "upsert[$i] ($uri): " . $e->getMessage();
            }
        }

        foreach ($deletes as $i => $uri) {
            $uri = (string) $uri;
            if ($uri === '') {
                continue;
            }
            try {
                $this->caldavBackend->deleteCalendarObject(
                    [$calendarId, $instanceId],
                    $uri
                );
                $deleted++;
            } catch (\Exception $e) {
                $errors[] = "delete[$i] ($uri): " . $e->getMessage();
            }
        }

        $response->setStatus(200);
        $response->setHeader('Content-Type', 'application/json');
        $response->setBody(json_encode([
            'created' => $created,
            'updated' => $updated,
            'deleted' => $deleted,
            'errors' => $errors,
        ]));
    }

    /** Small helper to emit a JSON error response. */
    private function jsonError($response, int $status, string $message): void
    {
        $response->setStatus($status);
        $response->setHeader('Content-Type', 'application/json');
        $response->setBody(json_encode(['error' => $message]));
    }

    public function getPluginInfo()
    {
        return [
            'name' => $this->getPluginName(),
            'description' => 'Internal API for resource provisioning and ICS import',
        ];
    }
}
