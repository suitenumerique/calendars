<?php
/**
 * Custom principal backend with auto-creation and org-scoped discovery.
 *
 * - Auto-creates principals (without calendars) on first access
 * - Filters searchPrincipals() and getPrincipalsByPrefix() by org_id
 * - Does NOT filter getPrincipalByPath() (allows cross-org sharing)
 *
 * Mailbox address injection is handled by MailboxPlugin (propFind).
 */

namespace Calendars\SabreDav;

use Sabre\DAVACL\PrincipalBackend\PDO as BasePDO;

class PrincipalBackend extends BasePDO
{
    const TYPE_INDIVIDUAL = 'INDIVIDUAL';
    const TYPE_MAILBOX = 'MAILBOX';
    const ACCESS_OWNER = 1;
    const ACCESS_READ = 2;
    const ACCESS_READ_WRITE = 3;

    /**
     * Extend the default field map to include calendar-user-type.
     *
     * @see https://github.com/sabre-io/dav/blob/master/lib/DAVACL/PrincipalBackend/PDO.php
     * @see https://github.com/sabre-io/dav/blob/master/lib/CalDAV/Schedule/Plugin.php
     */
    protected $fieldMap = [
        '{DAV:}displayname' => [
            'dbField' => 'displayname',
        ],
        '{http://sabredav.org/ns}email-address' => [
            'dbField' => 'email',
        ],
        '{urn:ietf:params:xml:ns:caldav}calendar-user-type' => [
            'dbField' => 'calendar_user_type',
        ],
    ];

    /**
     * @var \Sabre\DAV\Server|null
     */
    private $server = null;

    /**
     * Set the server reference (called from server.php after server creation).
     *
     * @param \Sabre\DAV\Server $server
     */
    public function setServer(\Sabre\DAV\Server $server)
    {
        $this->server = $server;
    }

    /**
     * Get the org_id from the current HTTP request's X-LS-Org-Id header.
     *
     * @return string|null
     */
    private function getRequestOrgId()
    {
        if ($this->server && $this->server->httpRequest) {
            return $this->server->httpRequest->getHeader('X-LS-Org-Id');
        }
        return null;
    }

    /**
     * Returns a specific principal, specified by its path.
     *
     * Auto-creates the principal (without a calendar) if it doesn't exist.
     * NOT org-filtered: allows cross-org sharing and scheduling.
     *
     * @param string $path
     * @return array|null
     */
    public function getPrincipalByPath($path)
    {
        $principal = parent::getPrincipalByPath($path);

        if (!$principal && strpos($path, 'principals/users/') === 0) {
            $email = substr($path, strlen('principals/users/'));
            $principal = $this->ensurePrincipal($email);
        }

        return $principal;
    }

    /**
     * Find a principal by URI (e.g. mailto:bob@company.com).
     *
     * Auto-creates a USER principal when the email is unknown so that
     * CS:share can resolve any mailto: URI to a principal — but ONLY
     * when the caller is iterating the ``principals/users`` collection
     * and ONLY when the email does not already belong to a principal
     * in another collection (e.g. ``principals/resources``).
     *
     * Without those guards, ``DAVACL\Plugin::getPrincipalByUri`` —
     * which iterates ``principalCollectionSet = ['principals/users',
     * 'principals/resources']`` and returns the first match — would
     * see our override mint a fresh user row for a resource email and
     * stop iterating before ever asking the ``principals/resources``
     * collection. iTIP delivery to resources would then never reach
     * ``ResourceAutoSchedulePlugin``.
     *
     * @param string $uri
     * @param string $principalPrefix
     * @return string|null Principal path or null
     */
    public function findByUri($uri, $principalPrefix)
    {
        $result = parent::findByUri($uri, $principalPrefix);
        if ($result) {
            return $result;
        }

        if (!str_starts_with($uri, 'mailto:')) {
            return null;
        }
        $email = substr($uri, 7);

        // Before falling through to auto-create, check whether this
        // email already belongs to a principal in ANY collection. If
        // so, return null and let ``DAVACL\Plugin::getPrincipalByUri``
        // continue iterating until it asks the matching collection's
        // own ``findByUri`` round, where the parent implementation
        // will resolve it via the prefix-aware query.
        if ($this->principalExistsForEmail($email)) {
            return null;
        }

        // Auto-create only user principals. Resources are provisioned
        // via the internal API and never auto-created here.
        if ($principalPrefix !== 'principals/users') {
            return null;
        }

        $principal = $this->ensurePrincipal($email);
        return $principal['uri'] ?? null;
    }

    /**
     * Whether any principal (in any collection) currently has the
     * given email. Used by ``findByUri`` to avoid auto-creating a
     * user when a resource (or another collection) already owns the
     * address.
     */
    private function principalExistsForEmail(string $email): bool
    {
        try {
            $stmt = $this->pdo->prepare(
                'SELECT 1 FROM ' . $this->tableName
                . ' WHERE lower(email) = lower(?) LIMIT 1'
            );
            $stmt->execute([$email]);
            return (bool) $stmt->fetchColumn();
        } catch (\Exception $e) {
            error_log("[PrincipalBackend] principalExistsForEmail failed: " . $e->getMessage());
            // Fail-closed: when in doubt, don't auto-create — better to
            // leak a "no such recipient" than to overwrite a resource.
            return true;
        }
    }

    /**
     * Ensure a user principal exists (create if missing, no calendar).
     *
     * @param string $email
     * @return array|null The principal, or null on failure.
     */
    private function ensurePrincipal($email)
    {
        $path = 'principals/users/' . $email;
        $orgId = $this->getRequestOrgId();

        try {
            // DO NOTHING on conflict: this is a lightweight auto-create for
            // sharing/scheduling. The canonical path for setting org_id and
            // calendar_user_type is POST /internal-api/calendars/ (setup flow).
            $stmt = $this->pdo->prepare(
                'INSERT INTO ' . $this->tableName
                . ' (uri, email, displayname, calendar_user_type, org_id)'
                . ' VALUES (?, ?, ?, ?, ?)'
                . ' ON CONFLICT (uri) DO NOTHING'
            );
            $stmt->execute([$path, $email, $email, self::TYPE_INDIVIDUAL, $orgId]);
            return parent::getPrincipalByPath($path);
        } catch (\Exception $e) {
            error_log("[PrincipalBackend] Failed to ensure principal for $email: " . $e->getMessage());
            return null;
        }
    }

    /**
     * Returns a list of principals based on a prefix.
     *
     * Org-filtered: only returns principals from the requesting user's org.
     *
     * @param string $prefixPath
     * @return array
     */
    public function getPrincipalsByPrefix($prefixPath)
    {
        $principals = parent::getPrincipalsByPrefix($prefixPath);

        $orgId = $this->getRequestOrgId();
        if (!$orgId) {
            return $principals;
        }

        // Filter by org_id
        $filteredUris = $this->getOrgPrincipalUris($prefixPath, $orgId);
        if ($filteredUris === null) {
            return $principals;
        }

        return array_values(array_filter($principals, function ($principal) use ($filteredUris) {
            return in_array($principal['uri'], $filteredUris, true);
        }));
    }

    /**
     * Search principals matching certain criteria.
     *
     * Org-filtered: only returns principals from the requesting user's org.
     *
     * @param string $prefixPath
     * @param array $searchProperties
     * @param string $test
     * @return array
     */
    public function searchPrincipals($prefixPath, array $searchProperties, $test = 'allof')
    {
        $results = parent::searchPrincipals($prefixPath, $searchProperties, $test);

        $orgId = $this->getRequestOrgId();
        if (!$orgId) {
            return $results;
        }

        $filteredUris = $this->getOrgPrincipalUris($prefixPath, $orgId);
        if ($filteredUris === null) {
            return $results;
        }

        return array_values(array_filter($results, function ($uri) use ($filteredUris) {
            return in_array($uri, $filteredUris, true);
        }));
    }

    /**
     * Get principal URIs for a given prefix and org_id.
     *
     * @param string $prefixPath
     * @param string $orgId
     * @return array|null
     */
    private function getOrgPrincipalUris($prefixPath, $orgId)
    {
        try {
            $stmt = $this->pdo->prepare(
                'SELECT uri FROM ' . $this->tableName
                . ' WHERE uri LIKE ? AND org_id = ?'
            );
            $stmt->execute([$prefixPath . '/%', $orgId]);
            return $stmt->fetchAll(\PDO::FETCH_COLUMN, 0);
        } catch (\Exception $e) {
            error_log("Failed to query org principals: " . $e->getMessage());
            return null;
        }
    }
}
