<?php
/**
 * AttendeeNormalizerPlugin - Normalizes and deduplicates attendees in CalDAV events.
 *
 * This plugin fixes a common issue with CalDAV scheduling where REPLY processing
 * can create duplicate attendees due to email case sensitivity or format differences.
 *
 * The plugin:
 * 1. Normalizes all attendee emails to lowercase
 * 2. Deduplicates attendees by email, keeping the one with the most "advanced" status
 *
 * Status priority (most to least advanced): ACCEPTED > TENTATIVE > DECLINED > NEEDS-ACTION
 */

namespace Calendars\SabreDav;

use Sabre\DAV\Server;
use Sabre\DAV\ServerPlugin;
use Sabre\VObject\Reader;
use Sabre\VObject\Component\VCalendar;

class AttendeeNormalizerPlugin extends ServerPlugin
{
    /**
     * Reference to the DAV server instance
     * @var Server
     */
    protected $server;

    /**
     * Status priority map (higher = more definitive response)
     * @var array
     */
    private const STATUS_PRIORITY = [
        'ACCEPTED' => 4,
        'TENTATIVE' => 3,
        'DECLINED' => 2,
        'NEEDS-ACTION' => 1,
    ];

    /**
     * Returns a plugin name.
     *
     * @return string
     */
    public function getPluginName()
    {
        return 'attendee-normalizer';
    }

    /**
     * Initialize the plugin.
     *
     * @param Server $server
     * @return void
     */
    public function initialize(Server $server)
    {
        $this->server = $server;

        // Hook into calendar object creation and updates
        // Priority 90 to run before most other plugins but after authentication
        $server->on('beforeCreateFile', [$this, 'beforeWriteCalendarObject'], 90);
        $server->on('beforeWriteContent', [$this, 'beforeWriteCalendarObject'], 90);
    }

    /**
     * Called before a calendar object is created or updated.
     *
     * @param string $path The path to the file
     * @param resource|string $data The data being written
     * @param \Sabre\DAV\ICollection $parentNode The parent collection
     * @param bool $modified Whether the data was modified
     * @return void
     */
    public function beforeWriteCalendarObject($path, &$data, $parentNode = null, &$modified = false)
    {
        // Only process .ics files in calendar collections
        if (!preg_match('/\.ics$/i', $path)) {
            return;
        }

        // Check if parent is a calendar collection
        if ($parentNode && !($parentNode instanceof \Sabre\CalDAV\ICalendarObjectContainer)) {
            return;
        }

        try {
            // Get the data as string
            if (is_resource($data)) {
                $dataStr = stream_get_contents($data);
                rewind($data);
            } else {
                $dataStr = $data;
            }

            // Parse the iCalendar data
            $vcalendar = Reader::read($dataStr);

            if (!$vcalendar instanceof VCalendar) {
                return;
            }

            $wasModified = false;

            // Process all VEVENT components
            foreach ($vcalendar->VEVENT as $vevent) {
                if ($this->normalizeAndDeduplicateAttendees($vevent)) {
                    $wasModified = true;
                }
            }

            // If we made changes, update the data
            if ($wasModified) {
                $newData = $vcalendar->serialize();
                $data = $newData;
                $modified = true;

                error_log("[AttendeeNormalizerPlugin] Normalized attendees in: " . $path);
            }
        } catch (\Exception $e) {
            // Log error but don't block the request
            error_log("[AttendeeNormalizerPlugin] Error processing calendar object: " . $e->getMessage());
        }
    }

    /**
     * Normalize and deduplicate attendees in a VEVENT component.
     *
     * @param \Sabre\VObject\Component\VEvent $vevent
     * @return bool True if the component was modified
     */
    private function normalizeAndDeduplicateAttendees($vevent)
    {
        if (!isset($vevent->ATTENDEE) || count($vevent->ATTENDEE) === 0) {
            return false;
        }

        $attendees = [];
        $attendeesByEmail = [];
        $wasModified = false;

        // First pass: collect and normalize all attendees
        foreach ($vevent->ATTENDEE as $attendee) {
            $email = $this->normalizeEmail((string)$attendee);
            $status = isset($attendee['PARTSTAT']) ? strtoupper((string)$attendee['PARTSTAT']) : 'NEEDS-ACTION';
            $priority = self::STATUS_PRIORITY[$status] ?? 0;

            $attendeeData = [
                'property' => $attendee,
                'email' => $email,
                'status' => $status,
                'priority' => $priority,
            ];

            if (!isset($attendeesByEmail[$email])) {
                // First occurrence of this email
                $attendeesByEmail[$email] = $attendeeData;
                $attendees[] = $attendeeData;
            } else {
                // Duplicate found
                $existing = $attendeesByEmail[$email];

                if ($priority > $existing['priority']) {
                    // New attendee has higher priority - replace
                    // Find and replace in the array
                    foreach ($attendees as $i => $att) {
                        if ($att['email'] === $email) {
                            $attendees[$i] = $attendeeData;
                            $attendeesByEmail[$email] = $attendeeData;
                            break;
                        }
                    }
                }

                $wasModified = true;
                error_log("[AttendeeNormalizerPlugin] Found duplicate attendee: {$email} (keeping status: " . $attendeesByEmail[$email]['status'] . ")");
            }
        }

        // Also normalize the email in the value (lowercase the mailto: part)
        foreach ($vevent->ATTENDEE as $attendee) {
            $value = (string)$attendee;
            $normalizedValue = $this->normalizeMailtoValue($value);

            if ($value !== $normalizedValue) {
                $attendee->setValue($normalizedValue);
                $wasModified = true;
            }
        }

        // If duplicates were found, rebuild the ATTENDEE list
        if ($wasModified && count($attendees) < count($vevent->ATTENDEE)) {
            // Remove all existing ATTENDEEs
            unset($vevent->ATTENDEE);

            // Add back the deduplicated attendees
            foreach ($attendees as $attendeeData) {
                $property = $attendeeData['property'];

                // Clone the property to the vevent
                $newAttendee = $vevent->add('ATTENDEE', $this->normalizeMailtoValue((string)$property));

                // Copy all parameters
                foreach ($property->parameters() as $param) {
                    $newAttendee[$param->name] = $param->getValue();
                }
            }

            error_log("[AttendeeNormalizerPlugin] Reduced attendees from " . count($vevent->ATTENDEE) . " to " . count($attendees));
        }

        return $wasModified;
    }

    /**
     * Normalize an email address extracted from a mailto: URI.
     *
     * @param string $value The ATTENDEE value (e.g., "mailto:User@Example.com")
     * @return string Normalized email (lowercase)
     */
    private function normalizeEmail($value)
    {
        // Remove mailto: prefix if present
        $email = preg_replace('/^mailto:/i', '', $value);

        // Lowercase and trim
        return strtolower(trim($email));
    }

    /**
     * Normalize the mailto: value to have lowercase email.
     *
     * @param string $value The ATTENDEE value (e.g., "mailto:User@Example.com")
     * @return string Normalized value (e.g., "mailto:user@example.com")
     */
    private function normalizeMailtoValue($value)
    {
        if (stripos($value, 'mailto:') === 0) {
            $email = substr($value, 7);
            return 'mailto:' . strtolower(trim($email));
        }

        return strtolower(trim($value));
    }

    /**
     * Returns a list of features for the DAV: header.
     *
     * @return array
     */
    public function getFeatures()
    {
        return [];
    }
}
