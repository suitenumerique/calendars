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
 *
 * Access control (defense in depth):
 *   1. Django proxy blocklist rejects /internal-api/ paths
 *   2. Requires X-Internal-Api-Key header (different from X-Api-Key used by proxy)
 *   3. Test coverage verifies the proxy rejects these paths
 */

namespace Calendars\SabreDav;

use Sabre\DAV\Server;
use Sabre\DAV\ServerPlugin;
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
        $headerValue = $request->getHeader('X-Internal-Api-Key');
        if (!$headerValue || !hash_equals($this->apiKey, $headerValue)) {
            $response->setStatus(403);
            $response->setHeader('Content-Type', 'application/json');
            $response->setBody(json_encode([
                'error' => 'Forbidden: missing or invalid X-Internal-Api-Key header',
            ]));
            return false;
        }

        $method = $request->getMethod();

        // Route: POST /internal-api/resources/
        if ($method === 'POST' && preg_match('#^internal-api/resources/?$#', $path)) {
            $this->handleCreateResource($request, $response);
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

        // Route: POST /internal-api/import/{principalUser}/{calendarUri}
        if ($method === 'POST' && preg_match('#^internal-api/import/([^/]+)/([^/]+)$#', $path, $matches)) {
            $this->handleImport($request, $response, urldecode($matches[1]), $matches[2]);
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
        $orgId = $request->getHeader('X-CalDAV-Organization');

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
        $orgId = $request->getHeader('X-CalDAV-Organization');

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
