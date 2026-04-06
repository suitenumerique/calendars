<?php

namespace Calendars\SabreDav;

use Sabre\DAV;
use Sabre\HTTP\RequestInterface;

/**
 * Enforces organization-scoped freebusy access.
 *
 * 1. Blocks VFREEBUSY outbox queries when sharing level is "none".
 * 2. Blocks free-busy-query REPORT on calendars owned by users in
 *    a different organization.
 *
 * The X-LS-Org-Id header is set by the Django proxy based on
 * the authenticated user's organization.
 */
class FreeBusyOrgScopePlugin extends DAV\ServerPlugin
{
    protected $server;

    /** @var \PDO */
    private $pdo;

    public function __construct(\PDO $pdo)
    {
        $this->pdo = $pdo;
    }

    public function initialize(DAV\Server $server)
    {
        $this->server = $server;
        // Before Schedule\Plugin processes outbox freebusy
        $server->on('beforeMethod:POST', [$this, 'beforePost'], 99);
        // Before CalDAV\Plugin processes free-busy-query REPORT
        $server->on('beforeMethod:REPORT', [$this, 'beforeReport'], 99);
    }

    /**
     * Block VFREEBUSY outbox queries when sharing level is "none".
     */
    public function beforePost(RequestInterface $request)
    {
        $path = $request->getPath();

        if (strpos($path, '/outbox') === false) {
            return;
        }

        $sharingLevel = $request->getHeader('X-LS-Org-Sharing-Level');

        if ($sharingLevel !== 'none') {
            return;
        }

        $body = $request->getBodyAsString();
        $request->setBody($body);

        if (stripos($body, 'VFREEBUSY') !== false) {
            throw new DAV\Exception\Forbidden(
                'Free/busy queries are not allowed when organization sharing is disabled'
            );
        }
    }

    /**
     * Enforce sharing level on free-busy-query REPORT.
     *
     * SabreDAV grants {CALDAV}read-free-busy to all authenticated users.
     * We restrict based on:
     * - Cross-org: always blocked
     * - Same-org, sharing_level=none: blocked
     * - Same-org, sharing_level=freebusy/read/write: allowed
     */
    public function beforeReport(RequestInterface $request)
    {
        $body = $request->getBodyAsString();
        $request->setBody($body);

        if (stripos($body, 'free-busy-query') === false) {
            return;
        }

        $path = $request->getPath();

        if (!preg_match('#^calendars/users/([^/]+)/#', $path, $matches)) {
            return;
        }

        $targetEmail = urldecode($matches[1]);
        $requesterEmail = $request->getHeader('X-LS-User');

        // Own calendars: always allowed
        if ($targetEmail === $requesterEmail) {
            return;
        }

        $sharingLevel = $request->getHeader('X-LS-Org-Sharing-Level');

        // sharing_level=none: block all freebusy (even same-org)
        if ($sharingLevel === 'none') {
            throw new DAV\Exception\Forbidden(
                'Free/busy queries are not allowed when sharing is disabled'
            );
        }

        // Cross-org: always blocked
        $requesterOrgId = $request->getHeader('X-LS-Org-Id');
        if (!$requesterOrgId) {
            return;
        }

        try {
            $stmt = $this->pdo->prepare(
                'SELECT org_id FROM principals WHERE uri = ?'
            );
            $stmt->execute(['principals/users/' . $targetEmail]);
            $row = $stmt->fetch(\PDO::FETCH_ASSOC);

            if ($row && $row['org_id'] && $row['org_id'] !== $requesterOrgId) {
                throw new DAV\Exception\Forbidden(
                    'Cross-organization free/busy queries are not allowed'
                );
            }
        } catch (DAV\Exception\Forbidden $e) {
            throw $e;
        } catch (\Exception $e) {
            error_log("[FreeBusyOrgScopePlugin] Error: " . $e->getMessage());
        }
    }

    public function getPluginName()
    {
        return 'freebusy-org-scope';
    }

    public function getPluginInfo()
    {
        return [
            'name' => $this->getPluginName(),
            'description' => 'Enforces organization-level freebusy sharing settings',
        ];
    }
}
