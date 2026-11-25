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
use Sabre\HTTP\RequestInterface;
use Sabre\HTTP\ResponseInterface;
use Sabre\VObject\Component;
use Sabre\VObject\Component\VCalendar;
use Sabre\VObject\Component\VEvent;
use Sabre\VObject\ITip\Message;
use Sabre\VObject\Property;
use Sabre\VObject\Reader;
use Sabre\VObject\Recur\EventIterator;

class HttpCallbackIMipPlugin extends IMipPlugin
{
    private const WRITE_PROPERTIES = ['CREATED', 'DTSTAMP', 'LAST-MODIFIED', 'SEQUENCE'];

    private const TIME_PROPERTIES = ['DTEND', 'DTSTART', 'DURATION', 'RECURRENCE-ID'];

    private const ANSWER_PARAMETERS = ['PARTSTAT', 'RSVP', 'SCHEDULE-STATUS'];

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
     * Attendee emails of the stored events that this request updates.
     * Keys are event UIDs. Values are sets of lowercase emails.
     * @var array<string, array<string, true>>
     */
    private $previousAttendees = [];

    /**
     * UIDs of the events that this request changes only by new entries
     * for regular dates. Each new entry is a copy of its date, with other
     * answers of the attendees.
     * @var array<string, true>
     */
    private $answerOnlyUids = [];

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
        // Priority 90 runs before the scheduling plugin (priority 100).
        $server->on('calendarObjectChange', [$this, 'inspectStoredEvent'], 90);
    }

    /**
     * Compare the stored event with the new one before the overwrite.
     *
     * Keep the attendees of the stored event. A new event has no previous
     * attendees.
     *
     * @return void
     */
    public function inspectStoredEvent(
        RequestInterface $request,
        ResponseInterface $response,
        VCalendar $vCal,
        $calendarPath,
        &$modified,
        $isNew
    ) {
        if ($isNew) {
            foreach ($vCal->VEVENT ?? [] as $vevent) {
                $this->previousAttendees[(string) $vevent->UID] = [];
            }
            return;
        }

        try {
            $node = $this->server->tree->getNodeForPath($request->getPath());
            $stored = Reader::read($node->get());
        } catch (\Exception $e) {
            error_log("[HttpCallbackIMipPlugin] Failed to read the stored event: " . $e->getMessage());
            return;
        }

        foreach ($stored->VEVENT ?? [] as $vevent) {
            $uid = (string) $vevent->UID;
            $this->previousAttendees[$uid] = $this->previousAttendees[$uid] ?? [];
            foreach ($vevent->ATTENDEE ?? [] as $attendee) {
                $this->previousAttendees[$uid][$this->normalizeEmail($attendee->getValue())] = true;
            }
        }

        try {
            if ($this->onlyAddsRegularDates($vCal, $stored)) {
                $this->answerOnlyUids[(string) $vCal->VEVENT->UID] = true;
            }
        } catch (\Exception $e) {
            error_log("[HttpCallbackIMipPlugin] Failed to compare the stored event: " . $e->getMessage());
        }
        $stored->destroy();
    }

    /**
     * Tell if the new event only adds entries for regular dates.
     *
     * SabreDAV marks each new entry as a significant change for all the
     * attendees. A copy of a regular date with other answers changes
     * nothing for them.
     */
    private function onlyAddsRegularDates(VCalendar $vCal, VCalendar $stored): bool
    {
        if (!isset($stored->VEVENT->ORGANIZER)
            || $this->hasRange($vCal)
            || $this->hasRange($stored)
            || $this->timezones($vCal) !== $this->timezones($stored)) {
            return false;
        }

        $storedEntries = [];
        foreach ($stored->VEVENT as $vevent) {
            $storedEntries[$this->recurrenceId($vevent)] = $vevent;
        }

        $kept = 0;
        $added = false;
        foreach ($vCal->VEVENT as $vevent) {
            $storedEntry = $storedEntries[$this->recurrenceId($vevent)] ?? null;
            if ($storedEntry) {
                $kept++;
                if ($this->answerless($vevent, self::WRITE_PROPERTIES)
                    !== $this->answerless($storedEntry, self::WRITE_PROPERTIES)) {
                    return false;
                }
            } elseif ($this->matchesRegularDate($vevent, $stored)) {
                $added = true;
            } else {
                return false;
            }
        }
        return $added && $kept === count($storedEntries);
    }

    /**
     * Tell if an entry has a RANGE, such as RANGE=THISANDFUTURE.
     *
     * Such an entry also changes the later dates. EventIterator does not
     * support it, so the regular dates are not known.
     */
    private function hasRange(VCalendar $vCal): bool
    {
        foreach ($vCal->VEVENT as $vevent) {
            if (isset($vevent->{'RECURRENCE-ID'}['RANGE'])) {
                return true;
            }
        }
        return false;
    }

    /**
     * @return string[] Sorted VTIMEZONE components, with sorted properties
     */
    private function timezones(VCalendar $vCal): array
    {
        $timezones = [];
        foreach ($vCal->select('VTIMEZONE') as $timezone) {
            $timezones[] = implode("\n", $this->answerless($timezone, []));
        }
        sort($timezones);
        return $timezones;
    }

    private function recurrenceId(VEvent $vevent): string
    {
        return isset($vevent->{'RECURRENCE-ID'}) ? $vevent->{'RECURRENCE-ID'}->getValue() : 'master';
    }

    /**
     * Tell if a new entry is a copy of its regular date in the stored
     * event. Only the answers of the attendees can differ.
     */
    private function matchesRegularDate(VEvent $vevent, VCalendar $stored): bool
    {
        if (!isset($vevent->{'RECURRENCE-ID'})) {
            return false;
        }

        $date = $vevent->{'RECURRENCE-ID'}->getDateTime();
        $occurrences = new EventIterator($stored, (string) $vevent->UID);
        while ($occurrences->valid() && $occurrences->getDtStart() < $date) {
            $occurrences->next();
        }
        if (!$occurrences->valid() || $occurrences->getDtStart() != $date) {
            return false;
        }

        $regular = $occurrences->getEventObject();
        // A moved date can start at the time of the new entry.
        if ($regular->{'RECURRENCE-ID'}->getDateTime() != $date) {
            return false;
        }
        $skipped = array_merge(self::WRITE_PROPERTIES, self::TIME_PROPERTIES);
        return $vevent->DTSTART->getDateTime() == $occurrences->getDtStart()
            && $vevent->DTSTART->hasTime() === $regular->DTSTART->hasTime()
            && $vevent->DTSTART->isFloating() === $regular->DTSTART->isFloating()
            && $this->endOf($vevent) == $this->endOf($regular)
            && $this->endIsFloating($vevent) === $this->endIsFloating($regular)
            && $this->answerless($vevent, $skipped) === $this->answerless($regular, $skipped);
    }

    private function endIsFloating(VEvent $vevent): bool
    {
        return isset($vevent->DTEND) ? $vevent->DTEND->isFloating() : $vevent->DTSTART->isFloating();
    }

    private function endOf(VEvent $vevent): \DateTimeImmutable
    {
        $start = $vevent->DTSTART->getDateTime();
        if (isset($vevent->DTEND)) {
            return $vevent->DTEND->getDateTime();
        }
        if (isset($vevent->DURATION)) {
            return $start->add($vevent->DURATION->getDateInterval());
        }
        return $vevent->DTSTART->hasTime() ? $start : $start->modify('+1 day');
    }

    /**
     * @param string[] $skipped Names of the properties to leave out
     * @return string[] Sorted serialized children, with sorted parameters
     *                  and without the answers of the attendees. Nested
     *                  components get the same treatment.
     */
    private function answerless(Component $component, array $skipped): array
    {
        $children = [];
        foreach ($component->children() as $child) {
            if (in_array($child->name, $skipped, true)) {
                continue;
            }
            if (!$child instanceof Property) {
                $children[] = $child->name . '{' . implode("\n", $this->answerless($child, [])) . '}';
                continue;
            }
            $isAttendee = 'ATTENDEE' === $child->name;
            $parameters = [];
            foreach ($child->parameters() as $parameter) {
                if (!$isAttendee || !in_array($parameter->name, self::ANSWER_PARAMETERS, true)) {
                    $parameters[] = $parameter->serialize();
                }
            }
            sort($parameters);
            $value = $isAttendee ? $this->normalizeEmail($child->getValue()) : $child->getRawMimeDirValue();
            $children[] = $child->name . ';' . implode(';', $parameters) . ':' . $value;
        }
        sort($children);
        return $children;
    }

    /**
     * Tell if the recipient of a REQUEST is not on the stored event.
     *
     * All the recipients of a created event are new attendees.
     */
    private function isNewAttendee(Message $iTipMessage): bool
    {
        if ('REQUEST' !== $iTipMessage->method || !isset($this->previousAttendees[$iTipMessage->uid])) {
            return false;
        }
        $recipient = $this->normalizeEmail($iTipMessage->recipient);
        return !isset($this->previousAttendees[$iTipMessage->uid][$recipient]);
    }

    private function normalizeEmail(string $address): string
    {
        return strtolower(preg_replace('/^mailto:/i', '', trim($address)));
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

        if ('REQUEST' === $iTipMessage->method && isset($this->answerOnlyUids[$iTipMessage->uid])) {
            $iTipMessage->scheduleStatus = '1.0;The change only records an answer for one date';
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

        if ($this->isNewAttendee($iTipMessage)) {
            $headers[] = 'X-LS-New-Attendee: true';
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
