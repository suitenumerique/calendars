<?php
/**
 * ShareAccessPlugin - Custom per-share access level extension for CalDAV.
 *
 * Extends CalDAV sharing with a per-share access level property in the
 * La Suite namespace ({http://lasuite.numerique.gouv.fr/ns/}). This enables
 * freebusy-only shares: the share uses standard CS:read access, but a
 * custom LS:share-access element signals that the server should strip
 * event details (enforced by SharedCalendarPrivacyPlugin).
 *
 * Protocol extension:
 *
 *   CS:share POST request (setting a freebusy share):
 *     <CS:set>
 *       <D:href>mailto:user@example.com</D:href>
 *       <LS:share-access xmlns:LS="http://lasuite.numerique.gouv.fr/ns/">
 *         freebusy
 *       </LS:share-access>
 *       <CS:read/>
 *     </CS:set>
 *
 *   PROPFIND response on the shared calendar instance:
 *     <LS:share-access>freebusy</LS:share-access>
 *
 * Storage: calendarinstances.share_access_level column.
 *
 * This deliberately avoids CS:summary (a human-readable field in the
 * CalendarServer spec) to keep the standard protocol clean and prevent
 * internal markers from leaking to third-party CalDAV clients.
 */

namespace Calendars\SabreDav;

use Sabre\CalDAV\ICalendar;
use Sabre\DAV\INode;
use Sabre\DAV\PropFind;
use Sabre\DAV\Server;
use Sabre\DAV\ServerPlugin;
use Sabre\Xml\Element\XmlFragment;

class ShareAccessPlugin extends ServerPlugin
{
    /** La Suite namespace */
    const LS_NS = 'http://lasuite.numerique.gouv.fr/ns/';

    /** Custom DAV property on the sharee's calendar instance: their access level */
    const SHARE_ACCESS_PROP = '{http://lasuite.numerique.gouv.fr/ns/}share-access';

    /**
     * Allowlist of valid share_access_level values.
     *
     * Anything outside this set is coerced to ``null`` before being
     * persisted. The column is consumed by ``SharedCalendarPrivacyPlugin``
     * (which checks ``=== 'freebusy'`` to enable the freebusy filter)
     * and by the frontend ``parseSharePrivilege`` helper (which maps
     * both ``'freebusy'`` and ``'admin'`` to UI badges riding on top of
     * the standard CalDAV access levels). Storing arbitrary attacker-
     * supplied strings would let a future reader misinterpret them —
     * harden at write time so the column can never carry surprises.
     */
    const ALLOWED_LEVELS = ['freebusy', 'admin'];

    /** Custom DAV property: the owner principal's type (e.g., "MAILBOX").
     *  Injected into calendarInfo by CustomCalendarHome, read here via propFind.
     *  Zero extra DB queries — the value is cached in calendarInfo at load time. */
    const OWNER_TYPE_PROP = '{http://lasuite.numerique.gouv.fr/ns/}calendar-owner-type';

    /**
     * Custom DAV property on the owner's calendar: map of sharee hrefs to
     * access levels. Allows the owner's sharing UI to distinguish freebusy
     * from read without querying each sharee's instance.
     *
     * Serialized as XML:
     *   <LS:share-access-map>
     *     <LS:sharee href="mailto:user@example.com" access="freebusy"/>
     *   </LS:share-access-map>
     */
    const SHARE_ACCESS_MAP_PROP = '{http://lasuite.numerique.gouv.fr/ns/}share-access-map';

    /** @var \PDO */
    private $pdo;

    /** @var Server */
    protected $server;

    /** @var string|null Cached POST body for afterPost */
    private $postBody = null;

    public function __construct(\PDO $pdo)
    {
        $this->pdo = $pdo;
    }

    public function getPluginName()
    {
        return 'share-access';
    }

    public function initialize(Server $server)
    {
        $this->server = $server;
        $server->on('beforeMethod:POST', [$this, 'cachePostBody'], 50);
        $server->on('afterMethod:POST', [$this, 'afterPost'], 200);
        $server->on('propFind', [$this, 'propFindShareAccess'], 200);
        $server->on('propFind', [$this, 'propFindShareAccessMap'], 200);
        $server->on('propFind', [$this, 'propFindOwnerType'], 200);
    }

    public function cachePostBody($request, $response)
    {
        $this->postBody = $request->getBodyAsString();
        $request->setBody($this->postBody);
    }

    /**
     * After a CS:share POST, reconcile LS:share-access for every sharee
     * mentioned in the request body.
     *
     * Critically this runs even when the body has NO ``LS:share-access``
     * elements: a sharee may be transitioning from ``freebusy`` (or any
     * other custom level) back to a regular CS:read share, in which
     * case we must clear the previously-stored level — otherwise the
     * stale row pins the sharee at ``freebusy`` forever and the
     * frontend reads it back at the wrong level.
     *
     * Uses SabreDAV's XML parser (same as CalDAV\SharingPlugin) to parse
     * the CS:share body. The LS:share-access element is captured as part
     * of the KeyValue parsing of each CS:set block.
     */
    public function afterPost($request, $response)
    {
        $body = $this->postBody ?? '';
        // Cheap pre-filter: only CS:share bodies are interesting. Other
        // POSTs (ICS imports, MKCALENDAR followups, …) reach this hook
        // too and we don't want to parse them.
        if (!$body || strpos($body, ':share') === false) {
            return;
        }

        $path = $request->getPath();
        $parts = explode('/', trim($path, '/'));
        if (count($parts) < 4) return;

        $ownerEmail = urldecode($parts[2]);
        $calendarUri = $parts[3];
        $ownerPrincipal = 'principals/users/' . $ownerEmail;

        // Authorization guard: only the calendar OWNER may reconcile share
        // levels. SabreDAV's sharing plugin already restricts CS:share to the
        // owner, but this hook performs its own DB write off the request body
        // and runs on afterMethod:POST regardless — so it must not depend on
        // upstream ordering. A sharee (or anyone whose authenticated principal
        // is not the path owner) must never be able to rewrite share_access_level.
        $aclPlugin = $this->server->getPlugin('acl');
        $currentPrincipal = $aclPlugin ? $aclPlugin->getCurrentUserPrincipal() : null;
        if (!is_string($currentPrincipal)
            || strtolower(rtrim($currentPrincipal, '/'))
                !== strtolower(rtrim($ownerPrincipal, '/'))) {
            error_log(
                "[ShareAccessPlugin] Refusing share_access_level write: "
                . "principal " . var_export($currentPrincipal, true)
                . " is not the calendar owner " . $ownerPrincipal
            );
            return;
        }

        try {
            // Parse with a fresh XML service (not the server's, which has
            // element maps that transform CS:share into a Share object).
            // Using KeyValue for CS:set gives us all child elements by
            // Clark notation, including our custom LS:share-access.
            $xml = new \Sabre\Xml\Service();
            $cs = '{http://calendarserver.org/ns/}';
            $xml->elementMap[$cs . 'share'] = function (\Sabre\Xml\Reader $reader) use ($cs) {
                return $reader->parseGetElements([
                    $cs . 'set' => \Sabre\Xml\Element\KeyValue::class,
                ]);
            };
            $result = $xml->parse($body);

            if (!is_array($result)) return;

            // Resolve calendarid once for the path. The same statement
            // is reused inside the loop with the right param shape.
            $update = $this->pdo->prepare(
                'UPDATE calendarinstances SET share_access_level = ? '
                . 'WHERE share_href = ? AND calendarid = ('
                . '  SELECT calendarid FROM calendarinstances '
                . '  WHERE principaluri = ? AND uri = ?'
                . ')'
            );

            foreach ($result as $elem) {
                if ($elem['name'] !== $cs . 'set' || !is_array($elem['value'])) {
                    continue;
                }

                $setValues = $elem['value'];
                $href = $setValues['{DAV:}href'] ?? null;
                if (!$href) {
                    continue;
                }
                $rawLevel = $setValues[self::SHARE_ACCESS_PROP] ?? null;
                $level = ($rawLevel !== null) ? trim($rawLevel) : null;
                if ($level === '') {
                    $level = null;
                }
                // Coerce anything outside the allowlist to NULL. The
                // privacy plugin only acts on ``'freebusy'`` and the
                // frontend only badges ``'freebusy'`` / ``'admin'`` —
                // any other value is meaningless today and storing it
                // would create a future-bug primitive.
                if ($level !== null && !in_array($level, self::ALLOWED_LEVELS, true)) {
                    error_log(
                        "[ShareAccessPlugin] Coercing unknown share_access_level "
                        . "to NULL: " . $level
                    );
                    $level = null;
                }
                // Bind NULL when there's no override → resets the
                // column for sharees being moved off freebusy/admin.
                $update->execute([$level, $href, $ownerPrincipal, $calendarUri]);
            }
        } catch (\Exception $e) {
            error_log("[ShareAccessPlugin] Failed to save access level: " . $e->getMessage());
        }
    }

    /**
     * Expose the share access level as a custom DAV property.
     *
     * Property: {http://lasuite.numerique.gouv.fr/ns/}share-access
     * Value: "freebusy" (or null if not set)
     */
    public function propFindShareAccess(PropFind $propFind, INode $node)
    {
        if (!$node instanceof ICalendar) {
            return;
        }

        $propFind->handle(self::SHARE_ACCESS_PROP, function () use ($node) {
            try {
                $reflection = new \ReflectionObject($node);
                if (!$reflection->hasProperty('calendarInfo')) {
                    return null;
                }
                $prop = $reflection->getProperty('calendarInfo');
                $info = $prop->getValue($node);

                // calendarInfo['id'] is [calendarId, instanceId] in SabreDAV
                $instanceId = is_array($info['id']) ? ($info['id'][1] ?? null) : null;
                if (!$instanceId) {
                    return null;
                }

                $stmt = $this->pdo->prepare(
                    'SELECT share_access_level FROM calendarinstances WHERE id = ?'
                );
                $stmt->execute([$instanceId]);
                $level = $stmt->fetchColumn();

                return $level ?: null;
            } catch (\Exception $e) {
                error_log("[ShareAccessPlugin] propFind error: " . $e->getMessage());
            }
            return null;
        });
    }

    /**
     * On the owner's calendar, expose a map of sharee → access level.
     * Only includes sharees that have a non-null share_access_level.
     *
     * Returns a simple XML string that tsdav can parse.
     */
    public function propFindShareAccessMap(PropFind $propFind, INode $node)
    {
        if (!$node instanceof ICalendar) {
            return;
        }

        $propFind->handle(self::SHARE_ACCESS_MAP_PROP, function () use ($node) {
            try {
                $reflection = new \ReflectionObject($node);
                if (!$reflection->hasProperty('calendarInfo')) {
                    return null;
                }
                $prop = $reflection->getProperty('calendarInfo');
                $info = $prop->getValue($node);

                $calendarId = is_array($info['id']) ? $info['id'][0] : ($info['id'] ?? null);
                if (!$calendarId) {
                    return null;
                }

                $stmt = $this->pdo->prepare(
                    'SELECT share_href, share_access_level FROM calendarinstances '
                    . 'WHERE calendarid = ? AND share_access_level IS NOT NULL'
                );
                $stmt->execute([$calendarId]);
                $rows = $stmt->fetchAll(\PDO::FETCH_ASSOC);

                if (empty($rows)) {
                    return null;
                }

                // Build the inner XML as proper child elements via
                // XmlFragment. Returning a plain string would let
                // SabreDAV serialize it as escaped text content (e.g.
                // "&lt;LS:sharee.../&gt;"), which the frontend cannot
                // parse as a structured object. XmlFragment re-parses
                // the inner XML and writes real child elements with the
                // right namespace declarations.
                $xml = '';
                foreach ($rows as $row) {
                    $href = htmlspecialchars($row['share_href'], ENT_XML1);
                    $level = htmlspecialchars($row['share_access_level'], ENT_XML1);
                    $xml .= '<LS:sharee xmlns:LS="' . self::LS_NS . '"'
                        . ' href="' . $href . '"'
                        . ' access="' . $level . '"/>';
                }
                return new XmlFragment($xml);
            } catch (\Exception $e) {
                error_log("[ShareAccessPlugin] propFindMap error: " . $e->getMessage());
            }
            return null;
        });
    }

    /**
     * Expose the calendar owner's principal type (e.g., "MAILBOX").
     *
     * The value is injected into calendarInfo by CustomCalendarHome during
     * calendar loading — zero extra DB queries here.
     */
    public function propFindOwnerType(PropFind $propFind, INode $node)
    {
        if (!$node instanceof ICalendar) {
            return;
        }

        $propFind->handle(self::OWNER_TYPE_PROP, function () use ($node) {
            try {
                $reflection = new \ReflectionObject($node);
                if (!$reflection->hasProperty('calendarInfo')) {
                    return null;
                }
                $prop = $reflection->getProperty('calendarInfo');
                $info = $prop->getValue($node);
                return $info[self::OWNER_TYPE_PROP] ?? null;
            } catch (\Exception $e) {
                return null;
            }
        });
    }
}
