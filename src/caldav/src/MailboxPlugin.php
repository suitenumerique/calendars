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

use Sabre\DAV\Server;
use Sabre\DAV\ServerPlugin;
use Sabre\DAV\PropFind;
use Sabre\DAV\INode;
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
     * Intercept CS:share POST requests and reject read-write shares
     * on MAILBOX calendars. Write access must come via the internal
     * sync-mailbox-acls API.
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
        $request->setBody($body);

        // Quick checks: only CS:share with read-write
        if (false === strpos($body, 'share') || false === strpos($body, 'read-write')) {
            return;
        }

        $path = $request->getPath();

        if (!preg_match('#^calendars/users/([^/]+)/([^/]+)#', $path, $matches)) {
            return;
        }

        $principalUri = 'principals/users/' . urldecode($matches[1]);
        $calendarUri = urldecode($matches[2]);

        // Look up the actual owner's principal type via the calendar's
        // underlying calendarid. This handles both direct ownership and
        // shared instances (any URI format — sync-managed or UUID).
        if (!$this->isMailboxOwnedCalendar($principalUri, $calendarUri)) {
            return;
        }

        throw new \Sabre\DAV\Exception\Forbidden(
            'Mailbox calendars can only be shared with read-only access. '
            . 'To grant write access, update the mailbox permissions in Messages.'
        );
    }

    /**
     * Check if a calendar instance belongs to a MAILBOX-owned calendar.
     *
     * Resolves the owner via the calendarid → owner instance → principal
     * chain. Works for both directly-owned calendars and shared instances
     * (any URI format).
     */
    private function isMailboxOwnedCalendar(string $principalUri, string $calendarUri): bool
    {
        try {
            $stmt = $this->pdo->prepare(
                'SELECT p.calendar_user_type '
                . 'FROM calendarinstances ci '
                . 'JOIN calendarinstances owner_ci ON owner_ci.calendarid = ci.calendarid AND owner_ci.access = 1 '
                . 'JOIN principals p ON p.uri = owner_ci.principaluri '
                . 'WHERE ci.principaluri = ? AND ci.uri = ? '
                . 'LIMIT 1'
            );
            $stmt->execute([$principalUri, $calendarUri]);
            return $stmt->fetchColumn() === PrincipalBackend::TYPE_MAILBOX;
        } catch (\Exception $e) {
            error_log("[MailboxPlugin] DB error in isMailboxOwnedCalendar: " . $e->getMessage());
            return false;
        }
    }

}
