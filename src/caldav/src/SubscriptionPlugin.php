<?php
/**
 * SubscriptionPlugin - Read-only enforcement on subscription calendars.
 *
 * Subscription calendars are owned by SUBSCRIPTION principals and shared
 * read-only with subscribing users. The only writer is the sync worker,
 * which goes through the internal API (X-LS-Internal-Api-Key auth). All
 * user-initiated writes must 403.
 *
 * Hooks:
 *   - beforeMethod:PUT / DELETE / MOVE / PROPPATCH / MKCOL / MKCALENDAR
 *     at priority 80 (runs before the default write handlers).
 *   - method:POST at priority 80 (blocks CS:share edits on the owner
 *     calendar path, mirroring the MailboxPlugin pattern).
 *
 * Internal-API writes (sync worker) bypass this plugin because the
 * internal API dispatcher short-circuits all /internal-api/ routes
 * before beforeMethod fires. This plugin only inspects regular CalDAV
 * paths (calendars/subscriptions/..., calendars/users/<email>/<uri>).
 */

namespace Calendars\SabreDav;

use Sabre\DAV\Server;
use Sabre\DAV\ServerPlugin;
use Sabre\HTTP\RequestInterface;
use Sabre\HTTP\ResponseInterface;

class SubscriptionPlugin extends ServerPlugin
{
    /** @var Server */
    protected $server;

    /** @var \PDO */
    private $pdo;

    /** @var array<int,bool> Per-request cache: calendarId → isSubscriptionOwned */
    private $ownerCache = [];

    public function __construct(\PDO $pdo)
    {
        $this->pdo = $pdo;
    }

    public function getPluginName()
    {
        return 'subscription';
    }

    public function initialize(Server $server)
    {
        $this->server = $server;

        $verbs = ['PUT', 'DELETE', 'MOVE', 'PROPPATCH', 'MKCOL', 'MKCALENDAR'];
        foreach ($verbs as $verb) {
            // Priority 80: run before the default SabreDAV handlers
            // (which live at priority 100+).
            $server->on('beforeMethod:' . $verb, [$this, 'blockWrite'], 80);
        }

        // Block CS:share POST on subscription calendars so users can't
        // manually re-share or change access levels.
        $server->on('method:POST', [$this, 'blockSharePost'], 80);
    }

    /**
     * Reject any write verb that targets a subscription calendar or one
     * of its objects. Returns null when the path is unrelated.
     */
    public function blockWrite(RequestInterface $request, ResponseInterface $response)
    {
        $path = $request->getPath();
        if (!$this->pathIsUnderSubscription($path)) {
            return;
        }
        throw new \Sabre\DAV\Exception\Forbidden(
            'Cannot modify events in a subscription calendar.'
        );
    }

    /**
     * Reject CS:share POST on the owner-side subscription calendar.
     * User-side shares live under ``calendars/users/<email>/...`` and
     * are blocked by ``blockWrite`` (POST is not a write verb above,
     * but CS:share's content-type is XML and we intercept it here).
     */
    public function blockSharePost(RequestInterface $request, ResponseInterface $response)
    {
        $path = $request->getPath();
        if (!$this->pathIsUnderSubscription($path)) {
            return;
        }
        $contentType = $request->getHeader('Content-Type') ?? '';
        if (strpos($contentType, 'xml') === false) {
            return;
        }
        throw new \Sabre\DAV\Exception\Forbidden(
            'Subscription calendars cannot be reshared.'
        );
    }

    /**
     * Whether a CalDAV path targets a subscription calendar — either by
     * living under ``calendars/subscriptions/...`` (the owner side) or
     * by resolving to a calendar whose owner principal is a SUBSCRIPTION.
     */
    private function pathIsUnderSubscription(string $path): bool
    {
        $normalised = ltrim($path, '/');

        // Owner-side path — always a subscription calendar.
        if (strpos($normalised, 'calendars/subscriptions/') === 0) {
            return true;
        }

        // User-side path: need to resolve calendarid → owner principal.
        if (!preg_match('#^calendars/users/([^/]+)/([^/]+)#', $normalised, $matches)) {
            return false;
        }
        $userPrincipal = 'principals/users/' . urldecode($matches[1]);
        $calendarUri = urldecode($matches[2]);

        try {
            $stmt = $this->pdo->prepare(
                'SELECT calendarid FROM calendarinstances'
                . ' WHERE principaluri = ? AND uri = ? LIMIT 1'
            );
            $stmt->execute([$userPrincipal, $calendarUri]);
            $calendarId = $stmt->fetchColumn();
            if ($calendarId === false) {
                return false;
            }
            $calendarId = (int) $calendarId;

            if (array_key_exists($calendarId, $this->ownerCache)) {
                return $this->ownerCache[$calendarId];
            }

            $stmt = $this->pdo->prepare(
                'SELECT p.calendar_user_type FROM calendarinstances owner_ci'
                . ' JOIN principals p ON p.uri = owner_ci.principaluri'
                . ' WHERE owner_ci.calendarid = ? AND owner_ci.access = 1 LIMIT 1'
            );
            $stmt->execute([$calendarId]);
            $type = $stmt->fetchColumn();
            $isSubscription = ($type === PrincipalBackend::TYPE_SUBSCRIPTION);
            $this->ownerCache[$calendarId] = $isSubscription;
            return $isSubscription;
        } catch (\Exception $e) {
            error_log('[SubscriptionPlugin] DB error: ' . $e->getMessage());
            // Fail closed — better to 403 a legitimate write than to
            // let a subscription-calendar write slip through.
            return true;
        }
    }
}
