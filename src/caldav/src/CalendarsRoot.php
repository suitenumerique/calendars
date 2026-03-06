<?php
/**
 * Custom root node for the /calendars/ collection.
 *
 * SabreDAV's built-in CalendarRoot maps calendars/{name} → principals/{name}
 * using a flat, single-level principal prefix. This doesn't work for nested
 * prefixes like principals/users/{email} and principals/resources/{id},
 * because CalendarRoot.getChild('users') would look for a principal named
 * 'principals/users' rather than a sub-collection.
 *
 * This node sits at /calendars/ and delegates to child CalendarRoot nodes:
 *   calendars/users/{email}/{cal}     → CalendarRoot(prefix='principals/users')
 *   calendars/resources/{id}/{cal}  → CalendarRoot(prefix='principals/resources')
 *
 */

namespace Calendars\SabreDav;

use Sabre\CalDAV;
use Sabre\DAV;
use Sabre\DAVACL\PrincipalBackend\BackendInterface as PrincipalBackendInterface;
use Sabre\CalDAV\Backend\BackendInterface as CalDAVBackendInterface;

class CalendarsRoot extends DAV\Collection
{
    /** @var DAV\INode[] */
    private $children;

    public function __construct(
        PrincipalBackendInterface $principalBackend,
        CalDAVBackendInterface $caldavBackend
    ) {
        $this->children = [
            new NamedCalendarRoot('users', $principalBackend, $caldavBackend, 'principals/users'),
            new NamedCalendarRoot('resources', $principalBackend, $caldavBackend, 'principals/resources'),
        ];
    }

    public function getName()
    {
        return 'calendars';
    }

    public function getChild($name)
    {
        foreach ($this->children as $child) {
            if ($child->getName() === $name) {
                return $child;
            }
        }
        throw new DAV\Exception\NotFound('Collection ' . $name . ' not found');
    }

    public function getChildren()
    {
        return $this->children;
    }
}

/**
 * A CalendarRoot whose getName() returns a custom value instead of 'calendars'.
 *
 * Used as a child of CalendarsRoot so that:
 *   calendars/users/   → NamedCalendarRoot('users', ..., 'principals/users')
 *   calendars/resources/ → NamedCalendarRoot('resources', ..., 'principals/resources')
 */
class NamedCalendarRoot extends CalDAV\CalendarRoot
{
    /** @var string */
    private $nodeName;

    public function __construct(
        string $nodeName,
        PrincipalBackendInterface $principalBackend,
        CalDAVBackendInterface $caldavBackend,
        string $principalPrefix
    ) {
        parent::__construct($principalBackend, $caldavBackend, $principalPrefix);
        $this->nodeName = $nodeName;
    }

    public function getName()
    {
        return $this->nodeName;
    }
}
