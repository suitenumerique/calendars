<?php
/**
 * MailboxPlugin - MAILBOX principal support for CalDAV sharing and scheduling.
 *
 * MAILBOX principals represent shared organizational mailboxes (e.g.,
 * contact@company.com). This plugin handles two aspects:
 *
 * 1. **Address injection**: Users with read-write access to a MAILBOX
 *    calendar get the mailbox email in their calendar-user-address-set.
 *    This allows SabreDAV's Schedule\Plugin to accept that email as a
 *    valid ORGANIZER when creating events on behalf of the mailbox.
 *
 * 2. **Share restriction**: Direct CalDAV shares on MAILBOX calendars
 *    are capped to read-only. Write access must come via the internal
 *    ACL sync API (Messages is the source of truth for permissions).
 *
 * Hooks:
 *   - propFind (priority 80) — injects mailbox emails into address set
 *     (runs before Schedule\Plugin at priority 100)
 *   - method:POST (priority 80) — blocks read-write CS:share on MAILBOX
 *     (runs before CalDAV\SharingPlugin at default priority 100)
 */

namespace Calendars\SabreDav;

use Sabre\CalDAV\Plugin as CalDAVPlugin;
use Sabre\CalDAV\Xml\Request\Share as ShareRequest;
use Sabre\DAV\Server;
use Sabre\DAV\ServerPlugin;
use Sabre\DAV\PropFind;
use Sabre\DAV\INode;
use Sabre\DAV\Sharing\Plugin as SharingPlugin;
use Sabre\DAV\Xml\Property\Href;
use Sabre\DAVACL\IPrincipal;
use Sabre\HTTP\RequestInterface;
use Sabre\HTTP\ResponseInterface;

class MailboxPlugin extends ServerPlugin
{
    /** @var Server */
    protected $server;

    /** @var \PDO */
    private $pdo;

    /** @var array Per-request cache for mailbox email queries */
    private $addressCache = [];

    public function __construct(\PDO $pdo)
    {
        $this->pdo = $pdo;
    }

    public function getPluginName()
    {
        return 'mailbox';
    }

    public function initialize(Server $server)
    {
        $this->server = $server;

        // Priority 80: run before Schedule\Plugin's propFind (priority 100)
        // so the address set is complete when scheduling reads it.
        $server->on('propFind', [$this, 'propFindAddresses'], 80);

        // Priority 80: run before CalDAV\SharingPlugin's httpPost (priority 100)
        // to reject read-write shares before they're processed.
        $server->on('method:POST', [$this, 'restrictSharing'], 80);
    }

    // ========================================================================
    // Address injection — calendar-user-address-set
    // ========================================================================

    /**
     * Inject mailbox emails into calendar-user-address-set for principals
     * that have read-write access to MAILBOX calendars.
     */
    public function propFindAddresses(PropFind $propFind, INode $node)
    {
        if (!$node instanceof IPrincipal) {
            return;
        }

        $CUAS = '{urn:ietf:params:xml:ns:caldav}calendar-user-address-set';

        $propFind->handle($CUAS, function () use ($node) {
            $uri = $node->getPrincipalUrl();
            $email = $node->getProperties(['{http://sabredav.org/ns}email-address']);
            $primaryEmail = $email['{http://sabredav.org/ns}email-address'] ?? '';

            $addresses = [];
            if ($primaryEmail) {
                $addresses[] = 'mailto:' . $primaryEmail;
            }

            foreach ($this->getMailboxEmails($uri) as $mbEmail) {
                $addr = 'mailto:' . $mbEmail;
                if (!in_array($addr, $addresses, true)) {
                    $addresses[] = $addr;
                }
            }

            return new Href($addresses, false);
        });
    }

    /**
     * Get mailbox emails this principal has read-write access to.
     *
     * Queries calendarinstances for MAILBOX-owned calendars where the
     * given principal has at least read-write (access >= 3) access.
     *
     * @param string $principalUri
     * @return string[] Array of mailbox email addresses
     */
    private function getMailboxEmails($principalUri)
    {
        if (array_key_exists($principalUri, $this->addressCache)) {
            return $this->addressCache[$principalUri];
        }

        try {
            $stmt = $this->pdo->prepare(
                'SELECT DISTINCT p.email FROM calendarinstances owner_ci '
                . 'JOIN principals p ON p.uri = owner_ci.principaluri '
                . 'JOIN calendarinstances sharee_ci '
                . '  ON sharee_ci.calendarid = owner_ci.calendarid '
                . 'WHERE sharee_ci.principaluri = ? '
                . '  AND sharee_ci.access >= ' . PrincipalBackend::ACCESS_READ_WRITE . ' '
                . '  AND owner_ci.access = ' . PrincipalBackend::ACCESS_OWNER . ' '
                . '  AND p.calendar_user_type = \'' . PrincipalBackend::TYPE_MAILBOX . '\''
            );
            $stmt->execute([$principalUri]);
            $result = $stmt->fetchAll(\PDO::FETCH_COLUMN, 0);
        } catch (\Exception $e) {
            error_log("[MailboxPlugin] Failed to query mailbox emails: " . $e->getMessage());
            $result = [];
        }

        $this->addressCache[$principalUri] = $result;
        return $result;
    }

    // ========================================================================
    // Share restriction — cap to read-only on MAILBOX calendars
    // ========================================================================

    /**
     * Intercept CS:share POST requests on MAILBOX calendars and reject:
     *
     *  1. Any attempt to grant ``read-write`` (or its ``admin`` flavor)
     *     via manual sharing — write access must come via the internal
     *     sync-mailbox-acls API only.
     *
     *  2. Any attempt to set/update/remove a sharee whose row is
     *     ``is_sync_managed = TRUE``. Sync-managed sharees represent
     *     the source of truth from Messages — only another sync may
     *     change them. Without this guard a user could downgrade a
     *     Messages-managed ``read`` share to ``freebusy`` (or any other
     *     level) by simply re-sharing with the same email, because
     *     SabreDAV's ``CS:share`` handler ``ON CONFLICT``-updates the
     *     existing row.
     *
     * Body parsing goes through ``$server->xml->parse()`` so we use the
     * exact same deserializer ``Sabre\CalDAV\SharingPlugin`` runs a
     * moment later — no hand-rolled regex, no namespace assumptions,
     * and ``Sharee::access`` already distinguishes set/remove via
     * ``ACCESS_READ``/``ACCESS_READWRITE``/``ACCESS_NOACCESS``.
     *
     * @return bool|null
     *
     * @noinspection PhpUnusedParameterInspection
     */
    public function restrictSharing(RequestInterface $request, ResponseInterface $response)
    {
        $contentType = $request->getHeader('Content-Type');
        if (!$contentType || (
            false === strpos($contentType, 'application/xml') &&
            false === strpos($contentType, 'text/xml')
        )) {
            return;
        }

        $body = $request->getBodyAsString();
        // Re-populate so the next handler (SharingPlugin) can read it.
        $request->setBody($body);
        if ($body === '') {
            return;
        }

        // Use SabreDAV's own XML deserializer. ``parse()`` returns a
        // typed message and fills ``$documentType`` with the root
        // element's qualified name. Anything other than CalendarServer
        // ``share`` (e.g. ``invite-reply``) is left for the next plugin.
        try {
            $message = $this->server->xml->parse(
                $body,
                $request->getUrl(),
                $documentType
            );
        } catch (\Exception $e) {
            // Malformed XML — let the downstream plugin produce its
            // canonical error rather than masking it here.
            return;
        }

        if ($documentType !== '{' . CalDAVPlugin::NS_CALENDARSERVER . '}share'
            || !$message instanceof ShareRequest
        ) {
            return;
        }

        $path = $request->getPath();
        if (!preg_match('#^calendars/users/([^/]+)/([^/]+)#', $path, $matches)) {
            return;
        }
        $principalUri = 'principals/users/' . urldecode($matches[1]);
        $calendarUri = urldecode($matches[2]);

        // Resolve the calendarid via the request's (principaluri, uri)
        // pair so the rest of the checks operate on the underlying
        // shared calendar, not the per-user sharee instance URI.
        $calendarId = $this->resolveCalendarId($principalUri, $calendarUri);
        if ($calendarId === null || !$this->isMailboxOwnedCalendarId($calendarId)) {
            return;
        }

        foreach ($message->sharees as $sharee) {
            // Rule 1 — manual sharing on mailbox calendars cannot grant
            // write access. ``admin`` rides on top of ``<CS:read-write/>``
            // so the deserializer reports ``ACCESS_READWRITE`` for both.
            if ($sharee->access === SharingPlugin::ACCESS_READWRITE) {
                throw new \Sabre\DAV\Exception\Forbidden(
                    'Mailbox calendars can only be shared with read-only '
                    . 'access. To grant write access, update the mailbox '
                    . 'permissions in Messages.'
                );
            }

            // Rule 2 — sync-managed sharees are off-limits to manual
            // ops. Applies to set AND remove (a CS:remove deserializes
            // with ACCESS_NOACCESS, which falls past Rule 1 above).
            if ($this->isSyncManagedSharee($calendarId, (string) $sharee->href)) {
                throw new \Sabre\DAV\Exception\Forbidden(
                    'This sharee is managed by Messages and can only be '
                    . 'changed there. Update the mailbox permissions in '
                    . 'Messages instead.'
                );
            }
        }
    }

    /**
     * Look up whether ``$shareeHref`` (a ``mailto:...`` or principal
     * URL) currently has a sync-managed instance row for the given
     * ``$calendarId``. Sync-managed rows are owned by Messages and
     * must not be touched by user-initiated CalDAV operations.
     */
    private function isSyncManagedSharee(int $calendarId, string $shareeHref): bool
    {
        // Resolve the sharee's principal URI from the href. Manual
        // CS:share normally uses ``mailto:`` form, but a principal
        // URL is also valid per RFC 6638.
        $principalUri = null;
        if (stripos($shareeHref, 'mailto:') === 0) {
            $email = substr($shareeHref, 7);
            $principalUri = 'principals/users/' . $email;
        } elseif (stripos($shareeHref, 'principals/users/') !== false) {
            $principalUri = preg_replace('#^.*?(principals/users/[^/]+).*$#', '$1', $shareeHref);
        }
        if (!$principalUri) {
            return false;
        }

        try {
            $stmt = $this->pdo->prepare(
                'SELECT 1 FROM calendarinstances '
                . 'WHERE calendarid = ? AND principaluri = ? '
                . '  AND is_sync_managed = TRUE '
                . 'LIMIT 1'
            );
            $stmt->execute([$calendarId, $principalUri]);
            return (bool) $stmt->fetchColumn();
        } catch (\Exception $e) {
            error_log("[MailboxPlugin] DB error in isSyncManagedSharee: " . $e->getMessage());
            // Fail closed: when in doubt, refuse to overwrite a
            // potentially sync-managed row.
            return true;
        }
    }

    /**
     * Resolve the underlying calendarid for a (principaluri, uri)
     * pair. ``uri`` may be the owner-side URI or a per-user sharee
     * instance URI — both row types live in ``calendarinstances`` and
     * point to the same ``calendarid``.
     *
     * Returns ``null`` when the row genuinely does not exist.
     * **Throws** on DB errors so the caller fails closed: silently
     * returning ``null`` would let ``restrictSharing()`` skip its
     * mailbox-only checks and SabreDAV would then process an unfiltered
     * ``CS:share`` (including read-write/admin grants).
     *
     * @throws \RuntimeException on DB error
     */
    private function resolveCalendarId(string $principalUri, string $calendarUri): ?int
    {
        try {
            $stmt = $this->pdo->prepare(
                'SELECT calendarid FROM calendarinstances '
                . 'WHERE principaluri = ? AND uri = ? LIMIT 1'
            );
            $stmt->execute([$principalUri, $calendarUri]);
            $value = $stmt->fetchColumn();
            return $value === false ? null : (int) $value;
        } catch (\Exception $e) {
            error_log("[MailboxPlugin] DB error in resolveCalendarId: " . $e->getMessage());
            throw new \RuntimeException(
                'Failed to resolve calendar id for sharing restriction',
                0,
                $e
            );
        }
    }

    /**
     * Whether the calendar with the given id is owned by a MAILBOX
     * principal.
     *
     * **Throws** on DB errors so ``restrictSharing()`` fails closed:
     * silently returning ``false`` would skip the mailbox-only checks
     * and let an unfiltered ``CS:share`` reach SabreDAV's handler.
     *
     * @throws \RuntimeException on DB error
     */
    private function isMailboxOwnedCalendarId(int $calendarId): bool
    {
        try {
            $stmt = $this->pdo->prepare(
                'SELECT p.calendar_user_type '
                . 'FROM calendarinstances owner_ci '
                . 'JOIN principals p ON p.uri = owner_ci.principaluri '
                . 'WHERE owner_ci.calendarid = ? AND owner_ci.access = 1 '
                . 'LIMIT 1'
            );
            $stmt->execute([$calendarId]);
            return $stmt->fetchColumn() === PrincipalBackend::TYPE_MAILBOX;
        } catch (\Exception $e) {
            error_log("[MailboxPlugin] DB error in isMailboxOwnedCalendarId: " . $e->getMessage());
            throw new \RuntimeException(
                'Failed to verify mailbox ownership for sharing restriction',
                0,
                $e
            );
        }
    }
}
