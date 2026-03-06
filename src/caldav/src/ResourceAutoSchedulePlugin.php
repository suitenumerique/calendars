<?php
/**
 * ResourceAutoSchedulePlugin - Automatic scheduling for resource principals.
 *
 * Intercepts iTIP messages delivered to resource principals (ROOM/RESOURCE)
 * and automatically accepts or declines based on:
 * - The resource's auto-schedule mode (automatic, accept-always, decline-always, manual)
 * - Calendar conflict detection (for 'automatic' mode)
 * - Org scoping (rejects cross-org bookings)
 *
 * Runs after Schedule\Plugin delivers the iTIP message (priority 120 > 110).
 *
 * This plugin also sets $message->scheduleStatus before HttpCallbackIMipPlugin
 * runs, which prevents email delivery to resource addresses (resource addresses
 * are not real mailboxes).
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
        // Priority 120: runs after Schedule\Plugin (110)
        $server->on('schedule', [$this, 'autoSchedule'], 120);
        // Priority 200: runs BEFORE Schedule\Plugin's propFindEarly (150)
        // which hardcodes calendar-user-type to 'INDIVIDUAL'. By setting
        // the real value first, the Schedule\Plugin's handle() becomes a no-op.
        $server->on('propFind', [$this, 'propFindResourceType'], 200);
    }

    /**
     * Set the correct calendar-user-type for resource principals.
     *
     * Schedule\Plugin::propFindEarly (priority 150) hardcodes INDIVIDUAL via
     * handle(), which only fires when the property isn't already resolved.
     * By setting the real DB value here at priority 200 via set(), we pre-empt it.
     */
    public function propFindResourceType(\Sabre\DAV\PropFind $propFind, \Sabre\DAV\INode $node)
    {
        if (!($node instanceof ResourcePrincipal)) {
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
     * @param Message $message
     */
    public function autoSchedule(Message $message)
    {
        // Only handle REQUEST method (new invitations and updates)
        if ($message->method !== 'REQUEST') {
            return;
        }

        // Only handle messages to resource principals
        $recipientPrincipal = $this->resolveRecipientPrincipal($message->recipient);
        if (!$recipientPrincipal) {
            return;
        }

        $cutype = $recipientPrincipal['calendar_user_type'] ?? 'INDIVIDUAL';
        if (!in_array($cutype, ['ROOM', 'RESOURCE'], true)) {
            return;
        }

        // Enforce org scoping: reject cross-org bookings
        $requestOrgId = $this->server->httpRequest
            ? $this->server->httpRequest->getHeader('X-CalDAV-Organization')
            : null;
        $resourceOrgId = $recipientPrincipal['org_id'] ?? null;

        if ($requestOrgId && $resourceOrgId && $requestOrgId !== $resourceOrgId) {
            $this->declineInvitation($message, 'Cross-organization booking not allowed');
            return;
        }

        // Read auto-schedule mode from propertystorage
        $mode = $this->getAutoScheduleMode($recipientPrincipal['uri']);

        switch ($mode) {
            case 'accept-always':
                $this->acceptInvitation($message);
                break;

            case 'decline-always':
                $this->declineInvitation($message, 'Resource is offline');
                break;

            case 'manual':
                // Leave as NEEDS-ACTION for manual approval
                // But still set scheduleStatus to prevent email delivery
                $message->scheduleStatus = '1.0;Pending manual approval';
                break;

            case 'automatic':
            default:
                if ($this->hasConflict($recipientPrincipal, $message)) {
                    $this->declineInvitation($message, 'Resource is busy');
                } else {
                    $this->acceptInvitation($message);
                }
                break;
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
            // Use calendarobjects table directly for conflict check
            // firstoccurence and lastoccurence are Unix timestamps stored by SabreDAV
            $sql = 'SELECT COUNT(*) FROM calendarobjects'
                . ' WHERE calendarid = ?'
                . ' AND firstoccurence < ? AND lastoccurence > ?';
            $params = [$calendarId[0], $endTs, $startTs];

            if ($excludeUid) {
                $sql .= ' AND uid != ?';
                $params[] = $excludeUid;
            }

            $stmt = $this->pdo->prepare($sql);
            $stmt->execute($params);
            return (int)$stmt->fetchColumn() > 0;
        } catch (\Exception $e) {
            error_log("[ResourceAutoSchedulePlugin] Conflict check failed: " . $e->getMessage());
            return false; // Fail-open: allow booking if check fails
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
