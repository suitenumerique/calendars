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
     * Default callback URL (fallback if header is not provided)
     * @var string|null
     */
    private $defaultCallbackUrl;

    /**
     * Constructor
     *
     * @param string $apiKey The API key for authenticating with the callback endpoint
     * @param string|null $defaultCallbackUrl Optional default callback URL
     */
    public function __construct($apiKey, $defaultCallbackUrl = null)
    {
        // Call parent constructor with empty email (we won't use it)
        parent::__construct('');

        $this->apiKey = $apiKey;
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
            $callbackUrl = $this->server->httpRequest->getHeader('X-CalDAV-Callback-URL');
        }

        // Fall back to default callback URL if header is not provided
        if (!$callbackUrl && $this->defaultCallbackUrl) {
            $callbackUrl = $this->defaultCallbackUrl;
            error_log("[HttpCallbackIMipPlugin] Using default callback URL: {$callbackUrl}");
        }

        if (!$callbackUrl) {
            error_log("[HttpCallbackIMipPlugin] ERROR: X-CalDAV-Callback-URL header or default URL is required");
            $iTipMessage->scheduleStatus = '5.4;X-CalDAV-Callback-URL header or default URL is required';
            return;
        }

        // Ensure URL ends with trailing slash for Django's APPEND_SLASH middleware
        $callbackUrl = rtrim($callbackUrl, '/') . '/';

        // Serialize the iCalendar message
        $vcalendar = $iTipMessage->message ? $iTipMessage->message->serialize() : '';
        
        // Prepare headers
        // Trim API key to remove any whitespace from environment variable
        $apiKey = trim($this->apiKey);
        $headers = [
            'Content-Type: text/calendar',
            'X-Api-Key: ' . $apiKey,
            'X-CalDAV-Sender: ' . $iTipMessage->sender,
            'X-CalDAV-Recipient: ' . $iTipMessage->recipient,
            'X-CalDAV-Method: ' . $iTipMessage->method,
        ];
        
        // Make HTTP POST request to Django callback endpoint
        $ch = curl_init($callbackUrl);
        curl_setopt_array($ch, [
            CURLOPT_POST => true,
            CURLOPT_RETURNTRANSFER => true,
            CURLOPT_HTTPHEADER => $headers,
            CURLOPT_POSTFIELDS => $vcalendar,
            CURLOPT_TIMEOUT => 10,
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
}
