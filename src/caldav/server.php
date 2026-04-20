<?php
/**
 * sabre/dav CalDAV Server
 * Configured to use PostgreSQL backend and custom header-based authentication
 */

use Sabre\DAV\Auth;
use Sabre\DAVACL;
use Sabre\CalDAV;
use Sabre\CardDAV;
use Sabre\DAV;
use Calendars\SabreDav\PrincipalBackend;
use Calendars\SabreDav\HttpCallbackIMipPlugin;
use Calendars\SabreDav\ApiKeyAuthBackend;
use Calendars\SabreDav\CalendarSanitizerPlugin;
use Calendars\SabreDav\AttendeeNormalizerPlugin;
use Calendars\SabreDav\InternalApiPlugin;
use Calendars\SabreDav\ResourceAutoSchedulePlugin;
use Calendars\SabreDav\FreeBusyOrgScopePlugin;
use Calendars\SabreDav\SharedCalendarPrivacyPlugin;
use Calendars\SabreDav\MailboxPlugin;
use Calendars\SabreDav\ShareAccessPlugin;
use Calendars\SabreDav\AvailabilityPlugin;
use Calendars\SabreDav\AuditCalDAVBackend;
use Calendars\SabreDav\AuditContextPlugin;
use Calendars\SabreDav\CalendarsRoot;
use Calendars\SabreDav\CustomCalDAVPlugin;
use Calendars\SabreDav\PrincipalsRoot;

// Allow large ICS imports (default 128M is too low for big calendars)
ini_set('memory_limit', getenv('PHP_MEMORY_LIMIT') ?: '512M');

// Composer autoloader
require_once __DIR__ . '/vendor/autoload.php';

// Get base URI from environment variable (set by compose.yaml)
// This ensures sabre/dav generates URLs with the correct proxy path
$baseUri = getenv('CALDAV_BASE_URI') ?: '/';

// Database connection from environment variables
$dbHost = getenv('PGHOST') ?: 'postgresql';
$dbPort = getenv('PGPORT') ?: '5432';
$dbName = getenv('PGDATABASE') ?: 'calendars';
$dbUser = getenv('PGUSER') ?: 'pgroot';
$dbPass = getenv('PGPASSWORD') ?: 'pass';

// Create PDO connection
$pdo = new PDO(
    "pgsql:host={$dbHost};port={$dbPort};dbname={$dbName}",
    $dbUser,
    $dbPass,
    [
        PDO::ATTR_ERRMODE => PDO::ERRMODE_EXCEPTION,
        PDO::ATTR_DEFAULT_FETCH_MODE => PDO::FETCH_ASSOC,
    ]
);

// Route all unqualified table references to the configured schema.
// Defaults to "public" so existing deployments are unaffected.
$dbSchema = getenv('CALDAV_DB_SCHEMA') ?: 'public';
if (!preg_match('/^[A-Za-z_][A-Za-z0-9_]*$/', $dbSchema)) {
    error_log("[sabre/dav] CALDAV_DB_SCHEMA must be a valid identifier, got: {$dbSchema}");
    exit(1);
}
$pdo->exec("SET search_path TO \"{$dbSchema}\", public");

// Create custom authentication backend
// Requires API key authentication and X-LS-User header
$apiKey = getenv('CALDAV_OUTBOUND_API_KEY');
if (!$apiKey) {
    error_log("[sabre/dav] CALDAV_OUTBOUND_API_KEY environment variable is required");
    exit(1);
}
$authBackend = new ApiKeyAuthBackend($apiKey);

// Create authentication plugin
$authPlugin = new Auth\Plugin($authBackend);

// Create CalDAV backend with audit tracking (channel_id, created_by, modified_by)
$caldavBackend = new AuditCalDAVBackend($pdo);

// Create CardDAV backend (optional, for future use)
$carddavBackend = new CardDAV\Backend\PDO($pdo);

// Create principal backend with org-scoped discovery and mailbox address loading
$principalBackend = new PrincipalBackend($pdo);

// Create directory tree
// Principal collections: principals/users/ and principals/resources/
// Calendar collections: calendars/users/ and calendars/resources/
$nodes = [
    new PrincipalsRoot($principalBackend),
    new CalendarsRoot($principalBackend, $caldavBackend, $pdo),
    new CardDAV\AddressBookRoot($principalBackend, $carddavBackend),
];

// Suppress every place SabreDAV self-identifies its version: the
// ``<s:sabredav-version>`` element in error bodies, the
// ``X-Sabre-Version`` response header, the version footers in
// Browser/Plugin and ICSExportPlugin, and the equivalent in IMip
// outbound mail. Useless to legitimate clients and a free
// fingerprinting hint for attackers.
DAV\Server::$exposeVersion = false;

// Create server
$server = new DAV\Server($nodes);
$server->setBaseUri($baseUri);

// Give the principal backend a reference to the server
// so it can read X-LS-Org-Id from the HTTP request
$principalBackend->setServer($server);

// Add plugins
$server->addPlugin($authPlugin);
$server->addPlugin(new CustomCalDAVPlugin());
$server->addPlugin(new CardDAV\Plugin());
// PrincipalsRoot is a plain DAV\Collection (not IPrincipalCollection), so the
// default principalCollectionSet ['principals'] would skip it during principal
// search. Point directly to the child IPrincipalCollection nodes instead.
$aclPlugin = new DAVACL\Plugin();
$aclPlugin->principalCollectionSet = ['principals/users', 'principals/resources', 'principals/mailboxes'];
$server->addPlugin($aclPlugin);
// Browser plugin disabled — it's a debug tool that exposes properties in HTML.
// $server->addPlugin(new DAV\Browser\Plugin());

// Add ICS export plugin for iCal subscription URLs
// Allows exporting calendars as .ics files via ?export query parameter
// See https://sabre.io/dav/ics-export-plugin/
$server->addPlugin(new CalDAV\ICSExportPlugin());

// Add sharing support
// See https://sabre.io/dav/caldav-sharing/
// Note: Order matters! CalDAV\SharingPlugin must come after DAV\Sharing\Plugin
$server->addPlugin(new DAV\Sharing\Plugin());
$server->addPlugin(new CalDAV\SharingPlugin());
$server->addPlugin(new MailboxPlugin($pdo));
$server->addPlugin(new ShareAccessPlugin($pdo));

// Debug logging for POST requests - commented out to avoid PII in logs
// Uncomment for local debugging only, never in production.
// $server->on('method:POST', function($request) {
//     $contentType = $request->getHeader('Content-Type');
//     $path = $request->getPath();
//     $body = $request->getBodyAsString();
//     error_log("[sabre/dav] POST request received:");
//     error_log("[sabre/dav] Path: " . $path);
//     error_log("[sabre/dav] Content-Type: " . $contentType);
//     error_log("[sabre/dav] Body: " . substr($body, 0, 1000));
//     $request->setBody($body);
// }, 50);
//
// $server->on('afterMethod:POST', function($request, $response) {
//     error_log("[sabre/dav] POST response status: " . $response->getStatus());
//     $body = $response->getBodyAsString();
//     if ($body) {
//         error_log("[sabre/dav] POST response body: " . substr($body, 0, 500));
//     }
// }, 50);

// Log unhandled exceptions, and mask any raw internal-error message so
// the client never sees database internals (SQL state, table names,
// PDO parameter values…). SabreDAV's error renderer uses
// $e->getMessage() directly when building the multistatus body and
// has no extension point to override the message, so we mutate the
// protected `Exception::$message` field via reflection. SabreDAV's
// own DAV exceptions are passed through unchanged — they're safe by
// design (NotFound, Forbidden, BadRequest, ServerError, etc.).
//
// FAIL-CLOSED: if reflection fails for any reason we MUST NOT let
// SabreDAV render the original message. We write a generic 500
// response directly and exit, bypassing the entire renderer.
$server->on('exception', function ($e) {
    error_log("[sabre/dav] Exception: " . get_class($e) . " - " . $e->getMessage());
    error_log("[sabre/dav] Exception trace: " . $e->getTraceAsString());

    if ($e instanceof \Sabre\DAV\Exception) {
        return;
    }
    try {
        $reflClass = new \ReflectionClass(\Exception::class);
        $reflMessage = $reflClass->getProperty('message');
        $reflMessage->setAccessible(true);
        $reflMessage->setValue($e, 'Internal server error');
        return;
    } catch (\Throwable $reflFailure) {
        error_log(
            "[sabre/dav] Reflection-based message masking failed: "
            . $reflFailure->getMessage()
            . " — emitting hardcoded 500 to avoid leaking original error"
        );
    }

    // Reflection failed. Bypass SabreDAV's renderer entirely so the
    // raw exception message can never reach the client.
    if (!headers_sent()) {
        http_response_code(500);
        header('Content-Type: application/xml; charset=utf-8');
    }
    echo '<?xml version="1.0" encoding="utf-8"?>'
        . '<d:error xmlns:d="DAV:" xmlns:s="http://sabredav.org/ns">'
        . '<s:exception>InternalServerError</s:exception>'
        . '<s:message>Internal server error</s:message>'
        . '</d:error>';
    exit;
}, 50);

// Add audit context plugin (priority 70, runs before sanitizer/normalizer)
// Sets principal email and channel ID on the backend before each write
$server->addPlugin(new AuditContextPlugin($caldavBackend));

// Add calendar sanitizer plugin (priority 85, runs before all other calendar plugins)
// Strips inline binary attachments (Outlook/Exchange base64 images) and truncates
// oversized DESCRIPTION fields. Applies to ALL CalDAV writes (PUT from any client).
$sanitizerStripAttachments = getenv('SANITIZER_STRIP_BINARY_ATTACHMENTS') !== 'false';
$sanitizerMaxDescBytes = getenv('SANITIZER_MAX_DESCRIPTION_BYTES');
$sanitizerMaxDescBytes = ($sanitizerMaxDescBytes !== false) ? (int)$sanitizerMaxDescBytes : 102400;
$sanitizerMaxResourceSize = getenv('SANITIZER_MAX_RESOURCE_SIZE');
$sanitizerMaxResourceSize = ($sanitizerMaxResourceSize !== false) ? (int)$sanitizerMaxResourceSize : 1048576;
$server->addPlugin(new CalendarSanitizerPlugin(
    $sanitizerStripAttachments,
    $sanitizerMaxDescBytes,
    $sanitizerMaxResourceSize
));

// Add attendee normalizer plugin to fix duplicate attendees issue
// This plugin normalizes attendee emails (lowercase) and deduplicates them
// when processing calendar objects, fixing issues with REPLY handling
$server->addPlugin(new AttendeeNormalizerPlugin());

// Add internal API plugin for resource provisioning and ICS import
// Gated by X-LS-Internal-Api-Key header (separate from X-LS-Api-Key used by proxy).
// MUST be set explicitly.
$internalApiKey = getenv('CALDAV_INTERNAL_API_KEY');
if (!$internalApiKey) {
    error_log("[sabre/dav] CALDAV_INTERNAL_API_KEY environment variable is required");
    exit(1);
}
$server->addPlugin(new InternalApiPlugin($pdo, $caldavBackend, $internalApiKey));

// Add custom IMipPlugin that forwards scheduling messages via HTTP callback
// This MUST be added BEFORE the Schedule\Plugin so that Schedule\Plugin finds it
// The callback URL is built from CALDAV_CALLBACK_BASE_URL + fixed path
$callbackApiKey = getenv('CALDAV_INBOUND_API_KEY');
if (!$callbackApiKey) {
    error_log("[sabre/dav] CALDAV_INBOUND_API_KEY environment variable is required for scheduling callback");
    exit(1);
}
$callbackBaseUrl = getenv('CALDAV_CALLBACK_BASE_URL');
if (!$callbackBaseUrl) {
    error_log("[sabre/dav] CALDAV_CALLBACK_BASE_URL environment variable is required for scheduling callback");
    exit(1);
}
$callbackUrl = rtrim($callbackBaseUrl, '/') . '/api/v1.0/caldav-scheduling-callback/';
$imipPlugin = new HttpCallbackIMipPlugin($callbackApiKey, $pdo, $callbackUrl);
$server->addPlugin($imipPlugin);

// Enforce org-level freebusy sharing settings
// Blocks VFREEBUSY queries when X-LS-Org-Sharing-Level is "none"
$server->addPlugin(new FreeBusyOrgScopePlugin($pdo));

// Add CalDAV scheduling support
// See https://sabre.io/dav/scheduling/
// NOTE: MailboxPlugin (registered above) runs propFind at priority 80 to inject
// mailbox emails into calendar-user-address-set before Schedule\Plugin (100).
$schedulePlugin = new CalDAV\Schedule\Plugin();
$server->addPlugin($schedulePlugin);

// Resource principal management: auto-scheduling + MKCALENDAR blocking
$server->addPlugin(new ResourceAutoSchedulePlugin($pdo, $caldavBackend));

// Add availability integration for freebusy responses
// Reads calendar-availability property and adds BUSY-UNAVAILABLE periods
$server->addPlugin(new AvailabilityPlugin($pdo));

// Add WebDAV sync support (RFC 6578) for incremental calendar sync
// Enables sync-collection REPORT used by all CalDAV clients
$server->addPlugin(new DAV\Sync\Plugin());

// Add property storage plugin for custom properties (resource metadata, etc.)
$server->addPlugin(new DAV\PropertyStorage\Plugin(
    new DAV\PropertyStorage\Backend\PDO($pdo)
));

// Shared calendar privacy: CLASS enforcement, freebusy shares, VALARM stripping
$server->addPlugin(new SharedCalendarPrivacyPlugin($pdo));

// Start server
$server->start();
