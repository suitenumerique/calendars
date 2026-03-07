<?php
/**
 * Custom root node for the /principals/ collection.
 *
 * SabreDAV's built-in Principal\Collection uses getName() = basename($prefix),
 * so Principal\Collection('principals/users') would appear at /users/ in the
 * tree, not /principals/users/. This node sits at /principals/ and delegates
 * to child Principal\Collection nodes:
 *   principals/users/{email}          → Principal\Collection(prefix='principals/users')
 *   principals/resources/{id}       → Principal\Collection(prefix='principals/resources')
 *
 */

namespace Calendars\SabreDav;

use Sabre\CalDAV;
use Sabre\DAV;
use Sabre\DAVACL;
use Sabre\DAVACL\PrincipalBackend\BackendInterface as PrincipalBackendInterface;

class PrincipalsRoot extends DAV\Collection
{
    /** @var DAV\INode[] */
    private $children;

    public function __construct(PrincipalBackendInterface $principalBackend)
    {
        $this->children = [
            new NamedPrincipalCollection('users', $principalBackend, 'principals/users'),
            new ResourcePrincipalCollection('resources', $principalBackend, 'principals/resources'),
        ];
    }

    public function getName()
    {
        return 'principals';
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
 * A Principal\Collection whose getName() returns a custom value.
 *
 * Used as a child of PrincipalsRoot so that:
 *   principals/users/      → NamedPrincipalCollection('users', ..., 'principals/users')
 *   principals/resources/  → NamedPrincipalCollection('resources', ..., 'principals/resources')
 */
class NamedPrincipalCollection extends CalDAV\Principal\Collection
{
    /** @var string */
    private $nodeName;

    public function __construct(
        string $nodeName,
        PrincipalBackendInterface $principalBackend,
        string $principalPrefix
    ) {
        parent::__construct($principalBackend, $principalPrefix);
        $this->nodeName = $nodeName;
    }

    public function getName()
    {
        return $this->nodeName;
    }
}

/**
 * Principal collection for resources that returns ResourcePrincipal nodes.
 *
 * Resource principals have no DAV owner, so the default ACL (which only
 * grants {DAV:}all to {DAV:}owner) blocks all property reads with 403.
 * This collection returns ResourcePrincipal nodes that additionally grant
 * {DAV:}read to {DAV:}authenticated, allowing any logged-in user to
 * discover resource names, types, and emails via PROPFIND.
 */
class ResourcePrincipalCollection extends NamedPrincipalCollection
{
    public function getChildForPrincipal(array $principal)
    {
        return new ResourcePrincipal($this->principalBackend, $principal);
    }
}

/**
 * A principal node with a permissive read ACL for resource discovery.
 */
class ResourcePrincipal extends CalDAV\Principal\User
{
    public function getACL()
    {
        return [
            [
                'privilege' => '{DAV:}all',
                'principal' => '{DAV:}owner',
                'protected' => true,
            ],
            [
                'privilege' => '{DAV:}read',
                'principal' => '{DAV:}authenticated',
                'protected' => true,
            ],
        ];
    }
}
