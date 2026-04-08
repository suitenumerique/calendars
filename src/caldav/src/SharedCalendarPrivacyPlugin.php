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

    /** Access constants — must match PrincipalBackend / SabreDAV's sharing model */
    const ACCESS_OWNER = 1;
    const ACCESS_READ = 2;

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
     *
     * Resource calendars (``calendars/resources/...``) are special:
     * they expose ``{DAV:}read`` to ``{DAV:}authenticated`` via
     * ``ResourceCalendar::getACL`` so that same-org users can see what
     * is booked on a shared room. There is no per-sharee instance row
     * for those reads — every reader hits the single owner-side
     * instance — so the standard ``calendarinstances`` lookup below
     * would return ``access = 1`` (owner) and the privacy filter would
     * be skipped, leaking ``CLASS:PRIVATE`` / ``CLASS:CONFIDENTIAL``
     * booking content (and the booker's ``VALARM``s) to every other
     * user in the org. Treat any access to a resource calendar as a
     * "share" so the per-event filter applies.
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

        // Resource calendars: no sharee rows, ACL grants read to
        // authenticated. Treat every access as shared (read level)
        // so CLASS / VALARM filtering kicks in. ``freebusy`` does not
        // apply — there is no share_access_level row for resources.
        if ($parts[1] === 'resources') {
            return $this->cache[$calKey] = [
                'access' => self::ACCESS_READ,
                'freebusy' => false,
            ];
        }

        if ($parts[1] !== 'users') {
            return $this->cache[$calKey] = null;
        }

        // Path segments are URL-decoded by SabreDAV's request layer
        // before the propFind hook fires, so the raw email here is
        // already in canonical form (no ``%40``). Lowercase for the
        // SQL match — principals are stored lowercased and the path
        // may carry mixed case from the client.
        $email = strtolower(urldecode($parts[2]));
        $calUri = $parts[3];

        $stmt = $this->pdo->prepare(
            'SELECT calendarid, access, share_access_level FROM calendarinstances '
            . 'WHERE principaluri = ? AND uri = ?'
        );
        $stmt->execute(["principals/users/{$email}", $calUri]);
        $instance = $stmt->fetch(\PDO::FETCH_ASSOC);

        if (!$instance) {
            return $this->cache[$calKey] = null;
        }

        $access = (int)$instance['access'];
        $freebusy = $access > 1
            && ($instance['share_access_level'] ?? '') === 'freebusy';

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
     * Iterates ALL non-VTIMEZONE components — VEVENT, VTODO, VJOURNAL —
     * even though our calendars are configured with
     * ``supported-calendar-component-set = VEVENT``. The HTTP PUT path
     * enforces that constraint via SabreDAV's ``validateICalendar``,
     * but the internal-api ICS import endpoint writes through the
     * backend directly and so can plant a VTODO/VJOURNAL into a
     * VEVENT-only calendar. Filtering only VEVENTs would leave those
     * components unfiltered for sharees. Defense in depth: treat any
     * scheduling component the same way.
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

        foreach ($vcal->getComponents() as $component) {
            $name = strtoupper($component->name);
            if ($name === 'VTIMEZONE') {
                continue;
            }
            if (!in_array($name, ['VEVENT', 'VTODO', 'VJOURNAL'], true)) {
                continue;
            }

            $class = $freebusy
                ? 'CONFIDENTIAL'
                : (isset($component->CLASS) ? strtoupper((string)$component->CLASS) : 'PUBLIC');

            if ($class === 'PRIVATE') {
                $toRemove[] = $component;
                $modified = true;
                continue;
            }

            if ($class === 'CONFIDENTIAL') {
                $this->stripToConfidential($component);
                $modified = true;
            }

            // Always strip VALARM from shared calendars
            if ($this->stripValarms($component)) {
                $modified = true;
            }
        }

        foreach ($toRemove as $component) {
            $vcal->remove($component);
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
