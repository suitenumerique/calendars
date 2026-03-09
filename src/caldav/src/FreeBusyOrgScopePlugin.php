<?php

namespace Calendars\SabreDav;

use Sabre\DAV;
use Sabre\HTTP\RequestInterface;

/**
 * Blocks VFREEBUSY queries when the organization sharing level is "none".
 *
 * The X-CalDAV-Sharing-Level header is set by the Django proxy based on
 * the organization's effective sharing level setting.
 *
 * Regular scheduling requests (invitations) are not affected.
 */
class FreeBusyOrgScopePlugin extends DAV\ServerPlugin
{
    protected $server;

    public function initialize(DAV\Server $server)
    {
        $this->server = $server;
        // Priority 99: before Schedule\Plugin (110) processes freebusy
        $server->on('beforeMethod:POST', [$this, 'beforePost'], 99);
    }

    /**
     * Intercept POST to scheduling outbox and block VFREEBUSY if sharing is "none".
     */
    public function beforePost(RequestInterface $request)
    {
        $path = $request->getPath();

        // Only intercept outbox requests (where freebusy queries are sent)
        if (strpos($path, '/outbox') === false) {
            return;
        }

        $sharingLevel = $request->getHeader('X-CalDAV-Sharing-Level');

        // Only block when sharing is explicitly disabled
        if ($sharingLevel !== 'none') {
            return;
        }

        // Read body to check if this is a VFREEBUSY request
        $body = $request->getBodyAsString();
        $request->setBody($body); // Reset stream for subsequent reads

        if (stripos($body, 'VFREEBUSY') !== false) {
            throw new DAV\Exception\Forbidden(
                'Free/busy queries are not allowed when organization sharing is disabled'
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
