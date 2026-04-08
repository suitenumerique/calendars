<?php
/**
 * Custom IMipPlugin that forwards scheduling messages via HTTP callback instead of sending emails.
 * 
 * This plugin extends sabre/dav's IMipPlugin but instead of sending emails via PHP's mail()
 * function, it forwards the scheduling messages to an HTTP callback endpoint secured by API key.
 * 
 * @see https://sabre.io/dav/scheduling/
 */

namespace Calendars\SabreDav;

use Sabre\CalDAV\Schedule\IMipPlugin;
use Sabre\DAV\Server;
use Sabre\VObject\ITip\Message;

class HttpCallbackIMipPlugin extends IMipPlugin
{
    /**
     * API key for authenticating with the callback endpoint
     * @var string
     */
    private $apiKey;

    /**
     * Reference to the DAV server instance
     * @var Server
     */
    private $server;

    /**
     * @var \PDO
     */
    private $pdo;

    /**
     * Default callback URL (fallback if header is not provided)
     * @var string|null
     */
    private $defaultCallbackUrl;

    /**
     * Constructor
     *
     * @param string $apiKey The API key for authenticating with the callback endpoint
     * @param \PDO $pdo Database connection for principal lookups
     * @param string|null $defaultCallbackUrl Optional default callback URL
     */
    public function __construct($apiKey, \PDO $pdo, $defaultCallbackUrl = null)
    {
        // Call parent constructor with empty email (we won't use it)
        parent::__construct('');

        $this->apiKey = $apiKey;
        $this->pdo = $pdo;
        $this->defaultCallbackUrl = $defaultCallbackUrl;
    }

    /**
     * Initialize the plugin.
     * 
     * @param Server $server
     * @return void
     */
    public function initialize(Server $server)
    {
        parent::initialize($server);
        $this->server = $server;
    }

    /**
     * Event handler for the 'schedule' event.
     * 
     * This overrides the parent's schedule() method to forward messages via HTTP callback
     * instead of sending emails via PHP's mail() function.
     * 
     * @param Message $iTipMessage The iTip message
     * @return void
     */
    public function schedule(Message $iTipMessage)
    {
        // Not sending any messages if the system considers the update insignificant.
        if (!$iTipMessage->significantChange) {
            if (!$iTipMessage->scheduleStatus) {
                $iTipMessage->scheduleStatus = '1.0;We got the message, but it\'s not significant enough to warrant delivery';
            }
            return;
        }

        // Only handle mailto: recipients (external attendees)
        if ('mailto' !== parse_url($iTipMessage->sender, PHP_URL_SCHEME)) {
            return;
        }

        if ('mailto' !== parse_url($iTipMessage->recipient, PHP_URL_SCHEME)) {
            return;
        }

        // Get callback URL from the HTTP request header or use default
        $callbackUrl = null;
        if ($this->server && $this->server->httpRequest) {
            $callbackUrl = $this->server->httpRequest->getHeader('X-LS-Callback-URL');
        }

        // Fall back to default callback URL if header is not provided
        if (!$callbackUrl && $this->defaultCallbackUrl) {
            $callbackUrl = $this->defaultCallbackUrl;
            error_log("[HttpCallbackIMipPlugin] Using default callback URL: {$callbackUrl}");
        }

        if (!$callbackUrl) {
            error_log("[HttpCallbackIMipPlugin] ERROR: X-LS-Callback-URL header or default URL is required");
            $iTipMessage->scheduleStatus = '5.4;X-LS-Callback-URL header or default URL is required';
            return;
        }

        // Ensure URL ends with trailing slash for Django's APPEND_SLASH middleware
        $callbackUrl = rtrim($callbackUrl, '/') . '/';

        // SSRF guard: only allow http(s). Without this, a caller that
        // reaches caldav directly (bypassing the Django proxy) and holds
        // the outbound API key could set ``X-LS-Callback-URL`` to e.g.
        // ``file:///etc/passwd``, ``gopher://internal-redis:6379/_SET…``
        // or ``dict://…`` and have curl deliver the iCalendar payload —
        // and the outbound API key in the headers — wherever they want.
        // The Django proxy already strips ``HTTP_X_LS_*`` from incoming
        // requests and overrides this header, so legit users can't reach
        // here at all; the guard exists to keep the blast radius small
        // when someone with the outbound key talks to caldav directly.
        $callbackScheme = strtolower((string) parse_url($callbackUrl, PHP_URL_SCHEME));
        if ($callbackScheme !== 'http' && $callbackScheme !== 'https') {
            error_log(
                "[HttpCallbackIMipPlugin] ERROR: refusing callback URL with "
                . "non-http(s) scheme: " . $callbackScheme
            );
            $iTipMessage->scheduleStatus = '5.4;Callback URL must use http(s) scheme';
            return;
        }

        // Serialize the iCalendar message
        $vcalendar = $iTipMessage->message ? $iTipMessage->message->serialize() : '';
        
        // Prepare headers
        // Trim API key to remove any whitespace from environment variable
        $apiKey = trim($this->apiKey);
        $headers = [
            'Content-Type: text/calendar',
            'X-LS-Api-Key: ' . $apiKey,
            'X-LS-Sender: ' . $iTipMessage->sender,
            'X-LS-Recipient: ' . $iTipMessage->recipient,
            'X-LS-Method: ' . $iTipMessage->method,
        ];

        // Check if the sender is a MAILBOX principal and tell Django
        // so it can route the invitation through Messages API.
        $senderEmail = substr($iTipMessage->sender, 7); // strip 'mailto:'
        if ($this->isSenderMailbox($senderEmail)) {
            $headers[] = 'X-LS-Is-Mailbox: true';
        }

        // Pass org_id so Django can include it in RSVP tokens
        if ($this->server && $this->server->httpRequest) {
            $orgId = $this->server->httpRequest->getHeader('X-LS-Org-Id');
            if ($orgId) {
                $headers[] = 'X-LS-Org-Id: ' . $orgId;
            }
        }
        
        // Make HTTP POST request to Django callback endpoint.
        // CURLOPT_PROTOCOLS / CURLOPT_REDIR_PROTOCOLS pin curl to http(s)
        // so even a (currently disabled) redirect cannot escape into
        // file://, gopher://, dict://, ldap://, etc. — defense in depth
        // alongside the scheme allowlist above.
        $ch = curl_init($callbackUrl);
        curl_setopt_array($ch, [
            CURLOPT_POST => true,
            CURLOPT_RETURNTRANSFER => true,
            CURLOPT_HTTPHEADER => $headers,
            CURLOPT_POSTFIELDS => $vcalendar,
            CURLOPT_TIMEOUT => 10,
            CURLOPT_PROTOCOLS => CURLPROTO_HTTP | CURLPROTO_HTTPS,
            CURLOPT_REDIR_PROTOCOLS => CURLPROTO_HTTP | CURLPROTO_HTTPS,
            CURLOPT_FOLLOWLOCATION => false,
        ]);
        
        $response = curl_exec($ch);
        $httpCode = curl_getinfo($ch, CURLINFO_HTTP_CODE);
        $curlError = curl_error($ch);
        curl_close($ch);
        
        if ($curlError) {
            error_log(sprintf(
                "[HttpCallbackIMipPlugin] ERROR: cURL failed: %s",
                $curlError
            ));
            $iTipMessage->scheduleStatus = '5.4;Failed to forward scheduling message via HTTP callback';
            return;
        }
        
        if ($httpCode >= 400) {
            error_log(sprintf(
                "[HttpCallbackIMipPlugin] ERROR: HTTP %d - %s",
                $httpCode,
                substr($response, 0, 200)
            ));
            $iTipMessage->scheduleStatus = '5.4;HTTP callback returned error: ' . $httpCode;
            return;
        }
        
        // Success
        $iTipMessage->scheduleStatus = '1.1;Scheduling message forwarded via HTTP callback';
    }

    /** @var array Per-request cache for mailbox checks */
    private $mailboxCache = [];

    /**
     * Check if a sender email belongs to a MAILBOX principal.
     *
     * @param string $email
     * @return bool
     */
    private function isSenderMailbox($email)
    {
        if (array_key_exists($email, $this->mailboxCache)) {
            return $this->mailboxCache[$email];
        }

        try {
            $stmt = $this->pdo->prepare(
                'SELECT calendar_user_type FROM principals WHERE uri = ?'
            );
            $stmt->execute(['principals/users/' . $email]);
            $result = $stmt->fetchColumn() === PrincipalBackend::TYPE_MAILBOX;
            $this->mailboxCache[$email] = $result;
            return $result;
        } catch (\Exception $e) {
            error_log("[HttpCallbackIMipPlugin] Failed to check principal type: " . $e->getMessage());
            return false;
        }
    }
}
