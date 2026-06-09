<?php
/**
 * SharedCalendarPrivacyPlugin - Controls what sharees see on shared calendars.
 *
 * Scope: filtering applies ONLY to read-only and freebusy sharees. The owner
 * and WRITE sharees see everything (a write sharee can edit the events anyway —
 * matching Google Calendar's "Make changes" permission and Nextcloud's "edit ⇒
 * see all events"). And a read-only/freebusy sharee who is the ORGANIZER or an
 * ATTENDEE of an event always sees that event in full — you can't be hidden
 * from a meeting you were invited to.
 *
 * Three layers of protection (for the read-only/freebusy, non-participant case):
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
 * Intentional visibility expansions (by design — NOT bugs):
 *
 * - WRITE sharees (access 3) see every event in full, including
 *   CLASS:PRIVATE / CONFIDENTIAL. An editor can already change or delete the
 *   events, so masking is pointless (Google "Make changes" / Nextcloud model).
 *   This also means members granted read-write on a shared MAILBOX calendar
 *   (via the Messages ACL sync) see that mailbox's private events — expected
 *   for a shared mailbox.
 * - PARTICIPANTS (organizer/attendee) see an event in full even on a
 *   read-only or freebusy share, overriding both the freebusy force and an
 *   explicit PRIVATE/CONFIDENTIAL CLASS — you can't be hidden from a meeting
 *   you were invited to. Consequence: a freebusy-only sharee who is an
 *   attendee sees that one event's full details (summary, description,
 *   location, co-attendees). Bounded — they received the invite ICS by email
 *   anyway — and unforgeable: the viewer email comes from the authenticated
 *   principal, and a read-only sharee cannot add themselves as an attendee.
 *
 * Architecture: propFind hook (data layer) for REPORT/PROPFIND,
 * afterMethod:GET for direct .ics downloads, beforeMethod:COPY/MOVE to
 * block exfiltration of events a sharee may not see in full.
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

        // Block COPY/MOVE of events a sharee may not see in full. These
        // operations read the raw stored bytes server-side (they never
        // go through propFind/GET), so without this a sharee — even a
        // read-only one — could copy a PRIVATE/CONFIDENTIAL event onto a
        // calendar they own and read it unmasked.
        $server->on('beforeMethod:COPY', [$this, 'blockSensitiveCopyMove'], 90);
        $server->on('beforeMethod:MOVE', [$this, 'blockSensitiveCopyMove'], 90);
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

    /**
     * Whether privacy filtering applies to this path for the current user.
     *
     * Only READ-level shares are filtered (freebusy is a read share with a
     * flag, so it's covered too). WRITE sharees (access 3) are treated like
     * the owner: they can already edit/delete the events, so masking their
     * details is pointless — and it's the wrong model. This matches:
     *   - Google Calendar: "Make changes" permission bypasses an event's
     *     private/confidential visibility; only "see details"/"free-busy"
     *     viewers get "Busy".
     *   - Nextcloud: "being able to edit a calendar should mean you can see
     *     all events, as the owner would" (an editor who can't is a bug).
     */
    private function shouldFilter(string $path): bool
    {
        $info = $this->getShareInfo($path);
        return $info !== null && $info['access'] === self::ACCESS_READ;
    }

    private function isFreebusy(string $path): bool
    {
        $info = $this->getShareInfo($path);
        return $info !== null && $info['freebusy'];
    }

    /**
     * Email of the currently authenticated user (lowercased), or null.
     *
     * Used to exempt events the viewer organizes or is invited to: you
     * always see the details of an event you're a participant of, even on
     * a read-only / freebusy share. A read-only sharee cannot forge this
     * (it comes from the authenticated principal, not the request body) nor
     * add themselves as an attendee (that would need write access), so this
     * cannot be used to unmask events you weren't actually invited to.
     */
    private function currentUserEmail(): ?string
    {
        $aclPlugin = $this->server->getPlugin('acl');
        if (!$aclPlugin) {
            return null;
        }
        $principal = $aclPlugin->getCurrentUserPrincipal();
        if (!is_string($principal) || $principal === '') {
            return null;
        }
        $parts = explode('/', rtrim($principal, '/'));
        $last = end($parts);
        return $last ? strtolower(urldecode($last)) : null;
    }

    /**
     * True if $viewerEmail is the ORGANIZER or an ATTENDEE of $component.
     */
    private function isParticipant($component, string $viewerEmail): bool
    {
        if (isset($component->ORGANIZER)
            && $this->calAddressMatches((string)$component->ORGANIZER, $viewerEmail)) {
            return true;
        }
        foreach ($component->select('ATTENDEE') as $attendee) {
            if ($this->calAddressMatches((string)$attendee, $viewerEmail)) {
                return true;
            }
        }
        return false;
    }

    /**
     * Compare an iCalendar cal-address ("mailto:user@host" or bare address)
     * to an email, case-insensitively.
     */
    private function calAddressMatches(string $calAddress, string $email): bool
    {
        $addr = strtolower(trim($calAddress));
        if (strncmp($addr, 'mailto:', 7) === 0) {
            $addr = substr($addr, 7);
        }
        return $addr !== '' && $addr === $email;
    }

    // ========================================================================
    // CLASS classification (shared by applyRules and the COPY/MOVE guard)
    // ========================================================================

    /**
     * Normalise a component's explicit CLASS, failing CLOSED on anything we
     * don't recognise as safe to show.
     *
     * Trim before comparing: vobject preserves leading/trailing whitespace in
     * property values and some clients emit ``CLASS: PRIVATE`` (stray space) —
     * without the trim, '" PRIVATE"' !== 'PRIVATE' would leak. RFC 5545
     * §3.8.1.3: an absent CLASS defaults to PUBLIC, but implementations MUST
     * treat unrecognised x-name / iana-token values like PRIVATE. So only an
     * explicit PUBLIC or CONFIDENTIAL is honoured as-is; PRIVATE and ANY
     * unrecognised token (``PRIVAT``, ``RESTRICTED``, ``X-SECRET``, …) are
     * hidden, not leaked. A component with no CLASS at all returns PUBLIC.
     */
    private function normalizeClass($component): string
    {
        if (!isset($component->CLASS)) {
            return 'PUBLIC';
        }
        $raw = strtoupper(trim((string)$component->CLASS));
        return in_array($raw, ['PUBLIC', 'CONFIDENTIAL'], true) ? $raw : 'PRIVATE';
    }

    /**
     * Map of UID → normalised CLASS taken from each series' MASTER component
     * (the one without a RECURRENCE-ID). Override instances are skipped here:
     * they don't define the series' classification, they inherit it.
     */
    private function buildMasterClassByUid($vcal): array
    {
        $map = [];
        foreach ($vcal->getComponents() as $component) {
            $name = strtoupper($component->name);
            if (!in_array($name, ['VEVENT', 'VTODO', 'VJOURNAL'], true)) {
                continue;
            }
            // Overrides (RECURRENCE-ID) inherit; only the master sets the series class.
            if (isset($component->{'RECURRENCE-ID'}) || !isset($component->UID)) {
                continue;
            }
            $map[(string)$component->UID] = $this->normalizeClass($component);
        }
        return $map;
    }

    /**
     * Effective CLASS for a single component.
     *
     * A component with an explicit CLASS is honoured (normalised). A component
     * WITHOUT a CLASS that is a recurrence override inherits its series'
     * master class — otherwise a ``CLASS:PRIVATE`` / ``CONFIDENTIAL`` recurring
     * event would leak through a modified occurrence that simply omits CLASS
     * (RFC 5545 doesn't require overrides to repeat it). Falls back to PUBLIC
     * when there's no master to inherit from (RFC 5545 default).
     */
    private function effectiveClass($component, array $classByUid): string
    {
        if (isset($component->CLASS)) {
            return $this->normalizeClass($component);
        }
        $uid = isset($component->UID) ? (string)$component->UID : null;
        if ($uid !== null && isset($classByUid[$uid])) {
            return $classByUid[$uid];
        }
        return 'PUBLIC';
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
        if (!$this->shouldFilter($path)) {
            return;
        }

        $calData = $propFind->get(self::CALDAV_CALENDAR_DATA);
        if (!$calData || !is_string($calData)) {
            return;
        }

        $filtered = $this->applyRules($calData, $this->isFreebusy($path), $this->currentUserEmail());
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
        if (strpos($path, 'calendars/') === false || !$this->shouldFilter($path)) {
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

        $filtered = $this->applyRules($body, $this->isFreebusy($path), $this->currentUserEmail());
        if ($filtered !== $body) {
            $response->setBody($filtered);
            $response->setHeader('Content-Length', strlen($filtered));
        }
    }

    // ========================================================================
    // Block COPY/MOVE that would bypass read-time masking
    // ========================================================================

    /**
     * Refuse COPY/MOVE of an event a sharee is not allowed to see in
     * full. The read-time masking (propFind / afterMethod:GET) only
     * rewrites READ responses; a COPY/MOVE reads the raw stored bytes
     * server-side and re-creates them on the destination (a calendar the
     * sharee typically owns), so it would hand the sharee the unmasked
     * PRIVATE/CONFIDENTIAL content. Owners are unaffected (not shared).
     */
    public function blockSensitiveCopyMove(RequestInterface $request)
    {
        $path = $request->getPath();

        // Owners and write sharees have full visibility — no restriction.
        if (!$this->shouldFilter($path)) {
            return;
        }

        // Freebusy share: every event is confidential, nothing copyable.
        if ($this->isFreebusy($path)) {
            throw new DAV\Exception\Forbidden(
                'Cannot copy or move events from a freebusy-shared calendar'
            );
        }

        // Normal share: block only the events whose details are masked
        // for this sharee (PRIVATE / CONFIDENTIAL). PUBLIC events stay
        // copyable. Fail closed on anything we cannot read/parse.
        if ($this->sourceHasMaskedEvent($path)) {
            throw new DAV\Exception\Forbidden(
                'Cannot copy or move a private or confidential event '
                . 'from a shared calendar'
            );
        }
    }

    /**
     * True if the resource at $path contains a PRIVATE/CONFIDENTIAL
     * scheduling component (i.e. one whose details a sharee may not
     * see). Reads the raw stored data directly — NOT through the masking
     * hooks — because we need the real CLASS value. Fails closed.
     */
    private function sourceHasMaskedEvent(string $path): bool
    {
        try {
            $node = $this->server->tree->getNodeForPath($path);
        } catch (\Exception $e) {
            return true;
        }

        if (!($node instanceof \Sabre\CalDAV\ICalendarObject)) {
            // Not a single event (e.g. a whole-collection COPY). Be
            // conservative and block — bulk-copying a shared calendar
            // could sweep up masked events.
            return true;
        }

        $data = $node->get();
        if (is_resource($data)) {
            $data = stream_get_contents($data);
        }
        if (!is_string($data) || $data === '') {
            return true;
        }

        try {
            $vcal = Reader::read($data);
        } catch (\Exception $e) {
            return true;
        }

        $viewerEmail = $this->currentUserEmail();
        $classByUid = $this->buildMasterClassByUid($vcal);

        foreach ($vcal->getComponents() as $component) {
            $name = strtoupper($component->name);
            if (!in_array($name, ['VEVENT', 'VTODO', 'VJOURNAL'], true)) {
                continue;
            }
            // A participant sees the event in full (see applyRules), so it is
            // not masked for them — copying it leaks nothing they can't read.
            if ($viewerEmail !== null && $this->isParticipant($component, $viewerEmail)) {
                continue;
            }
            // Use the same fail-closed classification (incl. recurrence-override
            // inheritance) as the read path so a masked occurrence can't be
            // exfiltrated via COPY/MOVE.
            $class = $this->effectiveClass($component, $classByUid);
            if ($class === 'PRIVATE' || $class === 'CONFIDENTIAL') {
                return true;
            }
        }

        return false;
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
     * @param string      $icalData    Raw iCalendar string
     * @param bool        $freebusy    If true, ALL events are treated as CONFIDENTIAL
     * @param string|null $viewerEmail Current user's email; events they organize
     *                                 or attend are never masked from them
     * @return string Filtered iCalendar string
     */
    public function applyRules(string $icalData, bool $freebusy = false, ?string $viewerEmail = null): string
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
        $classByUid = $this->buildMasterClassByUid($vcal);

        foreach ($vcal->getComponents() as $component) {
            $name = strtoupper($component->name);
            if ($name === 'VTIMEZONE') {
                continue;
            }
            if (!in_array($name, ['VEVENT', 'VTODO', 'VJOURNAL'], true)) {
                continue;
            }

            // Classify the component (see normalizeClass/effectiveClass for the
            // fail-closed rules and recurrence-override inheritance).
            //
            // A participant (organizer/attendee) always sees the full event,
            // even on a read-only / freebusy share — you can't be hidden from
            // an event you were invited to. Checked first so it overrides both
            // the freebusy force and an explicit PRIVATE/CONFIDENTIAL CLASS.
            if ($viewerEmail !== null && $this->isParticipant($component, $viewerEmail)) {
                $class = 'PUBLIC';
            } elseif ($freebusy) {
                $class = 'CONFIDENTIAL';
            } else {
                $class = $this->effectiveClass($component, $classByUid);
            }

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
