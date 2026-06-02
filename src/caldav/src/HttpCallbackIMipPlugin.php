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
     * Callback URL set at startup from CALDAV_CALLBACK_BASE_URL
     * @var string
     */
    private $callbackUrl;

    /**
     * Constructor
     *
     * @param string $apiKey The API key for authenticating with the callback endpoint
     * @param \PDO $pdo Database connection for principal lookups
     * @param string $callbackUrl The callback URL (base URL + path, built at startup)
     */
    public function __construct($apiKey, \PDO $pdo, $callbackUrl)
    {
        // Call parent constructor with empty email (we won't use it)
        parent::__construct('');

        $this->apiKey = $apiKey;
        $this->pdo = $pdo;
        $this->callbackUrl = rtrim($callbackUrl, '/') . '/';
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

        // Serialize the iCalendar message
        $vcalendar = $iTipMessage->message ? $iTipMessage->message->serialize() : '';
        
        // Prepare headers.
        //
        // SECURITY: every header VALUE concatenated below was sourced
        // from attacker-influenceable iCalendar property text
        // (ORGANIZER/ATTENDEE URIs, METHOD token). vobject's parser
        // preserves lone CR bytes (no following LF) inside URI
        // properties, and while our re-serialize invariant strips
        // them at storage time, the Schedule plugin may consume the
        // iTip message before that re-serialize lands. Sanitize at
        // the boundary regardless — anything other than printable
        // ASCII becomes underscore. libcurl rejects literal CR/LF
        // in headers in modern versions, but defense-in-depth here
        // means we don't depend on that.
        $apiKey = trim($this->apiKey);
        $headers = [
            'Content-Type: text/calendar',
            'X-LS-Api-Key: ' . $apiKey,
            'X-LS-Sender: ' . $this->sanitizeHeaderValue($iTipMessage->sender),
            'X-LS-Recipient: ' . $this->sanitizeHeaderValue($iTipMessage->recipient),
            'X-LS-Method: ' . $this->sanitizeHeaderValue($iTipMessage->method),
        ];

        // Check if the sender is a MAILBOX principal and tell Django
        // so it can route the invitation through Messages API.
        $senderEmail = substr($iTipMessage->sender, 7); // strip 'mailto:'
        if ($this->isSenderMailbox($senderEmail)) {
            $headers[] = 'X-LS-Is-Mailbox: true';
        }

        // Pass org_id so Django can include it in RSVP tokens.
        // Sanitize before concatenating: while the inbound request
        // header is normally already CR/LF-stripped by the SAPI,
        // we apply the same defense-in-depth pass we use for the
        // iTip-sourced headers above so a misbehaving reverse proxy
        // (or a future direct caller) can't smuggle a header break.
        if ($this->server && $this->server->httpRequest) {
            $orgId = $this->server->httpRequest->getHeader('X-LS-Org-Id');
            if ($orgId) {
                $headers[] = 'X-LS-Org-Id: ' . $this->sanitizeHeaderValue($orgId);
            }
        }
        
        // Make HTTP POST request to Django callback endpoint.
        $ch = curl_init($this->callbackUrl);
        curl_setopt_array($ch, [
            CURLOPT_POST => true,
            CURLOPT_RETURNTRANSFER => true,
            CURLOPT_HTTPHEADER => $headers,
            CURLOPT_POSTFIELDS => $vcalendar,
            CURLOPT_TIMEOUT => 10,
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

    /**
     * Strip anything that could break the HTTP header line.
     *
     * Replaces every byte outside the printable-ASCII range (0x20-0x7E)
     * with `_`. Catches CR/LF (header injection) and high-bit bytes
     * (libcurl semantics vary by version). Returns a string short
     * enough not to make oversized headers — 1024 bytes is the cap
     * (typical CalDAV URI / iTIP token is well under 256).
     */
    private function sanitizeHeaderValue($value): string
    {
        $s = (string) $value;
        if (strlen($s) > 1024) {
            $s = substr($s, 0, 1024);
        }
        return preg_replace('/[^\x20-\x7E]/', '_', $s) ?? '';
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
                'SELECT 1 FROM principals WHERE uri = ?'
            );
            $stmt->execute(['principals/mailboxes/' . $email]);
            $result = (bool) $stmt->fetchColumn();
            $this->mailboxCache[$email] = $result;
            return $result;
        } catch (\Exception $e) {
            error_log("[HttpCallbackIMipPlugin] Failed to check principal type: " . $e->getMessage());
            return false;
        }
    }
}
