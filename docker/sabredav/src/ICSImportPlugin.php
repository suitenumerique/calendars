<?php
/**
 * ICSImportPlugin - Bulk import events from a multi-event ICS file.
 *
 * Accepts a single POST with raw ICS data and splits it into individual
 * calendar objects using Sabre\VObject\Splitter\ICalendar. Each split
 * VCALENDAR is validated/repaired and inserted directly via the CalDAV
 * PDO backend, avoiding N HTTP round-trips from Python.
 *
 * The endpoint is gated by a dedicated X-Calendars-Import header so that
 * only the Python backend can call it (not future proxied CalDAV clients).
 */

namespace Calendars\SabreDav;

use Sabre\DAV\Server;
use Sabre\DAV\ServerPlugin;
use Sabre\CalDAV\Backend\PDO as CalDAVBackend;
use Sabre\VObject;

class ICSImportPlugin extends ServerPlugin
{
    /** @var Server */
    protected $server;

    /** @var CalDAVBackend */
    private $caldavBackend;

    /** @var string */
    private $importApiKey;

    public function __construct(CalDAVBackend $caldavBackend, string $importApiKey)
    {
        $this->caldavBackend = $caldavBackend;
        $this->importApiKey = $importApiKey;
    }

    public function getPluginName()
    {
        return 'ics-import';
    }

    public function initialize(Server $server)
    {
        $this->server = $server;
        // Priority 90: runs before the debug logger (50)
        $server->on('method:POST', [$this, 'httpPost'], 90);
    }

    /**
     * Handle POST requests with ?import query parameter.
     *
     * @return bool|null false to stop event propagation, null to let
     *                   other handlers proceed.
     */
    public function httpPost($request, $response)
    {
        // Only handle requests with ?import in the query string
        $queryParams = $request->getQueryParameters();
        if (!array_key_exists('import', $queryParams)) {
            return;
        }

        // Verify the dedicated import header
        $headerValue = $request->getHeader('X-Calendars-Import');
        if (!$headerValue || $headerValue !== $this->importApiKey) {
            $response->setStatus(403);
            $response->setHeader('Content-Type', 'application/json');
            $response->setBody(json_encode([
                'error' => 'Forbidden: missing or invalid X-Calendars-Import header',
            ]));
            return false;
        }

        // Resolve the calendar from the request path.
        // getPath() returns a path relative to the base URI, e.g.
        // "calendars/user@example.com/cal-uuid"
        $path = $request->getPath();
        $parts = explode('/', trim($path, '/'));

        // Expect exactly: [calendars, <user>, <calendar-uri>]
        if (count($parts) < 3 || $parts[0] !== 'calendars') {
            error_log("[ICSImportPlugin] Invalid calendar path: " . $path);
            $response->setStatus(400);
            $response->setHeader('Content-Type', 'application/json');
            $response->setBody(json_encode([
                'error' => 'Invalid calendar path',
            ]));
            return false;
        }

        $principalUser = urldecode($parts[1]);
        $calendarUri = $parts[2];
        $principalUri = 'principals/' . $principalUser;

        // Look up calendarId by iterating the user's calendars
        $calendarId = $this->resolveCalendarId($principalUri, $calendarUri);
        if ($calendarId === null) {
            $response->setStatus(404);
            $response->setHeader('Content-Type', 'application/json');
            $response->setBody(json_encode([
                'error' => 'Calendar not found',
            ]));
            return false;
        }

        // Read and parse the raw ICS body
        $icsBody = $request->getBodyAsString();
        if (empty($icsBody)) {
            $response->setStatus(400);
            $response->setHeader('Content-Type', 'application/json');
            $response->setBody(json_encode([
                'error' => 'Empty request body',
            ]));
            return false;
        }

        try {
            $vcal = VObject\Reader::read($icsBody);
        } catch (\Exception $e) {
            error_log("[ICSImportPlugin] Failed to parse ICS: " . $e->getMessage());
            $response->setStatus(400);
            $response->setHeader('Content-Type', 'application/json');
            $response->setBody(json_encode([
                'error' => 'Failed to parse ICS file',
            ]));
            return false;
        }

        // Validate and auto-repair (fixes missing VALARM ACTION, etc.)
        $vcal->validate(VObject\Component::REPAIR);

        // Split by UID using the stream-based splitter
        // The splitter expects a stream, so we wrap the serialized data
        $stream = fopen('php://temp', 'r+');
        fwrite($stream, $vcal->serialize());
        rewind($stream);

        $splitter = new VObject\Splitter\ICalendar($stream);

        $totalEvents = 0;
        $importedCount = 0;
        $duplicateCount = 0;
        $skippedCount = 0;
        $errors = [];

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
                // and enforce max resource size
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

                // Duplicate key (SQLSTATE 23505) = event already exists
                // "no valid instances" = dead recurring event (all occurrences excluded)
                // Neither is actionable by the user, skip silently.
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
                        "[ICSImportPlugin] Failed to import event "
                        . "uid=" . ($uid ?? 'unknown')
                        . " summary={$summary}: {$msg}"
                    );
                }
            }
        }

        fclose($stream);

        error_log(
            "[ICSImportPlugin] Import complete: "
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
     *
     * Delegates to CalendarSanitizerPlugin (if registered). Import bypasses
     * the HTTP layer (uses createCalendarObject directly), so beforeCreateFile
     * hooks don't fire — we must call the sanitizer explicitly.
     *
     * @throws \Exception if the sanitized object exceeds the max resource size.
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
     * Resolve the internal calendar ID (the [calendarId, instanceId] pair)
     * from a principal URI and calendar URI.
     *
     * @param string $principalUri e.g. "principals/user@example.com"
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
            'description' => 'Bulk import events from a multi-event ICS file',
        ];
    }
}
