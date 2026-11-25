<?php
/**
 * AuditContextPlugin - Injects principal and channel context into the backend.
 *
 * The principal belongs to the request. The plugin sets it once, on
 * beforeMethod:* at priority 15, after the authentication (10). Thus each
 * backend write of the request has an author. This includes the writes
 * that emit no beforeCreateFile or beforeWriteContent: a MOVE, a write by
 * another plugin, a write by the internal API.
 *
 * The channel belongs to the object that the request writes. The plugin
 * sets it just before this write and clears it after. A write in another
 * calendar, for example a scheduling update of the organizer's copy,
 * keeps the channel of its event.
 *
 * Reads:
 *   X-LS-User header → setCurrentPrincipal()
 *     Same header ApiKeyAuthBackend uses for authentication, so the
 *     audit principal can NEVER drift from the authenticated principal
 *     and there is exactly one header carrying "who is acting".
 *   X-LS-Channel-Id header → setCurrentChannelId() (with UUID validation)
 *     X-LS-* prefix matches every other internal proxy→SabreDAV
 *     header, so the proxy's defensive HTTP_X_LS_* strip covers it
 *     and there are no leftover non-X-LS-* internal headers.
 */

namespace Calendars\SabreDav;

use Sabre\DAV\Server;
use Sabre\DAV\ServerPlugin;

class AuditContextPlugin extends ServerPlugin
{
    /** @var Server */
    protected $server;

    /** @var AuditCalDAVBackend */
    private $caldavBackend;

    public function __construct(AuditCalDAVBackend $caldavBackend)
    {
        $this->caldavBackend = $caldavBackend;
    }

    public function getPluginName()
    {
        return 'audit-context';
    }

    public function initialize(Server $server)
    {
        $this->server = $server;

        // Priority 15: after the authentication (10), before all the writes.
        $server->on('beforeMethod:*', [$this, 'injectPrincipal'], 15);

        // Priority 1000: after the CalDAV plugin (100), which makes the
        // scheduling writes in other calendars.
        $server->on('beforeCreateFile', [$this, 'applyChannel'], 1000);
        $server->on('beforeWriteContent', [$this, 'applyChannel'], 1000);
        $server->on('afterCreateFile', [$this, 'clearChannel'], 10);
        $server->on('afterWriteContent', [$this, 'clearChannel'], 10);
    }

    public function injectPrincipal(): void
    {
        $request = $this->server->httpRequest;

        // Set principal from the same X-LS-User header that
        // ApiKeyAuthBackend uses for authentication. Reusing the
        // auth header guarantees the audit principal cannot drift
        // from the authenticated one — there is exactly one source
        // of "who is acting" on the request.
        $user = $request->getHeader('X-LS-User');
        if ($user) {
            $this->caldavBackend->setCurrentPrincipal($user);
        }
    }

    /**
     * Set the channel ID from the X-LS-Channel-Id header, with UUID
     * validation, for the next writes.
     */
    public function applyChannel(): void
    {
        $channelId = $this->server->httpRequest->getHeader('X-LS-Channel-Id');
        if ($channelId && $this->isValidUuid($channelId)) {
            $this->caldavBackend->setCurrentChannelId($channelId);
        } else {
            $this->caldavBackend->setCurrentChannelId(null);
        }
    }

    public function clearChannel(): void
    {
        $this->caldavBackend->setCurrentChannelId(null);
    }

    /**
     * Validate a UUID v4 string.
     */
    private function isValidUuid(string $value): bool
    {
        return (bool) preg_match(
            '/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i',
            $value
        );
    }

    public function getPluginInfo()
    {
        return [
            'name' => $this->getPluginName(),
            'description' => 'Injects audit context (principal, channel) into the CalDAV backend',
        ];
    }
}
