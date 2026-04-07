<?php
/**
 * ResourceCalendar - SharedCalendar with same-org read access.
 *
 * Resource calendars (rooms, equipment) are inherently shared within
 * an organization: a room only exists to be booked, and people booking
 * the room legitimately need to see what is already on it. The default
 * Sabre\CalDAV\SharedCalendar ACL only grants
 * ``{CALDAV}read-free-busy`` to ``{DAV:}authenticated``, which lets
 * users freebusy-query the room but not read the actual events
 * (summaries, organizers, attendees) — so the booking user cannot even
 * verify that their own request was accepted.
 *
 * This subclass extends both ``getACL()`` and ``getChildACL()`` with a
 * ``{DAV:}read`` grant for ``{DAV:}authenticated``. Cross-organization
 * isolation is enforced separately by
 * ``ResourceAutoSchedulePlugin::restrictCrossOrgRead`` so that this
 * grant does not leak resource booking content across orgs.
 */

namespace Calendars\SabreDav;

use Sabre\CalDAV\SharedCalendar;

class ResourceCalendar extends SharedCalendar
{
    public function getACL()
    {
        $acl = parent::getACL();
        $acl[] = [
            'privilege' => '{DAV:}read',
            'principal' => '{DAV:}authenticated',
            'protected' => true,
        ];
        return $acl;
    }

    public function getChildACL()
    {
        $acl = parent::getChildACL();
        $acl[] = [
            'privilege' => '{DAV:}read',
            'principal' => '{DAV:}authenticated',
            'protected' => true,
        ];
        return $acl;
    }
}
