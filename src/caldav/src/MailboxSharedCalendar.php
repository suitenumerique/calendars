<?php
/**
 * MailboxSharedCalendar - SharedCalendar that grants share privilege.
 *
 * For shared instances of MAILBOX-owned calendars, read-write sharees
 * (senders/admins) need {DAV:}share privilege to manage read-only shares
 * via standard CS:share. This subclass adds that privilege to the ACL.
 *
 * This eliminates the need for proxy-level path rewriting — SabreDAV's
 * standard sharing flow (SharingPlugin → checkPrivileges → updateInvites)
 * works natively because getACL() returns the right privileges.
 *
 * Security: MailboxPlugin.restrictSharing() still enforces that only
 * read-only shares are allowed on MAILBOX calendars via CalDAV. Write
 * access must come through the Messages ACL sync (internal API).
 */

namespace Calendars\SabreDav;

use Sabre\CalDAV\SharedCalendar;
use Sabre\DAV\Sharing\Plugin as SPlugin;

class MailboxSharedCalendar extends SharedCalendar
{
    /**
     * Returns ACL with {DAV:}share privilege for read-write sharees.
     *
     * Standard SharedCalendar only grants {DAV:}share to OWNER/NOTSHARED.
     * For MAILBOX calendars, read-write sharees (who are Messages
     * senders/admins) also get share privilege so they can add read-only
     * shares via CS:share.
     */
    public function getACL()
    {
        $acl = parent::getACL();

        // Only add share privilege for read-write sharees
        if ($this->getShareAccess() === SPlugin::ACCESS_READWRITE) {
            $acl[] = [
                'privilege' => '{DAV:}share',
                'principal' => $this->calendarInfo['principaluri'],
                'protected' => true,
            ];
            $acl[] = [
                'privilege' => '{DAV:}share',
                'principal' => $this->calendarInfo['principaluri'] . '/calendar-proxy-write',
                'protected' => true,
            ];
        }

        return $acl;
    }
}
