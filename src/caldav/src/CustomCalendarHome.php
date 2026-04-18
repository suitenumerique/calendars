<?php
/**
 * CustomCalendarHome - Overrides calendar instantiation for mailbox support.
 *
 * SabreDAV's CalendarHome instantiates SharedCalendar for all shared
 * calendar instances. We override this to use MailboxSharedCalendar for
 * instances whose owner is a MAILBOX principal. This grants {DAV:}share
 * privilege to read-write sharees of mailbox calendars, allowing them
 * to manage read-only shares via standard CS:share without proxy hacks.
 */

namespace Calendars\SabreDav;

use Sabre\CalDAV\CalendarHome;
use Sabre\CalDAV\Calendar;
use Sabre\CalDAV\SharedCalendar;
use Sabre\CalDAV\Backend\SharingSupport;
use Sabre\DAV\Exception\NotFound;

class CustomCalendarHome extends CalendarHome
{
    /** @var \PDO */
    private $pdo;

    /** @var array<int,bool> Per-instance cache: calendarId → isMailboxOwned */
    private $mailboxOwnedCache = [];

    public function setPdo(\PDO $pdo)
    {
        $this->pdo = $pdo;
    }

    /**
     * Override getChild to return MailboxSharedCalendar for MAILBOX-owned
     * shared instances.
     */
    public function getChild($name)
    {
        // For non-sharing backends, delegate to parent
        if (!($this->caldavBackend instanceof SharingSupport)) {
            return parent::getChild($name);
        }

        // Handle special collections (inbox, outbox, notifications)
        // by delegating to parent for non-calendar names
        if (in_array($name, ['inbox', 'outbox', 'notifications'], true)) {
            return parent::getChild($name);
        }

        foreach ($this->caldavBackend->getCalendarsForUser($this->principalInfo['uri']) as $calendar) {
            if ($calendar['uri'] === $name) {
                return $this->wrapCalendar($calendar);
            }
        }

        // Check subscriptions
        try {
            return parent::getChild($name);
        } catch (NotFound $e) {
            throw new NotFound('Calendar with name \'' . $name . '\' could not be found');
        }
    }

    /**
     * Override getChildren to use proper calendar node types.
     *
     * Replicates parent logic but routes through wrapCalendar() to use
     * MailboxSharedCalendar where appropriate, avoiding double-instantiation.
     */
    public function getChildren()
    {
        $objs = [];

        // Calendars — batch-prefetch mailbox-owned status to avoid N+1 queries
        $calendars = $this->caldavBackend->getCalendarsForUser($this->principalInfo['uri']);
        $this->prefetchMailboxOwned($calendars);
        foreach ($calendars as $calendar) {
            $objs[] = $this->wrapCalendar($calendar);
        }

        // Scheduling inbox/outbox
        if ($this->caldavBackend instanceof \Sabre\CalDAV\Backend\SchedulingSupport) {
            $objs[] = new \Sabre\CalDAV\Schedule\Inbox($this->caldavBackend, $this->principalInfo['uri']);
            $objs[] = new \Sabre\CalDAV\Schedule\Outbox($this->principalInfo['uri']);
        }

        // Notifications
        if ($this->caldavBackend instanceof \Sabre\CalDAV\Backend\NotificationSupport) {
            $objs[] = new \Sabre\CalDAV\Notifications\Collection($this->caldavBackend, $this->principalInfo['uri']);
        }

        // Subscriptions
        if ($this->caldavBackend instanceof \Sabre\CalDAV\Backend\SubscriptionSupport) {
            foreach ($this->caldavBackend->getSubscriptionsForUser($this->principalInfo['uri']) as $subscription) {
                $objs[] = new \Sabre\CalDAV\Subscriptions\Subscription($this->caldavBackend, $subscription);
            }
        }

        return $objs;
    }

    /**
     * Wrap a calendar array into the appropriate node class.
     *
     * Routing decision tree:
     *  - Backend without sharing support → plain Calendar
     *  - Calendar lives under a resource principal → ResourceCalendar
     *    (extends SharedCalendar with same-org read access; cross-org
     *    isolation is enforced by ResourceAutoSchedulePlugin's
     *    cross-org guard).
     *  - Mailbox-owned shared instance → MailboxSharedCalendar
     *  - Otherwise → SharedCalendar
     */
    private function wrapCalendar(array $calendar)
    {
        if (!($this->caldavBackend instanceof SharingSupport)) {
            return new Calendar($this->caldavBackend, $calendar);
        }

        // Resource calendars are detected from the home's principal URI
        // (no DB query): the home was constructed with the principal
        // info, so we already know if this is principals/resources/...
        if (strpos($this->principalInfo['uri'] ?? '', 'principals/resources/') === 0) {
            return new ResourceCalendar($this->caldavBackend, $calendar);
        }

        $access = $calendar['share-access'] ?? 0;
        $isShared = $access !== \Sabre\DAV\Sharing\Plugin::ACCESS_SHAREDOWNER
            && $access !== \Sabre\DAV\Sharing\Plugin::ACCESS_NOTSHARED;

        if ($isShared && $this->pdo && $this->isMailboxOwned($calendar)) {
            // Inject owner type into calendarInfo so propFind handlers
            // can read it without an extra DB query. The frontend uses
            // this to detect mailbox calendars.
            $calendar['{http://lasuite.numerique.gouv.fr/ns/}calendar-owner-type'] = 'MAILBOX';
            return new MailboxSharedCalendar($this->caldavBackend, $calendar);
        }

        return new SharedCalendar($this->caldavBackend, $calendar);
    }

    /**
     * Check if the calendar's owner principal is a MAILBOX type.
     *
     * Uses calendarid to find the owner instance, then checks the
     * principal's calendar_user_type.
     */
    private function isMailboxOwned(array $calendarInfo): bool
    {
        $calendarId = is_array($calendarInfo['id'])
            ? $calendarInfo['id'][0]
            : $calendarInfo['id'];

        if (array_key_exists($calendarId, $this->mailboxOwnedCache)) {
            return $this->mailboxOwnedCache[$calendarId];
        }

        try {
            // Find the owner principal for this calendar
            $stmt = $this->pdo->prepare(
                'SELECT p.calendar_user_type FROM calendarinstances ci '
                . 'JOIN principals p ON p.uri = ci.principaluri '
                . 'WHERE ci.calendarid = ? AND ci.access = 1 '
                . 'LIMIT 1'
            );
            $stmt->execute([$calendarId]);
            $type = $stmt->fetchColumn();

            $result = $type === PrincipalBackend::TYPE_MAILBOX;
            $this->mailboxOwnedCache[$calendarId] = $result;
            return $result;
        } catch (\Exception $e) {
            error_log("[CustomCalendarHome] DB error: " . $e->getMessage());
            return false;
        }
    }

    /**
     * Batch-prefetch mailbox-owned status for a set of calendars in one query.
     * Called from getChildren to avoid N+1 queries.
     *
     * @param array $calendars List of calendar info arrays from getCalendarsForUser
     */
    private function prefetchMailboxOwned(array $calendars): void
    {
        if (!$this->pdo || empty($calendars)) {
            return;
        }

        $ids = [];
        foreach ($calendars as $cal) {
            $cid = is_array($cal['id']) ? $cal['id'][0] : $cal['id'];
            if (!array_key_exists($cid, $this->mailboxOwnedCache)) {
                $ids[] = $cid;
            }
        }
        if (empty($ids)) {
            return;
        }

        try {
            $placeholders = implode(',', array_fill(0, count($ids), '?'));
            $stmt = $this->pdo->prepare(
                'SELECT ci.calendarid, p.calendar_user_type FROM calendarinstances ci '
                . 'JOIN principals p ON p.uri = ci.principaluri '
                . 'WHERE ci.calendarid IN (' . $placeholders . ') AND ci.access = 1'
            );
            $stmt->execute($ids);
            $found = [];
            while ($row = $stmt->fetch(\PDO::FETCH_ASSOC)) {
                $found[$row['calendarid']] = $row['calendar_user_type'];
            }
            foreach ($ids as $cid) {
                $this->mailboxOwnedCache[$cid] =
                    ($found[$cid] ?? null) === PrincipalBackend::TYPE_MAILBOX;
            }
        } catch (\Exception $e) {
            error_log("[CustomCalendarHome] prefetch DB error: " . $e->getMessage());
        }
    }

}
