<?php
/**
 * ResourceMkCalendarBlockPlugin - Blocks MKCALENDAR on resource principals.
 *
 * A resource principal has exactly one calendar (created during provisioning).
 * This plugin prevents additional calendars from being created on resource
 * principals by rejecting MKCALENDAR requests targeting resource calendar homes.
 */

namespace Calendars\SabreDav;

use Sabre\DAV\Server;
use Sabre\DAV\ServerPlugin;
use Sabre\DAV\Exception\Forbidden;

class ResourceMkCalendarBlockPlugin extends ServerPlugin
{
    /** @var Server */
    protected $server;

    public function getPluginName()
    {
        return 'resource-mkcalendar-block';
    }

    public function initialize(Server $server)
    {
        $this->server = $server;
        // Hook before MKCALENDAR is processed
        $server->on('beforeMethod:MKCALENDAR', [$this, 'beforeMkCalendar'], 90);
    }

    /**
     * Block MKCALENDAR on resource principal calendar homes.
     *
     * @param \Sabre\HTTP\RequestInterface $request
     * @param \Sabre\HTTP\ResponseInterface $response
     * @return bool|null false to stop, null to continue
     */
    public function beforeMkCalendar($request, $response)
    {
        $path = $request->getPath();

        // Check if the path is under a resource calendar home
        // Resource calendar homes: calendars/resources/{id}/
        if (preg_match('#^calendars/resources/#', $path)) {
            throw new Forbidden(
                'Resource principals can only have one calendar. '
                . 'Additional calendar creation is not allowed.'
            );
        }

        return null; // Allow for non-resource paths
    }

    public function getPluginInfo()
    {
        return [
            'name' => $this->getPluginName(),
            'description' => 'Blocks MKCALENDAR on resource principal calendar homes',
        ];
    }
}
