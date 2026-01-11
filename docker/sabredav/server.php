<?php
/**
 * sabre/dav CalDAV Server
 * Configured to use PostgreSQL backend and Apache authentication
 */

use Sabre\DAV\Auth;
use Sabre\DAVACL;
use Sabre\CalDAV;
use Sabre\CardDAV;
use Sabre\DAV;
use Calendars\SabreDav\AutoCreatePrincipalBackend;

// Composer autoloader
require_once __DIR__ . '/vendor/autoload.php';

// Set REMOTE_USER from X-Forwarded-User header (set by Django proxy)
// This allows sabre/dav Apache auth backend to work with proxied requests
if (isset($_SERVER['HTTP_X_FORWARDED_USER']) && !isset($_SERVER['REMOTE_USER'])) {
    $_SERVER['REMOTE_USER'] = $_SERVER['HTTP_X_FORWARDED_USER'];
}

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

// Create backend
$authBackend = new Auth\Backend\Apache();

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

// Start server
$server->start();
