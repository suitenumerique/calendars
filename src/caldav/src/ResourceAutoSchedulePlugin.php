<?php
/**
 * ResourceAutoSchedulePlugin - Resource principal management for CalDAV.
 *
 * Handles two aspects of resource principals (ROOM/RESOURCE):
 *
 * 1. **Auto-scheduling**: Intercepts iTIP messages and automatically accepts
 *    or declines based on:
 *    - The resource's auto-schedule mode (automatic, accept-always, decline-always, manual)
 *    - Calendar conflict detection (for 'automatic' mode)
 *    - Org scoping (rejects cross-org bookings)
 *
 * 2. **MKCALENDAR blocking**: Resources have exactly one calendar (created
 *    during provisioning). Additional calendar creation is rejected.
 *
 * Runs BEFORE Schedule\Plugin's scheduleLocalDelivery (default priority 100)
 * so that:
 *   - acceptInvitation's PARTSTAT mutation persists into the file that
 *     scheduleLocalDelivery writes (priority 90 < 100).
 *   - declineInvitation can return false to short-circuit event
 *     propagation, preventing scheduleLocalDelivery from delivering
 *     a declined message at all.
 *
 * Sets $message->scheduleStatus before HttpCallbackIMipPlugin runs, which
 * prevents email delivery to resource addresses.
 */

namespace Calendars\SabreDav;

use Sabre\DAV\Server;
use Sabre\DAV\ServerPlugin;
use Sabre\VObject\ITip\Message;
use Sabre\VObject\Reader;
use Sabre\CalDAV\Backend\PDO as CalDAVBackend;

class ResourceAutoSchedulePlugin extends ServerPlugin
{
    /** @var Server */
    protected $server;

    /** @var \PDO */
    private $pdo;

    /** @var CalDAVBackend */
    private $caldavBackend;

    /** Custom namespace for resource properties */
    private const NS = 'urn:lasuite:calendars';

    public function __construct(\PDO $pdo, CalDAVBackend $caldavBackend)
    {
        $this->pdo = $pdo;
        $this->caldavBackend = $caldavBackend;
    }

    public function getPluginName()
    {
        return 'resource-auto-schedule';
    }

    public function initialize(Server $server)
    {
        $this->server = $server;
        // Priority 90: runs BEFORE Schedule\Plugin::scheduleLocalDelivery
        // (default priority 100). This is critical: the auto-accept path
        // mutates $message->message in place to set PARTSTAT=ACCEPTED on
        // the resource attendee, and that mutation must be visible when
        // scheduleLocalDelivery runs and writes the file. Running AFTER
        // (the previous priority 120) would lose the mutation entirely.
        // For decline, autoSchedule returns false to stop propagation
        // so scheduleLocalDelivery never runs at all.
        $server->on('schedule', [$this, 'autoSchedule'], 90);
        // Priority 200: runs BEFORE Schedule\Plugin's propFindEarly (150)
        // which hardcodes calendar-user-type to 'INDIVIDUAL'. By setting
        // the real value first, the Schedule\Plugin's handle() becomes a no-op.
        $server->on('propFind', [$this, 'propFindResourceType'], 200);
        // Block additional calendar creation on resource principals
        $server->on('beforeMethod:MKCALENDAR', [$this, 'blockMkCalendar'], 90);
        // Cross-org isolation for read access on resource calendars.
        // ResourceCalendar grants {DAV:}read to {DAV:}authenticated so
        // same-org users can see what is booked on a shared room; this
        // hook prevents that grant from leaking content cross-org.
        $server->on('beforeMethod:GET', [$this, 'restrictCrossOrgRead'], 99);
        $server->on('beforeMethod:PROPFIND', [$this, 'restrictCrossOrgRead'], 99);
        $server->on('beforeMethod:REPORT', [$this, 'restrictCrossOrgRead'], 99);
    }

    /**
     * Reject reads on resource calendars when the requester's org does
     * not match the resource principal's org.
     *
     * Looks up the resource principal directly via the URL's
     * ``calendars/resources/{id}`` segment so we never have to wait for
     * SabreDAV to instantiate the node and run the ACL plugin (the
     * grant in ``ResourceCalendar`` would already have admitted the
     * cross-org caller by the time the ACL check ran).
     *
     * @return bool|null
     */
    public function restrictCrossOrgRead($request)
    {
        $path = $request->getPath();
        if (!preg_match('#^calendars/resources/([^/]+)#', $path, $matches)) {
            return null;
        }
        $resourceId = urldecode($matches[1]);
        $principalUri = 'principals/resources/' . $resourceId;

        try {
            $stmt = $this->pdo->prepare(
                'SELECT org_id FROM principals WHERE uri = ? LIMIT 1'
            );
            $stmt->execute([$principalUri]);
            $resourceOrgId = $stmt->fetchColumn();
        } catch (\Exception $e) {
            error_log(
                "[ResourceAutoSchedulePlugin] DB error in restrictCrossOrgRead: "
                . $e->getMessage()
            );
            // Fail-closed: refuse rather than leak.
            throw new \Sabre\DAV\Exception\Forbidden(
                'Cannot verify organization for resource calendar'
            );
        }

        if ($resourceOrgId === false || $resourceOrgId === null || $resourceOrgId === '') {
            // Resource has no org_id at all — should never happen for
            // properly provisioned resources. Fail-closed.
            throw new \Sabre\DAV\Exception\Forbidden(
                'Resource has no organization'
            );
        }

        $requesterOrgId = $request->getHeader('X-LS-Org-Id');
        if (!$requesterOrgId || $requesterOrgId !== $resourceOrgId) {
            throw new \Sabre\DAV\Exception\Forbidden(
                'Cross-organization access to resource calendars is not allowed'
            );
        }

        return null;
    }

    /**
     * Block MKCALENDAR on resource principal calendar homes.
     * Resources have exactly one calendar created during provisioning.
     */
    public function blockMkCalendar($request, $response)
    {
        if (preg_match('#^calendars/resources/#', $request->getPath())) {
            throw new \Sabre\DAV\Exception\Forbidden(
                'Resource principals can only have one calendar. '
                . 'Additional calendar creation is not allowed.'
            );
        }
    }

    /**
     * Set the correct calendar-user-type for resource principals.
     *
     * Schedule\Plugin::propFindEarly (priority 150) hardcodes INDIVIDUAL via
     * handle(), which only fires when the property isn't already resolved.
     * By setting the real DB value here at priority 200 via set(), we pre-empt it.
     *
     * Identifies resource principals by URL prefix (``principals/resources/``)
     * — the node class returned by ``ResourcePrincipalCollection`` is just
     * ``SchedulablePrincipal`` (a thin ``CalDAV\Principal\User`` subclass)
     * which is also used for individual users, so an instanceof check on
     * any concrete class would either match users too or never match at
     * all (which is what the previous bogus ``ResourcePrincipal`` reference
     * did — that class doesn't exist).
     */
    public function propFindResourceType(\Sabre\DAV\PropFind $propFind, \Sabre\DAV\INode $node)
    {
        if (!($node instanceof \Sabre\DAVACL\IPrincipal)) {
            return;
        }
        $url = $node->getPrincipalUrl();
        if (strpos($url, 'principals/resources/') !== 0) {
            return;
        }

        $props = $node->getProperties(
            ['{urn:ietf:params:xml:ns:caldav}calendar-user-type']
        );
        $cutype = $props['{urn:ietf:params:xml:ns:caldav}calendar-user-type'] ?? null;
        if ($cutype) {
            $propFind->set('{urn:ietf:params:xml:ns:caldav}calendar-user-type', $cutype);
        }
    }

    /**
     * Handle scheduling messages to resource principals.
     *
     * Returning ``false`` from this listener stops event propagation,
     * which is how decline (and manual-pending) paths prevent
     * ``Schedule\Plugin::scheduleLocalDelivery`` from writing the
     * declined message to the resource calendar. Accept paths return
     * null so the chain continues to scheduleLocalDelivery, which then
     * writes the (already PARTSTAT-mutated) message.
     *
     * @param Message $message
     * @return bool|null false = stop propagation; null = continue
     */
    public function autoSchedule(Message $message)
    {
        // Only handle REQUEST method (new invitations and updates)
        if ($message->method !== 'REQUEST') {
            return null;
        }

        // Only handle messages to resource principals
        $recipientPrincipal = $this->resolveRecipientPrincipal($message->recipient);
        if (!$recipientPrincipal) {
            return null;
        }

        $cutype = $recipientPrincipal['calendar_user_type'] ?? 'INDIVIDUAL';
        if (!in_array($cutype, ['ROOM', 'RESOURCE'], true)) {
            return null;
        }

        // Enforce org scoping: reject cross-org bookings
        $requestOrgId = $this->server->httpRequest
            ? $this->server->httpRequest->getHeader('X-LS-Org-Id')
            : null;
        $resourceOrgId = $recipientPrincipal['org_id'] ?? null;

        if ($resourceOrgId) {
            if (!$requestOrgId || $requestOrgId !== $resourceOrgId) {
                $this->declineInvitation($message, 'Cross-organization booking not allowed');
                return false;
            }
        }

        // Read auto-schedule mode from propertystorage
        $mode = $this->getAutoScheduleMode($recipientPrincipal['uri']);

        switch ($mode) {
            case 'accept-always':
                $this->acceptInvitation($message);
                return null;

            case 'decline-always':
                $this->declineInvitation($message, 'Resource is offline');
                return false;

            case 'manual':
                // Leave as NEEDS-ACTION for manual approval
                // But still set scheduleStatus to prevent email delivery
                // and stop propagation so scheduleLocalDelivery does
                // not auto-deliver the pending request.
                $message->scheduleStatus = '1.0;Pending manual approval';
                return false;

            case 'automatic':
            default:
                if ($this->hasConflict($recipientPrincipal, $message)) {
                    $this->declineInvitation($message, 'Resource is busy');
                    return false;
                }
                $this->acceptInvitation($message);
                return null;
        }
    }

    /**
     * Resolve the recipient email to a principal record.
     *
     * @param string $recipient mailto: URI
     * @return array|null Principal row or null
     */
    private function resolveRecipientPrincipal($recipient)
    {
        $email = $this->extractEmail($recipient);
        if (!$email) {
            return null;
        }

        try {
            $stmt = $this->pdo->prepare(
                'SELECT id, uri, email, calendar_user_type, org_id'
                . ' FROM principals WHERE email = ?'
            );
            $stmt->execute([strtolower($email)]);
            return $stmt->fetch(\PDO::FETCH_ASSOC) ?: null;
        } catch (\Exception $e) {
            error_log("[ResourceAutoSchedulePlugin] DB error: " . $e->getMessage());
            return null;
        }
    }

    /**
     * Extract email from a mailto: URI.
     *
     * @param string $uri
     * @return string|null
     */
    private function extractEmail($uri)
    {
        if (stripos($uri, 'mailto:') === 0) {
            return strtolower(substr($uri, 7));
        }
        return null;
    }

    /**
     * Get auto-schedule mode from propertystorage.
     *
     * @param string $principalUri
     * @return string
     */
    private function getAutoScheduleMode($principalUri)
    {
        try {
            $stmt = $this->pdo->prepare(
                "SELECT value FROM propertystorage"
                . " WHERE path = ? AND name = '{" . self::NS . "}auto-schedule-mode'"
            );
            $stmt->execute([$principalUri]);
            $result = $stmt->fetchColumn();
            return $result ?: 'automatic';
        } catch (\Exception $e) {
            error_log("[ResourceAutoSchedulePlugin] Failed to read auto-schedule mode: " . $e->getMessage());
            return 'automatic';
        }
    }

    /**
     * Check if the resource has a conflict with the incoming event.
     *
     * @param array $principal
     * @param Message $message
     * @return bool
     */
    private function hasConflict($principal, Message $message)
    {
        if (!$message->message) {
            return false;
        }

        $vcalendar = $message->message;

        // Get the resource's calendar
        $calendarId = $this->getResourceCalendarId($principal['uri']);
        if (!$calendarId) {
            return false; // No calendar = no conflicts
        }

        // Extract time ranges from all VEVENT components
        foreach ($vcalendar->VEVENT as $vevent) {
            // Skip transparent events
            $transp = isset($vevent->TRANSP) ? (string)$vevent->TRANSP : 'OPAQUE';
            if ($transp === 'TRANSPARENT') {
                continue;
            }

            $dtstart = $vevent->DTSTART ? $vevent->DTSTART->getDateTime() : null;
            $dtend = null;

            if (isset($vevent->DTEND)) {
                $dtend = $vevent->DTEND->getDateTime();
            } elseif (isset($vevent->DURATION)) {
                $dtend = clone $dtstart;
                $dtend->add($vevent->DURATION->getDateInterval());
            }

            if (!$dtstart || !$dtend) {
                continue;
            }

            // Query for overlapping events in the resource's calendar
            $startTs = $dtstart->getTimestamp();
            $endTs = $dtend->getTimestamp();

            // Get UID of the incoming event to exclude updates to the same event
            $uid = isset($vevent->UID) ? (string)$vevent->UID : null;

            if ($this->hasOverlappingEvents($calendarId, $startTs, $endTs, $uid)) {
                return true;
            }
        }

        return false;
    }

    /**
     * Get the resource's default calendar ID.
     *
     * @param string $principalUri
     * @return array|null [calendarId, instanceId] pair or null
     */
    private function getResourceCalendarId($principalUri)
    {
        $calendars = $this->caldavBackend->getCalendarsForUser($principalUri);
        if (!empty($calendars)) {
            return $calendars[0]['id'];
        }
        return null;
    }

    /**
     * Check for overlapping events in a calendar.
     *
     * @param array $calendarId [calendarId, instanceId]
     * @param int $startTs Start timestamp
     * @param int $endTs End timestamp
     * @param string|null $excludeUid UID to exclude (for updates)
     * @return bool
     */
    private function hasOverlappingEvents($calendarId, $startTs, $endTs, $excludeUid = null)
    {
        try {
            // Normalize calendarId: SabreDAV may return an array [id, instanceId]
            // or a scalar integer depending on the version/backend.
            $calId = is_array($calendarId) ? $calendarId[0] : $calendarId;

            // Use calendarobjects table directly for conflict check
            // firstoccurence and lastoccurence are Unix timestamps stored by SabreDAV
            $sql = 'SELECT COUNT(*) FROM calendarobjects'
                . ' WHERE calendarid = ?'
                . ' AND firstoccurence < ? AND lastoccurence > ?';
            $params = [$calId, $endTs, $startTs];

            if ($excludeUid) {
                $sql .= ' AND uid != ?';
                $params[] = $excludeUid;
            }

            $stmt = $this->pdo->prepare($sql);
            $stmt->execute($params);
            return (int)$stmt->fetchColumn() > 0;
        } catch (\Exception $e) {
            error_log("[ResourceAutoSchedulePlugin] Conflict check failed: " . $e->getMessage());
            return true; // Fail-closed: reject booking if check fails
        }
    }

    /**
     * Accept the invitation.
     *
     * @param Message $message
     */
    private function acceptInvitation(Message $message)
    {
        $message->scheduleStatus = '1.2;Scheduling message delivered (auto-accepted)';

        // Update PARTSTAT in the delivered calendar object
        $this->updatePartstat($message, 'ACCEPTED');
    }

    /**
     * Decline the invitation.
     *
     * @param Message $message
     * @param string $reason
     */
    private function declineInvitation(Message $message, $reason = '')
    {
        $message->scheduleStatus = '3.0;Scheduling message declined' . ($reason ? ": $reason" : '');

        // Update PARTSTAT in the delivered calendar object
        $this->updatePartstat($message, 'DECLINED');
    }

    /**
     * Update the PARTSTAT of the resource attendee in the iTIP message.
     *
     * @param Message $message
     * @param string $partstat ACCEPTED, DECLINED, etc.
     */
    private function updatePartstat(Message $message, $partstat)
    {
        if (!$message->message) {
            return;
        }

        $recipientEmail = $this->extractEmail($message->recipient);
        if (!$recipientEmail) {
            return;
        }

        foreach ($message->message->VEVENT as $vevent) {
            if (!isset($vevent->ATTENDEE)) {
                continue;
            }
            foreach ($vevent->ATTENDEE as $attendee) {
                $email = $this->extractEmail((string)$attendee);
                if ($email === $recipientEmail) {
                    $attendee['PARTSTAT'] = $partstat;
                }
            }
        }
    }

    public function getPluginInfo()
    {
        return [
            'name' => $this->getPluginName(),
            'description' => 'Auto-scheduling for resource principals (rooms, equipment)',
        ];
    }
}
