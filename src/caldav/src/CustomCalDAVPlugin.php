<?php
/**
 * Custom CalDAV plugin that handles nested principal prefixes.
 *
 * SabreDAV's built-in CalDAV\Plugin assumes principals are 2-part:
 *   principals/{name}  →  calendars/{name}
 *
 * We use 3-part principals:
 *   principals/users/{email}      →  calendars/users/{email}
 *   principals/resources/{id}     →  calendars/resources/{id}
 *
 * This subclass overrides getCalendarHomeForPrincipal() to handle
 * the nested structure.
 */

namespace Calendars\SabreDav;

use Sabre\CalDAV;

class CustomCalDAVPlugin extends CalDAV\Plugin
{
    /**
     * Returns the path to a principal's calendar home.
     *
     * Handles both 2-part (principals/{name}) and 3-part
     * (principals/{type}/{name}) principal URLs.
     *
     * @param string $principalUrl
     * @return string|null
     */
    public function getCalendarHomeForPrincipal($principalUrl)
    {
        $parts = explode('/', trim($principalUrl, '/'));

        if (count($parts) < 2 || 'principals' !== $parts[0]) {
            return null;
        }

        // Standard 2-part: principals/{name} → calendars/{name}
        if (count($parts) === 2) {
            return self::CALENDAR_ROOT . '/' . $parts[1];
        }

        // 3-part: principals/users/{email} → calendars/users/{email}
        //         principals/resources/{id} → calendars/resources/{id}
        if (count($parts) === 3 && in_array($parts[1], ['users', 'resources'], true)) {
            return self::CALENDAR_ROOT . '/' . $parts[1] . '/' . $parts[2];
        }

        return null;
    }
}
