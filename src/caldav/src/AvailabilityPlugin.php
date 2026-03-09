<?php
/**
 * AvailabilityPlugin - Integrates VAVAILABILITY (RFC 7953) into freebusy responses.
 *
 * When a freebusy query is made via the scheduling outbox, this plugin
 * post-processes the response to add BUSY-UNAVAILABLE periods based on
 * each recipient's calendar-availability property.
 *
 * The calendar-availability property is stored on the user's calendar home
 * via the PropertyStorage plugin and contains a VCALENDAR with VAVAILABILITY
 * and AVAILABLE components that define working hours.
 *
 * Runs after Schedule\Plugin (priority 200 on afterMethod:POST).
 */

namespace Calendars\SabreDav;

use Sabre\DAV;
use Sabre\DAV\Server;
use Sabre\DAV\ServerPlugin;
use Sabre\HTTP\RequestInterface;
use Sabre\HTTP\ResponseInterface;
use Sabre\VObject\Reader;

class AvailabilityPlugin extends ServerPlugin
{
    /** @var Server */
    protected $server;

    /** CalDAV namespace */
    private const CALDAV_NS = '{urn:ietf:params:xml:ns:caldav}';

    /** calendar-availability property name */
    private const AVAILABILITY_PROP = '{urn:ietf:params:xml:ns:caldav}calendar-availability';

    public function initialize(Server $server)
    {
        $this->server = $server;
        // Priority 200: runs after Schedule\Plugin (110) has built the response
        $server->on('afterMethod:POST', [$this, 'afterPost'], 200);
    }

    /**
     * Post-process scheduling outbox responses to inject BUSY-UNAVAILABLE periods.
     */
    public function afterPost(RequestInterface $request, ResponseInterface $response)
    {
        // Only process successful responses
        if ($response->getStatus() !== 200) {
            return;
        }

        // Only process outbox requests
        $path = $request->getPath();
        if (strpos($path, 'outbox') === false) {
            return;
        }

        // Only process XML responses
        $contentType = $response->getHeader('Content-Type');
        if (!$contentType || strpos($contentType, 'application/xml') === false) {
            return;
        }

        $body = $response->getBodyAsString();
        if (!$body) {
            return;
        }

        try {
            $modified = $this->processScheduleResponse($body);
            if ($modified !== null) {
                $response->setBody($modified);
            }
        } catch (\Exception $e) {
            error_log("[AvailabilityPlugin] Error processing response: " . $e->getMessage());
        }
    }

    /**
     * Parse the schedule-response XML and inject BUSY-UNAVAILABLE periods
     * for each recipient that has a calendar-availability property.
     *
     * @param string $xml The original XML response body
     * @return string|null Modified XML or null if no changes
     */
    private function processScheduleResponse($xml)
    {
        $dom = new \DOMDocument();
        $dom->preserveWhiteSpace = true;
        $dom->formatOutput = false;

        if (!@$dom->loadXML($xml)) {
            error_log("[AvailabilityPlugin] Failed to parse XML response");
            return null;
        }

        $xpath = new \DOMXPath($dom);
        $xpath->registerNamespace('D', 'DAV:');
        $xpath->registerNamespace('C', 'urn:ietf:params:xml:ns:caldav');

        // Find all schedule-response/response elements
        $responses = $xpath->query('//C:schedule-response/C:response');
        if (!$responses || $responses->length === 0) {
            return null;
        }

        $modified = false;

        foreach ($responses as $responseNode) {
            // Extract recipient email
            $recipientNodes = $xpath->query('.//C:recipient/D:href', $responseNode);
            if (!$recipientNodes || $recipientNodes->length === 0) {
                continue;
            }
            $recipientHref = $recipientNodes->item(0)->textContent;
            $email = $this->extractEmail($recipientHref);
            if (!$email) {
                continue;
            }

            // Find calendar-data element
            $calDataNodes = $xpath->query('.//C:calendar-data', $responseNode);
            if (!$calDataNodes || $calDataNodes->length === 0) {
                continue;
            }
            $calDataNode = $calDataNodes->item(0);
            $icsData = $calDataNode->textContent;

            if (strpos($icsData, 'VFREEBUSY') === false) {
                continue;
            }

            // Get the user's availability property
            $availability = $this->getCalendarAvailability($email);
            if (!$availability) {
                continue;
            }

            // Parse available windows from the VAVAILABILITY
            $availableWindows = $this->parseAvailableWindows($availability);
            if (empty($availableWindows)) {
                continue;
            }

            // Extract the freebusy query range from the VFREEBUSY component
            $queryRange = $this->extractFreebusyRange($icsData);
            if (!$queryRange) {
                continue;
            }

            // Compute BUSY-UNAVAILABLE periods
            $busyPeriods = $this->computeBusyUnavailable(
                $queryRange['start'],
                $queryRange['end'],
                $availableWindows
            );

            if (empty($busyPeriods)) {
                continue;
            }

            // Inject BUSY-UNAVAILABLE lines into the ICS data
            $modifiedIcs = $this->injectBusyUnavailable($icsData, $busyPeriods);
            if ($modifiedIcs !== null) {
                $calDataNode->textContent = '';
                $calDataNode->appendChild($dom->createTextNode($modifiedIcs));
                $modified = true;
            }
        }

        if ($modified) {
            return $dom->saveXML();
        }

        return null;
    }

    /**
     * Extract email from a mailto: URI.
     *
     * @param string $uri
     * @return string|null
     */
    private function extractEmail($uri)
    {
        if (stripos($uri, 'mailto:') === 0) {
            return strtolower(substr($uri, 7));
        }
        return null;
    }

    /**
     * Get the calendar-availability property for a user.
     *
     * Resolves the calendar home path from the principal URI via the
     * CalDAV plugin rather than hardcoding the path structure.
     *
     * @param string $email
     * @return string|null The VCALENDAR string or null
     */
    private function getCalendarAvailability($email)
    {
        $caldavPlugin = $this->server->getPlugin('caldav');
        if (!$caldavPlugin) {
            return null;
        }

        $principalUri = 'principals/users/' . $email;
        $calendarHomePath = $caldavPlugin->getCalendarHomeForPrincipal($principalUri);
        if (!$calendarHomePath) {
            return null;
        }

        try {
            $properties = $this->server->getProperties(
                $calendarHomePath,
                [self::AVAILABILITY_PROP]
            );

            if (isset($properties[self::AVAILABILITY_PROP])) {
                return $properties[self::AVAILABILITY_PROP];
            }
        } catch (\Exception $e) {
            error_log("[AvailabilityPlugin] Failed to get availability for user: "
                . $e->getMessage());
        }

        return null;
    }

    /**
     * Parse VAVAILABILITY/AVAILABLE components to extract available windows.
     *
     * Returns an array of available window definitions, each with:
     * - 'startTime': time string "HH:MM:SS"
     * - 'endTime': time string "HH:MM:SS"
     * - 'days': array of day-of-week integers (1=Monday .. 7=Sunday, ISO-8601)
     * - 'specificDate': string "Y-m-d" if this is a specific-date window (no RRULE)
     *
     * @param string $vcalendarStr
     * @return array
     */
    private function parseAvailableWindows($vcalendarStr)
    {
        $windows = [];

        try {
            $vcalendar = Reader::read($vcalendarStr);
        } catch (\Exception $e) {
            error_log("[AvailabilityPlugin] Failed to parse VAVAILABILITY: " . $e->getMessage());
            return $windows;
        }

        if (!isset($vcalendar->VAVAILABILITY)) {
            return $windows;
        }

        foreach ($vcalendar->VAVAILABILITY as $vavailability) {
            if (!isset($vavailability->AVAILABLE)) {
                continue;
            }

            foreach ($vavailability->AVAILABLE as $available) {
                if (!isset($available->DTSTART) || !isset($available->DTEND)) {
                    continue;
                }

                $dtstart = $available->DTSTART->getDateTime();
                $dtend = $available->DTEND->getDateTime();

                $startTime = $dtstart->format('H:i:s');
                $endTime = $dtend->format('H:i:s');

                // Parse RRULE to get BYDAY
                $days = [];
                $specificDate = null;
                if (isset($available->RRULE)) {
                    $rrule = (string)$available->RRULE;
                    if (preg_match('/BYDAY=([A-Z,]+)/', $rrule, $matches)) {
                        $dayMap = [
                            'MO' => 1,
                            'TU' => 2,
                            'WE' => 3,
                            'TH' => 4,
                            'FR' => 5,
                            'SA' => 6,
                            'SU' => 7,
                        ];
                        foreach (explode(',', $matches[1]) as $day) {
                            if (isset($dayMap[$day])) {
                                $days[] = $dayMap[$day];
                            }
                        }
                    }
                } else {
                    // No RRULE: specific-date availability, scoped to DTSTART date
                    $specificDate = $dtstart->format('Y-m-d');
                    $days = [(int)$dtstart->format('N')];
                }

                $windows[] = [
                    'startTime' => $startTime,
                    'endTime' => $endTime,
                    'days' => $days,
                    'specificDate' => $specificDate,
                ];
            }
        }

        return $windows;
    }

    /**
     * Extract the DTSTART and DTEND range from a VFREEBUSY component.
     *
     * @param string $icsData
     * @return array|null ['start' => DateTimeImmutable, 'end' => DateTimeImmutable]
     */
    private function extractFreebusyRange($icsData)
    {
        try {
            $vcalendar = Reader::read($icsData);
        } catch (\Exception $e) {
            error_log("[AvailabilityPlugin] Failed to parse VFREEBUSY ICS: " . $e->getMessage());
            return null;
        }

        if (!isset($vcalendar->VFREEBUSY)) {
            return null;
        }

        $vfreebusy = $vcalendar->VFREEBUSY;

        if (!isset($vfreebusy->DTSTART) || !isset($vfreebusy->DTEND)) {
            return null;
        }

        return [
            'start' => $vfreebusy->DTSTART->getDateTime(),
            'end' => $vfreebusy->DTEND->getDateTime(),
        ];
    }

    /**
     * Compute BUSY-UNAVAILABLE periods for times outside available windows.
     *
     * TODO: The available times in DTSTART/DTEND of AVAILABLE are treated as
     * UTC for now. Proper timezone handling would require resolving the TZID
     * from the VAVAILABILITY component and converting accordingly.
     *
     * @param \DateTimeInterface $rangeStart
     * @param \DateTimeInterface $rangeEnd
     * @param array $windows Available windows from parseAvailableWindows()
     * @return array Array of ['start' => DateTimeImmutable, 'end' => DateTimeImmutable]
     */
    private function computeBusyUnavailable(
        \DateTimeInterface $rangeStart,
        \DateTimeInterface $rangeEnd,
        array $windows
    ) {
        $utc = new \DateTimeZone('UTC');
        $busyPeriods = [];

        // Iterate day by day through the range
        $currentDay = new \DateTimeImmutable(
            $rangeStart->format('Y-m-d'),
            $utc
        );
        $endDay = new \DateTimeImmutable(
            $rangeEnd->format('Y-m-d'),
            $utc
        );

        while ($currentDay <= $endDay) {
            $dayOfWeek = (int)$currentDay->format('N'); // 1=Monday .. 7=Sunday
            $dayStart = $currentDay;
            $dayEnd = $currentDay->modify('+1 day');

            // Clamp to the query range
            $effectiveDayStart = $dayStart < $rangeStart
                ? new \DateTimeImmutable($rangeStart->format('Y-m-d\TH:i:s'), $utc)
                : $dayStart;
            $effectiveDayEnd = $dayEnd > $rangeEnd
                ? new \DateTimeImmutable($rangeEnd->format('Y-m-d\TH:i:s'), $utc)
                : $dayEnd;

            if ($effectiveDayStart >= $effectiveDayEnd) {
                $currentDay = $currentDay->modify('+1 day');
                continue;
            }

            // Collect available slots for this day of the week
            $availableSlots = [];
            $dateStr = $currentDay->format('Y-m-d');
            foreach ($windows as $window) {
                // Skip specific-date windows that don't match this day
                if ($window['specificDate'] !== null && $window['specificDate'] !== $dateStr) {
                    continue;
                }
                if (in_array($dayOfWeek, $window['days'], true)) {
                    $slotStart = new \DateTimeImmutable(
                        $currentDay->format('Y-m-d') . 'T' . $window['startTime'],
                        $utc
                    );
                    $slotEnd = new \DateTimeImmutable(
                        $currentDay->format('Y-m-d') . 'T' . $window['endTime'],
                        $utc
                    );

                    // Clamp to effective day range
                    if ($slotStart < $effectiveDayStart) {
                        $slotStart = $effectiveDayStart;
                    }
                    if ($slotEnd > $effectiveDayEnd) {
                        $slotEnd = $effectiveDayEnd;
                    }

                    if ($slotStart < $slotEnd) {
                        $availableSlots[] = [
                            'start' => $slotStart,
                            'end' => $slotEnd,
                        ];
                    }
                }
            }

            // Sort available slots by start time
            usort($availableSlots, function ($a, $b) {
                return $a['start'] <=> $b['start'];
            });

            // Merge overlapping slots
            $mergedSlots = [];
            foreach ($availableSlots as $slot) {
                if (empty($mergedSlots)) {
                    $mergedSlots[] = $slot;
                } else {
                    $last = &$mergedSlots[count($mergedSlots) - 1];
                    if ($slot['start'] <= $last['end']) {
                        if ($slot['end'] > $last['end']) {
                            $last['end'] = $slot['end'];
                        }
                    } else {
                        $mergedSlots[] = $slot;
                    }
                    unset($last);
                }
            }

            // Compute gaps (BUSY-UNAVAILABLE periods)
            $cursor = $effectiveDayStart;
            foreach ($mergedSlots as $slot) {
                if ($cursor < $slot['start']) {
                    $busyPeriods[] = [
                        'start' => $cursor,
                        'end' => $slot['start'],
                    ];
                }
                $cursor = $slot['end'];
            }
            if ($cursor < $effectiveDayEnd) {
                $busyPeriods[] = [
                    'start' => $cursor,
                    'end' => $effectiveDayEnd,
                ];
            }

            $currentDay = $currentDay->modify('+1 day');
        }

        return $busyPeriods;
    }

    /**
     * Inject FREEBUSY;FBTYPE=BUSY-UNAVAILABLE lines into a VFREEBUSY ICS string.
     *
     * @param string $icsData
     * @param array $busyPeriods
     * @return string|null Modified ICS data or null if injection failed
     */
    private function injectBusyUnavailable($icsData, array $busyPeriods)
    {
        // Build FREEBUSY lines
        $lines = '';
        foreach ($busyPeriods as $period) {
            $start = $period['start']->format('Ymd\THis\Z');
            $end = $period['end']->format('Ymd\THis\Z');
            $lines .= "FREEBUSY;FBTYPE=BUSY-UNAVAILABLE:{$start}/{$end}\r\n";
        }

        // Insert before END:VFREEBUSY
        $pos = strpos($icsData, "END:VFREEBUSY");
        if ($pos === false) {
            return null;
        }

        return substr($icsData, 0, $pos) . $lines . substr($icsData, $pos);
    }

    public function getPluginName()
    {
        return 'availability';
    }

    public function getPluginInfo()
    {
        return [
            'name' => $this->getPluginName(),
            'description' => 'Integrates VAVAILABILITY (RFC 7953) into freebusy responses',
        ];
    }
}
