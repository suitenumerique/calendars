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

// Composer autoloader
require_once __DIR__ . '/vendor/autoload.php';

// Get base URI from environment variable (set by compose.yaml)
// This ensures sabre/dav generates URLs with the correct proxy path
$baseUri = getenv('CALENDARS_BASE_URI') ?: '/';

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

// Add custom IMipPlugin that forwards scheduling messages via HTTP callback
// This MUST be added BEFORE the Schedule\Plugin so that Schedule\Plugin finds it
// The callback URL must be provided per-request via X-CalDAV-Callback-URL header
$callbackApiKey = getenv('CALDAV_INBOUND_API_KEY');
if (!$callbackApiKey) {
    error_log("[sabre/dav] CALDAV_INBOUND_API_KEY environment variable is required for scheduling callback");
    exit(1);
}
$imipPlugin = new HttpCallbackIMipPlugin($callbackApiKey);
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
