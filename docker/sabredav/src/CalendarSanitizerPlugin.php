<?php
/**
 * CalendarSanitizerPlugin - Sanitizes calendar data on all CalDAV writes.
 *
 * Applied to both new creates (PUT to new URI) and updates (PUT to existing URI).
 * This covers events coming from any CalDAV client (Thunderbird, Apple Calendar,
 * Outlook, etc.) as well as the bulk import plugin.
 *
 * Sanitizations:
 * 1. Strip inline binary attachments (ATTACH;VALUE=BINARY / ENCODING=BASE64)
 *    These are typically Outlook/Exchange email signature images that bloat storage.
 *    URL-based attachments (e.g. Google Drive links) are preserved.
 * 2. Truncate oversized text properties:
 *    - Long text fields (DESCRIPTION, X-ALT-DESC, COMMENT): configurable limit (default 100KB)
 *    - Short text fields (SUMMARY, LOCATION): fixed 1KB safety guardrail
 * 3. Enforce max resource size (default 1MB) on the final serialized object.
 *    Returns HTTP 507 Insufficient Storage if exceeded after sanitization.
 *
 * Controlled by constructor parameters (read from env vars in server.php).
 */

namespace Calendars\SabreDav;

use Sabre\DAV\Server;
use Sabre\DAV\ServerPlugin;
use Sabre\DAV\Exception\InsufficientStorage;
use Sabre\VObject\Reader;
use Sabre\VObject\Component\VCalendar;

class CalendarSanitizerPlugin extends ServerPlugin
{
    /** @var Server */
    protected $server;

    /** @var bool Whether to strip inline binary attachments */
    private $stripBinaryAttachments;

    /** @var int Max size in bytes for long text properties: DESCRIPTION, X-ALT-DESC, COMMENT (0 = no limit) */
    private $maxDescriptionBytes;

    /** @var int Max total resource size in bytes after sanitization (0 = no limit) */
    private $maxResourceSize;

    /** @var int Max size in bytes for short text properties: SUMMARY, LOCATION */
    private const MAX_SHORT_TEXT_BYTES = 1024;

    /** @var array Long text properties subject to $maxDescriptionBytes */
    private const LONG_TEXT_PROPERTIES = ['DESCRIPTION', 'X-ALT-DESC', 'COMMENT'];

    /** @var array Short text properties subject to MAX_SHORT_TEXT_BYTES */
    private const SHORT_TEXT_PROPERTIES = ['SUMMARY', 'LOCATION'];

    public function __construct(
        bool $stripBinaryAttachments = true,
        int $maxDescriptionBytes = 102400,
        int $maxResourceSize = 1048576
    ) {
        $this->stripBinaryAttachments = $stripBinaryAttachments;
        $this->maxDescriptionBytes = $maxDescriptionBytes;
        $this->maxResourceSize = $maxResourceSize;
    }

    public function getPluginName()
    {
        return 'calendar-sanitizer';
    }

    public function initialize(Server $server)
    {
        $this->server = $server;

        // Priority 85: run before AttendeeNormalizerPlugin (90) and CalDAV validation (100)
        $server->on('beforeCreateFile', [$this, 'beforeCreateCalendarObject'], 85);
        $server->on('beforeWriteContent', [$this, 'beforeUpdateCalendarObject'], 85);
    }

    /**
     * Called before a calendar object is created.
     * Signature: ($path, &$data, \Sabre\DAV\ICollection $parent, &$modified)
     */
    public function beforeCreateCalendarObject($path, &$data, $parentNode = null, &$modified = false)
    {
        $this->sanitizeCalendarData($path, $data, $modified);
    }

    /**
     * Called before a calendar object is updated.
     * Signature: ($path, \Sabre\DAV\IFile $node, &$data, &$modified)
     */
    public function beforeUpdateCalendarObject($path, $node, &$data, &$modified = false)
    {
        $this->sanitizeCalendarData($path, $data, $modified);
    }

    /**
     * Sanitize raw calendar data from a beforeCreateFile/beforeWriteContent hook.
     */
    private function sanitizeCalendarData($path, &$data, &$modified)
    {
        // Only process .ics files
        if (!preg_match('/\.ics$/i', $path)) {
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

            $vcalendar = Reader::read($dataStr);

            if (!$vcalendar instanceof VCalendar) {
                return;
            }

            if ($this->sanitizeVCalendar($vcalendar)) {
                $data = $vcalendar->serialize();
                $modified = true;
            }

            // Enforce max resource size after sanitization
            $finalSize = is_string($data) ? strlen($data) : strlen($dataStr);
            if ($this->maxResourceSize > 0 && $finalSize > $this->maxResourceSize) {
                throw new InsufficientStorage(
                    "Calendar object size ({$finalSize} bytes) exceeds limit ({$this->maxResourceSize} bytes)"
                );
            }
        } catch (InsufficientStorage $e) {
            // Re-throw size limit errors — these must reach the client as HTTP 507
            throw $e;
        } catch (\Exception $e) {
            // Log other errors but don't block the request
            error_log("[CalendarSanitizerPlugin] Error processing calendar object: " . $e->getMessage());
        }
    }

    /**
     * Sanitize a parsed VCalendar object in-place.
     * Strips binary attachments and truncates oversized descriptions.
     *
     * Also called by ICSImportPlugin for direct DB writes that bypass
     * the HTTP layer (and thus don't trigger beforeCreateFile hooks).
     *
     * @return bool True if the VCalendar was modified.
     */
    public function sanitizeVCalendar(VCalendar $vcalendar)
    {
        $wasModified = false;

        foreach ($vcalendar->getComponents() as $component) {
            if ($component->name === 'VTIMEZONE') {
                continue;
            }

            // Strip inline binary attachments
            if ($this->stripBinaryAttachments && isset($component->ATTACH)) {
                $toRemove = [];
                foreach ($component->select('ATTACH') as $attach) {
                    $valueParam = $attach->offsetGet('VALUE');
                    $encodingParam = $attach->offsetGet('ENCODING');
                    if (
                        ($valueParam && strtoupper((string)$valueParam) === 'BINARY') ||
                        ($encodingParam && strtoupper((string)$encodingParam) === 'BASE64')
                    ) {
                        $toRemove[] = $attach;
                    }
                }
                foreach ($toRemove as $attach) {
                    $component->remove($attach);
                    $wasModified = true;
                }
            }

            // Truncate oversized long text properties (DESCRIPTION, X-ALT-DESC, COMMENT)
            if ($this->maxDescriptionBytes > 0) {
                foreach (self::LONG_TEXT_PROPERTIES as $prop) {
                    if (isset($component->{$prop})) {
                        $val = (string)$component->{$prop};
                        if (strlen($val) > $this->maxDescriptionBytes) {
                            $component->{$prop} = substr($val, 0, $this->maxDescriptionBytes) . '...';
                            $wasModified = true;
                        }
                    }
                }
            }

            // Truncate oversized short text properties (SUMMARY, LOCATION)
            foreach (self::SHORT_TEXT_PROPERTIES as $prop) {
                if (isset($component->{$prop})) {
                    $val = (string)$component->{$prop};
                    if (strlen($val) > self::MAX_SHORT_TEXT_BYTES) {
                        $component->{$prop} = substr($val, 0, self::MAX_SHORT_TEXT_BYTES) . '...';
                        $wasModified = true;
                    }
                }
            }
        }

        return $wasModified;
    }

    /**
     * Check that a VCalendar's serialized size is within the max resource limit.
     * Called by ICSImportPlugin for the direct DB write path.
     *
     * @throws InsufficientStorage if the serialized size exceeds the limit.
     */
    public function checkResourceSize(VCalendar $vcalendar)
    {
        if ($this->maxResourceSize <= 0) {
            return;
        }

        $size = strlen($vcalendar->serialize());
        if ($size > $this->maxResourceSize) {
            throw new InsufficientStorage(
                "Calendar object size ({$size} bytes) exceeds limit ({$this->maxResourceSize} bytes)"
            );
        }
    }

    public function getPluginInfo()
    {
        return [
            'name' => $this->getPluginName(),
            'description' => 'Sanitizes calendar data (strips binary attachments, truncates descriptions)',
        ];
    }
}
