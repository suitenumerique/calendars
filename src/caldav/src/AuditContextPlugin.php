<?php
/**
 * AuditContextPlugin - Injects principal and channel context into the backend.
 *
 * Hooks beforeCreateFile and beforeWriteContent at priority 70 (before
 * CalendarSanitizerPlugin at 85 and AttendeeNormalizerPlugin at 90) so
 * that the audit context is available when the backend write happens.
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

        // Priority 70: before sanitizer (85), normalizer (90), and CalDAV (100+)
        $server->on('beforeCreateFile', [$this, 'injectContext'], 70);
        $server->on('beforeWriteContent', [$this, 'injectContext'], 70);
    }

    /**
     * Inject audit context from HTTP headers into the backend.
     *
     * Accepts variable arguments because beforeCreateFile and
     * beforeWriteContent have different signatures.
     */
    public function injectContext(): void
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

        // Set channel ID from X-LS-Channel-Id header (with UUID validation)
        $channelId = $request->getHeader('X-LS-Channel-Id');
        if ($channelId && $this->isValidUuid($channelId)) {
            $this->caldavBackend->setCurrentChannelId($channelId);
        } else {
            $this->caldavBackend->setCurrentChannelId(null);
        }
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
