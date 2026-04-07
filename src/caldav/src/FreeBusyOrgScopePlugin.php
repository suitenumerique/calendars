<?php

namespace Calendars\SabreDav;

use Sabre\DAV;
use Sabre\HTTP\RequestInterface;
use Sabre\VObject\Reader as VObjectReader;

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
     *
     * Detects VFREEBUSY structurally via ``VObject\Reader`` so the check
     * cannot be tricked by an iTIP REQUEST whose ``SUMMARY`` /
     * ``DESCRIPTION`` happens to contain the literal text ``VFREEBUSY``.
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

        if ($body === '' || !$this->bodyContainsVFreebusyComponent($body)) {
            return;
        }

        throw new DAV\Exception\Forbidden(
            'Free/busy queries are not allowed when organization sharing is disabled'
        );
    }

    /**
     * Whether the iCalendar body contains an actual ``VFREEBUSY``
     * component (not just the literal text in some property value).
     */
    private function bodyContainsVFreebusyComponent(string $body): bool
    {
        try {
            $vobject = VObjectReader::read($body);
        } catch (\Exception $e) {
            // Malformed body — leave the rejection to the next handler
            // rather than masking it as a freebusy block here.
            return false;
        }
        return isset($vobject->VFREEBUSY);
    }

    /**
     * Enforce sharing level on free-busy-query REPORT.
     *
     * SabreDAV grants {CALDAV}read-free-busy to all authenticated users.
     * We restrict based on:
     * - Cross-org: always blocked
     * - Same-org, sharing_level=none: blocked
     * - Same-org, sharing_level=freebusy/read/write: allowed
     *
     * Detects ``free-busy-query`` REPORTs structurally via SabreDAV's
     * own XML deserializer (``$server->xml->parse``) so the check
     * cannot be tricked by a calendar-query whose body happens to
     * contain the literal text ``free-busy-query`` (e.g. inside a
     * ``<C:text-match>`` filter).
     */
    public function beforeReport(RequestInterface $request)
    {
        $body = $request->getBodyAsString();
        $request->setBody($body);

        if ($body === '' || !$this->bodyIsFreeBusyQuery($body, $request->getUrl())) {
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

    /**
     * Whether the XML body is a CalDAV ``{caldav}free-busy-query`` REPORT.
     *
     * Routes through ``$server->xml->parse``, the same deserializer
     * SabreDAV's own ``CalDAV\Plugin`` uses to dispatch the REPORT, so
     * the document type comes from the parser, not from a substring.
     */
    private function bodyIsFreeBusyQuery(string $body, string $url): bool
    {
        try {
            $this->server->xml->parse($body, $url, $documentType);
        } catch (\Exception $e) {
            return false;
        }
        return $documentType === '{urn:ietf:params:xml:ns:caldav}free-busy-query';
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
