<?php
/**
 * SharedCalendarPrivacyPlugin - Controls what sharees see on shared calendars.
 *
 * Three layers of protection on shared calendars:
 *
 * 1. RFC 5545 CLASS enforcement:
 *    - CLASS:PRIVATE — event completely hidden
 *    - CLASS:CONFIDENTIAL — time block only, details stripped ("Busy")
 *    - CLASS:PUBLIC (default) — full details visible
 *
 * 2. Freebusy-only shares (custom property on calendar):
 *    - ALL events treated as CONFIDENTIAL regardless of their CLASS
 *    - COPY from freebusy calendars is blocked (prevents data exfiltration)
 *
 * 3. VALARM stripping:
 *    - Non-owners never see the owner's alarms/reminders
 *
 * Architecture: propFind hook (data layer) for REPORT/PROPFIND,
 * afterMethod:GET for direct .ics downloads, beforeMethod:COPY to block.
 */

namespace Calendars\SabreDav;

use Sabre\DAV;
use Sabre\DAV\Server;
use Sabre\DAV\ServerPlugin;
use Sabre\DAV\PropFind;
use Sabre\DAV\INode;
use Sabre\HTTP\ResponseInterface;
use Sabre\HTTP\RequestInterface;
use Sabre\VObject\Reader;

class SharedCalendarPrivacyPlugin extends ServerPlugin
{
    const FREEBUSY_PROP = '{http://lasuite.numerique.gouv.fr/ns/}freebusy-access';
    const CALDAV_CALENDAR_DATA = '{urn:ietf:params:xml:ns:caldav}calendar-data';

    /** Properties kept for CONFIDENTIAL / freebusy events (whitelist) */
    const CONFIDENTIAL_ALLOWED = [
        'UID', 'DTSTART', 'DTEND', 'DURATION', 'RRULE', 'EXDATE', 'RDATE',
        'RECURRENCE-ID', 'TRANSP', 'STATUS', 'DTSTAMP', 'CREATED',
        'LAST-MODIFIED', 'SEQUENCE', 'CLASS', 'EXRULE',
    ];

    /** @var Server */
    protected $server;

    /** @var \PDO */
    protected $pdo;

    /** @var array Per-request cache: calendar path -> [access, isFreebusy] */
    private $cache = [];

    public function __construct(\PDO $pdo)
    {
        $this->pdo = $pdo;
    }

    public function initialize(Server $server)
    {
        $this->server = $server;

        // Data-layer: filter calendar-data per-node
        $server->on('propFind', [$this, 'propFindFilter'], 310);

        // Response-layer: filter GET (direct .ics, ICS export)
        $server->on('afterMethod:GET', [$this, 'filterGetResponse'], 210);

        // Block COPY from freebusy calendars
        $server->on('beforeMethod:COPY', [$this, 'blockCopy'], 90);
    }

    // ========================================================================
    // Calendar access lookups
    // ========================================================================

    /**
     * Get share info for a calendar path.
     * Returns ['access' => int, 'freebusy' => bool] or null if not found.
     * access: 1=owner, 2=read, 3=readwrite
     */
    private function getShareInfo(string $path): ?array
    {
        $parts = explode('/', trim($path, '/'));
        if (count($parts) < 4 || $parts[0] !== 'calendars') {
            return null;
        }

        $calKey = implode('/', array_slice($parts, 0, 4));
        if (isset($this->cache[$calKey])) {
            return $this->cache[$calKey];
        }

        $email = $parts[2];
        $calUri = $parts[3];

        $stmt = $this->pdo->prepare(
            'SELECT calendarid, access FROM calendarinstances '
            . 'WHERE principaluri = ? AND uri = ?'
        );
        $stmt->execute(["principals/users/{$email}", $calUri]);
        $instance = $stmt->fetch(\PDO::FETCH_ASSOC);

        if (!$instance) {
            return $this->cache[$calKey] = null;
        }

        $access = (int)$instance['access'];
        $freebusy = false;

        // Check freebusy property only for shared calendars (access > 1)
        if ($access > 1) {
            // Find the owner's instance
            $stmt2 = $this->pdo->prepare(
                'SELECT principaluri, uri FROM calendarinstances '
                . 'WHERE calendarid = ? AND access = 1'
            );
            $stmt2->execute([$instance['calendarid']]);
            $owner = $stmt2->fetch(\PDO::FETCH_ASSOC);

            if ($owner) {
                $ownerEmail = basename($owner['principaluri']);
                $ownerCalPath = "calendars/users/{$ownerEmail}/{$owner['uri']}";

                $stmt3 = $this->pdo->prepare(
                    'SELECT 1 FROM propertystorage WHERE path = ? AND name = ?'
                );
                $stmt3->execute([$ownerCalPath, self::FREEBUSY_PROP]);
                $freebusy = $stmt3->fetch(\PDO::FETCH_ASSOC) !== false;
            }
        }

        return $this->cache[$calKey] = ['access' => $access, 'freebusy' => $freebusy];
    }

    private function isShared(string $path): bool
    {
        $info = $this->getShareInfo($path);
        return $info !== null && $info['access'] > 1;
    }

    private function isFreebusy(string $path): bool
    {
        $info = $this->getShareInfo($path);
        return $info !== null && $info['freebusy'];
    }

    // ========================================================================
    // propFind — data-layer filtering for REPORT/PROPFIND
    // ========================================================================

    public function propFindFilter(PropFind $propFind, INode $node)
    {
        if (!($node instanceof \Sabre\CalDAV\ICalendarObject)) {
            return;
        }

        $path = $propFind->getPath();
        if (!$this->isShared($path)) {
            return;
        }

        $calData = $propFind->get(self::CALDAV_CALENDAR_DATA);
        if (!$calData || !is_string($calData)) {
            return;
        }

        $filtered = $this->applyRules($calData, $this->isFreebusy($path));
        if ($filtered !== $calData) {
            $propFind->set(self::CALDAV_CALENDAR_DATA, $filtered);
        }
    }

    // ========================================================================
    // afterMethod:GET — response filtering for direct .ics downloads
    // ========================================================================

    public function filterGetResponse(RequestInterface $request, ResponseInterface $response)
    {
        $path = $request->getPath();
        if (strpos($path, 'calendars/') === false || !$this->isShared($path)) {
            return;
        }

        $contentType = $response->getHeader('Content-Type') ?? '';
        if (strpos($contentType, 'text/calendar') === false) {
            return;
        }

        $body = $response->getBodyAsString();
        if (!$body) {
            return;
        }

        $filtered = $this->applyRules($body, $this->isFreebusy($path));
        if ($filtered !== $body) {
            $response->setBody($filtered);
            $response->setHeader('Content-Length', strlen($filtered));
        }
    }

    // ========================================================================
    // Block COPY from freebusy calendars
    // ========================================================================

    public function blockCopy(RequestInterface $request)
    {
        if ($this->isFreebusy($request->getPath())) {
            throw new DAV\Exception\Forbidden(
                'Cannot copy events from a freebusy-shared calendar'
            );
        }
    }

    // ========================================================================
    // Core filtering logic
    // ========================================================================

    /**
     * Apply all privacy rules to iCalendar data on a shared calendar.
     *
     * @param string $icalData  Raw iCalendar string
     * @param bool   $freebusy  If true, ALL events are treated as CONFIDENTIAL
     * @return string Filtered iCalendar string
     */
    public function applyRules(string $icalData, bool $freebusy = false): string
    {
        try {
            $vcal = Reader::read($icalData);
        } catch (\Exception $e) {
            // Fail closed: never leak unparseable data to sharees
            return "BEGIN:VCALENDAR\r\nVERSION:2.0\r\n"
                 . "PRODID:-//Calendars//EN\r\nEND:VCALENDAR\r\n";
        }

        $modified = false;
        $toRemove = [];

        foreach ($vcal->select('VEVENT') as $vevent) {
            $class = $freebusy
                ? 'CONFIDENTIAL'
                : (isset($vevent->CLASS) ? strtoupper((string)$vevent->CLASS) : 'PUBLIC');

            if ($class === 'PRIVATE') {
                $toRemove[] = $vevent;
                $modified = true;
                continue;
            }

            if ($class === 'CONFIDENTIAL') {
                $this->stripToConfidential($vevent);
                $modified = true;
            }

            // Always strip VALARM from shared calendars
            if ($this->stripValarms($vevent)) {
                $modified = true;
            }
        }

        foreach ($toRemove as $vevent) {
            $vcal->remove($vevent);
        }

        return $modified ? $vcal->serialize() : $icalData;
    }

    /**
     * Strip a VEVENT to confidential level — keep only time properties.
     */
    private function stripToConfidential($vevent): void
    {
        $toRemove = [];
        foreach ($vevent->children() as $child) {
            if (!in_array(strtoupper($child->name), self::CONFIDENTIAL_ALLOWED, true)) {
                $toRemove[] = $child;
            }
        }
        foreach ($toRemove as $child) {
            $vevent->remove($child);
        }
        $vevent->add('SUMMARY', 'Busy');
    }

    /**
     * Remove all VALARM components from a VEVENT.
     */
    private function stripValarms($vevent): bool
    {
        $alarms = $vevent->select('VALARM');
        if (empty($alarms)) {
            return false;
        }
        foreach ($alarms as $alarm) {
            $vevent->remove($alarm);
        }
        return true;
    }

    // ========================================================================

    public function getPluginName()
    {
        return 'shared-calendar-privacy';
    }

    public function getPluginInfo()
    {
        return [
            'name' => $this->getPluginName(),
            'description' => 'Controls shared calendar visibility: CLASS, freebusy, VALARM',
        ];
    }
}
