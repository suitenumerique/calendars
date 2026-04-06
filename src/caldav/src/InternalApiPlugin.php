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

        $resourceId = $body['resource_id'] ?? null;
        $name = $body['name'] ?? null;
        $email = $body['email'] ?? null;
        $resourceType = $body['resource_type'] ?? 'ROOM';
        $orgId = $body['org_id'] ?? null;

        if (!$resourceId || !$name || !$email) {
            $response->setStatus(400);
            $response->setHeader('Content-Type', 'application/json');
            $response->setBody(json_encode([
                'error' => 'Missing required fields: resource_id, name, email',
            ]));
            return false;
        }

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

        // Verify org scoping — reject if orgs don't match or either is missing
        if (!$orgId || !$row['org_id'] || $orgId !== $row['org_id']) {
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

        // Verify org scoping — reject if orgs don't match or either is missing
        if ($row['org_id']) {
            if (!$orgId || $orgId !== $row['org_id']) {
                $response->setStatus(403);
                $response->setHeader('Content-Type', 'application/json');
                $response->setBody(json_encode([
                    'error' => 'Cannot delete a user from a different organization',
                ]));
                return false;
            }
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
     * Body: {
     *   "email": "contact@company.com",       (required)
     *   "name": "Contact Team",               (optional, defaults to email)
     *   "org_id": "...",                       (optional)
     *   "calendar_user_type": "INDIVIDUAL",    (optional, default INDIVIDUAL)
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

        $email = $body['email'] ?? null;
        $name = $body['name'] ?? $email;
        $orgId = $body['org_id'] ?? null;
        $calendarUserType = $body['calendar_user_type'] ?? 'INDIVIDUAL';
        $color = $body['color'] ?? '#3788d8';

        if (!$email) {
            $response->setStatus(400);
            $response->setHeader('Content-Type', 'application/json');
            $response->setBody(json_encode(['error' => 'Missing required field: email']));
            return false;
        }

        $principalUri = 'principals/users/' . $email;

        $this->pdo->beginTransaction();
        try {
            $stmt = $this->pdo->prepare(
                'INSERT INTO principals (uri, email, displayname, calendar_user_type, org_id)'
                . ' VALUES (?, ?, ?, ?, ?)'
                . ' ON CONFLICT (uri) DO UPDATE SET'
                . ' org_id = COALESCE(EXCLUDED.org_id, principals.org_id),'
                . ' displayname = COALESCE(EXCLUDED.displayname, principals.displayname),'
                . ' calendar_user_type = EXCLUDED.calendar_user_type'
            );
            $stmt->execute([$principalUri, $email, $name, $calendarUserType, $orgId]);

            // Check if this principal already had a calendar
            $existingCalendars = $this->caldavBackend->getCalendarsForUser($principalUri);
            $isNew = empty($existingCalendars);

            if ($isNew) {
                $this->caldavBackend->createCalendar(
                    $principalUri,
                    'default',
                    [
                        '{DAV:}displayname' => $name,
                        '{http://apple.com/ns/ical/}calendar-color' => $color,
                        '{urn:ietf:params:xml:ns:caldav}supported-calendar-component-set'
                            => new \Sabre\CalDAV\Xml\Property\SupportedCalendarComponentSet(['VEVENT']),
                    ]
                );
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

        $status = $isNew ? 201 : 200;
        $response->setStatus($status);
        $response->setHeader('Content-Type', 'application/json');
        $response->setBody(json_encode([
            'principal_uri' => $principalUri,
            'email' => $email,
            'created' => $isNew,
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
     *      "calendar_uri": "default", "privilege": "read-write"},
     *     {"user_email": "bob@co", "mailbox_email": "contact@co",
     *      "calendar_uri": "default", "privilege": "read"}
     *   ],
     *   "full_sync_users": ["alice@co"]
     * }
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

        $shares = $body['shares'] ?? [];
        $fullSyncUsers = array_flip($body['full_sync_users'] ?? []);
        $privilegeMap = [
            'read' => PrincipalBackend::ACCESS_READ,
            'read-write' => PrincipalBackend::ACCESS_READ_WRITE,
        ];

        $this->pdo->beginTransaction();
        try {
            // 1. Batch-fetch all owner calendar instances (one query)
            $mailboxEmails = array_unique(
                array_filter(array_column($shares, 'mailbox_email'))
            );
            $ownerCalendars = []; // "mailbox_email:uri" → row
            if ($mailboxEmails) {
                $ownerPrincipals = array_map(
                    fn($e) => 'principals/users/' . $e,
                    $mailboxEmails
                );
                $ph = implode(',', array_fill(0, count($ownerPrincipals), '?'));
                $stmt = $this->pdo->prepare(
                    'SELECT ci.calendarid, ci.principaluri, ci.uri, ci.displayname, ci.calendarcolor '
                    . 'FROM calendarinstances ci '
                    . 'WHERE ci.principaluri IN (' . $ph . ') AND ci.access = 1'
                );
                $stmt->execute($ownerPrincipals);
                foreach ($stmt->fetchAll(\PDO::FETCH_ASSOC) as $row) {
                    $email = str_replace('principals/users/', '',$row['principaluri']);
                    $ownerCalendars[$email . ':' . $row['uri']] = $row;
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

            // 4. Group desired shares by user
            // desired[principaluri][calendarid] → {access, uri, displayname}
            $desired = [];
            $active = [];
            foreach ($shares as $share) {
                $userEmail = $share['user_email'] ?? null;
                $mailboxEmail = $share['mailbox_email'] ?? null;
                $calendarUri = $share['calendar_uri'] ?? 'default';
                $privilege = $share['privilege'] ?? 'read';
                if (!$userEmail || !$mailboxEmail) {
                    continue;
                }

                $key = $mailboxEmail . ':' . $calendarUri;
                if (!isset($ownerCalendars[$key])) {
                    continue;
                }

                $ownerCal = $ownerCalendars[$key];
                $principal = 'principals/users/' . $userEmail;
                $calendarId = (int)$ownerCal['calendarid'];
                $access = $privilegeMap[$privilege] ?? 2;

                $desired[$principal][$calendarId] = [
                    'access' => $access,
                    'displayname' => $ownerCal['displayname'],
                    'share_href' => 'mailto:' . $userEmail,
                    'share_displayname' => $userEmail,
                    'color' => $ownerCal['calendarcolor'] ?? '#3788d8',
                ];
                $active[] = [
                    'user_email' => $userEmail,
                    'mailbox_email' => $mailboxEmail,
                    'calendar_uri' => $calendarUri,
                    'privilege' => $privilege,
                ];
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

        // Look up calendarId
        $calendarId = $this->resolveCalendarId($principalUri, $calendarUri);
        if ($calendarId === null) {
            $response->setStatus(404);
            $response->setHeader('Content-Type', 'application/json');
            $response->setBody(json_encode(['error' => 'Calendar not found']));
            return false;
        }

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
        $errors = [];

        // Set audit context once before the import loop
        if ($this->caldavBackend instanceof AuditCalDAVBackend) {
            $user = $request->getHeader('X-Forwarded-User');
            if ($user) {
                $this->caldavBackend->setCurrentPrincipal($user);
            }
            $channelId = $request->getHeader('X-CalDAV-Channel-Id');
            $this->caldavBackend->setCurrentChannelId($channelId ?: null);
        }

        try {
            while ($splitVcal = $splitter->getNext()) {
                $totalEvents++;

                try {
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
            . "{$skippedCount} failed "
            . "out of {$totalEvents} total"
        );

        $response->setStatus(200);
        $response->setHeader('Content-Type', 'application/json');
        $response->setBody(json_encode([
            'total_events' => $totalEvents,
            'imported_count' => $importedCount,
            'duplicate_count' => $duplicateCount,
            'skipped_count' => $skippedCount,
            'errors' => $errors,
        ]));

        return false;
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
        $calendars = $this->caldavBackend->getCalendarsForUser($principalUri);

        foreach ($calendars as $calendar) {
            if ($calendar['uri'] === $calendarUri) {
                return $calendar['id'];
            }
        }

        return null;
    }

    public function getPluginInfo()
    {
        return [
            'name' => $this->getPluginName(),
            'description' => 'Internal API for resource provisioning and ICS import',
        ];
    }
}
