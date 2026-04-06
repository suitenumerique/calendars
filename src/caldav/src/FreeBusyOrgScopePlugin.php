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

        // Missing/empty header is treated as "none" (fail-closed).
        $sharingLevel = $request->getHeader('X-LS-Org-Sharing-Level');
        if ($sharingLevel !== null && $sharingLevel !== '' && $sharingLevel !== 'none') {
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

        // Missing/empty/none header: block all freebusy (fail-closed, even same-org).
        $sharingLevel = $request->getHeader('X-LS-Org-Sharing-Level');
        if ($sharingLevel === null || $sharingLevel === '' || $sharingLevel === 'none') {
            throw new DAV\Exception\Forbidden(
                'Free/busy queries are not allowed when sharing is disabled'
            );
        }

        // Cross-org: always blocked. Fail-closed on missing header or DB error.
        $requesterOrgId = $request->getHeader('X-LS-Org-Id');
        if (!$requesterOrgId) {
            throw new DAV\Exception\Forbidden(
                'Organization header required for cross-calendar freebusy queries'
            );
        }

        try {
            $stmt = $this->pdo->prepare(
                'SELECT org_id FROM principals WHERE uri = ?'
            );
            $stmt->execute(['principals/users/' . $targetEmail]);
            $row = $stmt->fetch(\PDO::FETCH_ASSOC);

            // Fail-closed: a missing principal or one with no org_id
            // (e.g. a mailbox principal whose org isn't registered yet)
            // must not leak freebusy data to anyone outside its own org.
            if (!$row || empty($row['org_id'])) {
                throw new DAV\Exception\Forbidden(
                    'Cannot verify organization for freebusy query'
                );
            }
            if ($row['org_id'] !== $requesterOrgId) {
                throw new DAV\Exception\Forbidden(
                    'Cross-organization free/busy queries are not allowed'
                );
            }
        } catch (DAV\Exception\Forbidden $e) {
            throw $e;
        } catch (\Exception $e) {
            error_log("[FreeBusyOrgScopePlugin] DB error: " . $e->getMessage());
            throw new DAV\Exception\Forbidden(
                'Cannot verify organization for freebusy query'
            );
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
