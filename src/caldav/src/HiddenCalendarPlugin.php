<?php
/**
 * HiddenCalendarPlugin - Lets a user hide a calendar for themselves, in the
 * web app and in their CalDAV clients. The user keeps access.
 *
 * The LS:calendar-hidden property marks a sharee instance as hidden for
 * its user. The mailbox ACL sync keeps the instance URI, so the property
 * stays.
 *
 * A PROPFIND on a calendar home leaves hidden instances out, unless the
 * request has the "X-LS-Include-Hidden: true" header. Direct URLs,
 * free/busy and scheduling still use hidden instances.
 *
 * A DELETE of a sync-managed instance hides it.
 */

namespace Calendars\SabreDav;

use Sabre\CalDAV\SharedCalendar;
use Sabre\DAV\Exception\Forbidden;
use Sabre\DAV\Exception\NotFound;
use Sabre\DAV\PropPatch;
use Sabre\DAV\Server;
use Sabre\DAV\ServerPlugin;
use Sabre\DAV\Sharing\Plugin as SharingPlugin;
use Sabre\HTTP\RequestInterface;
use Sabre\HTTP\ResponseInterface;

class HiddenCalendarPlugin extends ServerPlugin
{
    const HIDDEN_PROP = '{http://lasuite.numerique.gouv.fr/ns/}calendar-hidden';

    const INCLUDE_HIDDEN_HEADER = 'X-LS-Include-Hidden';

    /** @var Server */
    protected $server;

    /** @var \PDO */
    private $pdo;

    public function __construct(\PDO $pdo)
    {
        $this->pdo = $pdo;
    }

    public function getPluginName()
    {
        return 'hidden-calendar';
    }

    public function initialize(Server $server)
    {
        $this->server = $server;
        $server->on('beforeMethod:PROPFIND', [$this, 'filterHomeListing']);
        // Before PropertyStorage (300) stores the property.
        $server->on('propPatch', [$this, 'validateHiddenProp'], 90);
        // Before CorePlugin (100) deletes the node.
        $server->on('method:DELETE', [$this, 'hideSyncManagedInstance'], 90);
    }

    /**
     * Leave hidden calendars out of a PROPFIND on a calendar home.
     *
     * Only the home node of this request gets the filter. Free/busy and
     * scheduling read the home in other requests, so they still see
     * hidden calendars.
     */
    public function filterHomeListing(RequestInterface $request, ResponseInterface $response)
    {
        if ($request->getHeader(self::INCLUDE_HIDDEN_HEADER) === 'true') {
            return;
        }

        $path = $request->getPath();
        try {
            $node = $this->server->tree->getNodeForPath($path);
        } catch (NotFound $e) {
            return;
        }

        if ($node instanceof CustomCalendarHome) {
            $node->excludeHiddenCalendars($path);
        }
    }

    /**
     * Accept LS:calendar-hidden only as "true" or as a removal, and only
     * on a sharee instance. An owner deletes their calendar instead.
     */
    public function validateHiddenProp($path, PropPatch $propPatch)
    {
        $mutations = $propPatch->getMutations();
        if (!array_key_exists(self::HIDDEN_PROP, $mutations)) {
            return;
        }

        $value = $mutations[self::HIDDEN_PROP];
        if ($value !== null && $value !== 'true') {
            $propPatch->setResultCode(self::HIDDEN_PROP, 400);
            return;
        }

        $node = $this->server->tree->getNodeForPath($path);
        if (!$node instanceof SharedCalendar || in_array(
            $node->getShareAccess(),
            [SharingPlugin::ACCESS_SHAREDOWNER, SharingPlugin::ACCESS_NOTSHARED],
            true
        )) {
            $propPatch->setResultCode(self::HIDDEN_PROP, 403);
        }
    }

    /**
     * Hide a sync-managed instance instead of deleting it.
     *
     * The ACL plugin checks the unbind privilege in beforeUnbind, which
     * this hook skips. So it checks write-properties itself, as for a
     * PROPPATCH.
     *
     * @return bool|null
     */
    public function hideSyncManagedInstance(RequestInterface $request, ResponseInterface $response)
    {
        $path = $request->getPath();
        if (!preg_match('#^calendars/users/([^/]+)/([^/]+)$#', $path, $matches)) {
            return;
        }
        if (!$this->isSyncManaged('principals/users/' . $matches[1], $matches[2])) {
            return;
        }

        $this->server->getPlugin('acl')->checkPrivileges($path, '{DAV:}write-properties');

        $result = $this->server->updateProperties($path, [self::HIDDEN_PROP => 'true']);
        if (($result[self::HIDDEN_PROP] ?? null) !== 200) {
            throw new Forbidden('This calendar cannot be hidden.');
        }

        $response->setStatus(204);
        $response->setHeader('Content-Length', '0');
        return false;
    }

    private function isSyncManaged(string $principalUri, string $calendarUri): bool
    {
        $stmt = $this->pdo->prepare(
            'SELECT 1 FROM calendarinstances '
            . 'WHERE principaluri = ? AND uri = ? AND is_sync_managed = TRUE '
            . 'LIMIT 1'
        );
        $stmt->execute([$principalUri, $calendarUri]);
        return (bool) $stmt->fetchColumn();
    }
}
