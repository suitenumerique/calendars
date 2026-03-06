<?php
/**
 * Custom principal backend that auto-creates principals when they don't exist
 * and supports org-scoped discovery.
 *
 * - Auto-creates principals on first access (for OIDC-authenticated users)
 * - Stores org_id and calendar_user_type on principals
 * - Filters searchPrincipals() and getPrincipalsByPrefix() by org_id
 * - Does NOT filter getPrincipalByPath() (allows cross-org sharing)
 */

namespace Calendars\SabreDav;

use Sabre\DAVACL\PrincipalBackend\PDO as BasePDO;
use Sabre\DAV\MkCol;

class AutoCreatePrincipalBackend extends BasePDO
{
    /**
     * Extend the default field map to include calendar-user-type.
     *
     * SabreDAV's PDO principal backend uses $fieldMap to map WebDAV property
     * names to database columns. The base class only maps displayname and email.
     * The Schedule\Plugin hardcodes calendar-user-type to 'INDIVIDUAL' via a
     * propFind handler, but that handler uses handle() which is a no-op when
     * the property is already set. By adding calendar-user-type to the fieldMap,
     * the Principal node exposes the real value from the DB via getProperties(),
     * and the Schedule\Plugin's hardcoded 'INDIVIDUAL' only serves as a fallback
     * for principals that don't have the column set.
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
     * Get the org_id from the current HTTP request's X-CalDAV-Organization header.
     *
     * @return string|null
     */
    private function getRequestOrgId()
    {
        if ($this->server && $this->server->httpRequest) {
            return $this->server->httpRequest->getHeader('X-CalDAV-Organization');
        }
        return null;
    }

    /**
     * Returns a specific principal, specified by its path.
     * Auto-creates the principal if it doesn't exist.
     *
     * NOT org-filtered: allows cross-org sharing and scheduling.
     *
     * @param string $path
     * @return array|null
     */
    public function getPrincipalByPath($path)
    {
        $principal = parent::getPrincipalByPath($path);

        // If principal doesn't exist, create it automatically
        // Only auto-create user principals (principals/users/*).
        // Resource principals (principals/resources/*) are provisioned via Django.
        if (!$principal && strpos($path, 'principals/users/') === 0) {
            // Extract username from path
            $username = substr($path, strlen('principals/users/'));

            $pdo = $this->pdo;
            $tableName = $this->tableName;
            $orgId = $this->getRequestOrgId();

            try {
                $stmt = $pdo->prepare(
                    'INSERT INTO ' . $tableName
                    . ' (uri, email, displayname, calendar_user_type, org_id)'
                    . ' VALUES (?, ?, ?, ?, ?)'
                    . ' ON CONFLICT (uri) DO UPDATE SET org_id = COALESCE(EXCLUDED.org_id, '
                    . $tableName . '.org_id)'
                );
                $stmt->execute([$path, $username, $username, 'INDIVIDUAL', $orgId]);

                // Retry getting the principal
                $principal = parent::getPrincipalByPath($path);
            } catch (\Exception $e) {
                error_log("Failed to auto-create principal: " . $e->getMessage());
                return null;
            }
        }

        return $principal;
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
