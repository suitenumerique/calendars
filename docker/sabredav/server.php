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
use Calendars\SabreDav\AutoCreatePrincipalBackend;
use Calendars\SabreDav\HttpCallbackIMipPlugin;
use Calendars\SabreDav\ApiKeyAuthBackend;
use Calendars\SabreDav\CalendarSanitizerPlugin;
use Calendars\SabreDav\AttendeeNormalizerPlugin;
use Calendars\SabreDav\ICSImportPlugin;

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

// Create custom authentication backend
// Requires API key authentication and X-Forwarded-User header
$apiKey = getenv('CALDAV_OUTBOUND_API_KEY');
if (!$apiKey) {
    error_log("[sabre/dav] CALDAV_OUTBOUND_API_KEY environment variable is required");
    exit(1);
}
$authBackend = new ApiKeyAuthBackend($apiKey);

// Create authentication plugin
$authPlugin = new Auth\Plugin($authBackend);

// Create CalDAV backend
$caldavBackend = new CalDAV\Backend\PDO($pdo);

// Create CardDAV backend (optional, for future use)
$carddavBackend = new CardDAV\Backend\PDO($pdo);

// Create principal backend with auto-creation support
$principalBackend = new AutoCreatePrincipalBackend($pdo);

// Create directory tree
$nodes = [
    new CalDAV\Principal\Collection($principalBackend),
    new CalDAV\CalendarRoot($principalBackend, $caldavBackend),
    new CardDAV\AddressBookRoot($principalBackend, $carddavBackend),
];

// Create server
$server = new DAV\Server($nodes);
$server->setBaseUri($baseUri);

// Add plugins
$server->addPlugin($authPlugin);
$server->addPlugin(new CalDAV\Plugin());
$server->addPlugin(new CardDAV\Plugin());
$server->addPlugin(new DAVACL\Plugin());
$server->addPlugin(new DAV\Browser\Plugin());

// Add ICS export plugin for iCal subscription URLs
// Allows exporting calendars as .ics files via ?export query parameter
// See https://sabre.io/dav/ics-export-plugin/
$server->addPlugin(new CalDAV\ICSExportPlugin());

// Add sharing support
// See https://sabre.io/dav/caldav-sharing/
// Note: Order matters! CalDAV\SharingPlugin must come after DAV\Sharing\Plugin
$server->addPlugin(new DAV\Sharing\Plugin());
$server->addPlugin(new CalDAV\SharingPlugin());

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

// Log unhandled exceptions
$server->on('exception', function($e) {
    error_log("[sabre/dav] Exception: " . get_class($e) . " - " . $e->getMessage());
    error_log("[sabre/dav] Exception trace: " . $e->getTraceAsString());
}, 50);

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

// Add ICS import plugin for bulk event import from a single POST request
// Only accessible via the X-Calendars-Import header (backend-only)
$server->addPlugin(new ICSImportPlugin($caldavBackend, $apiKey));

// Add custom IMipPlugin that forwards scheduling messages via HTTP callback
// This MUST be added BEFORE the Schedule\Plugin so that Schedule\Plugin finds it
// The callback URL can be provided per-request via X-CalDAV-Callback-URL header
// or via CALDAV_CALLBACK_URL environment variable as fallback
$callbackApiKey = getenv('CALDAV_INBOUND_API_KEY');
if (!$callbackApiKey) {
    error_log("[sabre/dav] CALDAV_INBOUND_API_KEY environment variable is required for scheduling callback");
    exit(1);
}
$defaultCallbackUrl = getenv('CALDAV_CALLBACK_URL') ?: null;
if ($defaultCallbackUrl) {
    error_log("[sabre/dav] Using default callback URL for scheduling: {$defaultCallbackUrl}");
}
$imipPlugin = new HttpCallbackIMipPlugin($callbackApiKey, $defaultCallbackUrl);
$server->addPlugin($imipPlugin);

// Add CalDAV scheduling support
// See https://sabre.io/dav/scheduling/
// The Schedule\Plugin will automatically find and use the IMipPlugin we just added
// It looks for plugins that implement CalDAV\Schedule\IMipPlugin interface
$schedulePlugin = new CalDAV\Schedule\Plugin();
$server->addPlugin($schedulePlugin);

// error_log("[sabre/dav] Starting server");

// Start server
$server->start();
