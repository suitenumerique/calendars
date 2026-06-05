<?php
/**
 * AuditCalDAVBackend - Extends SabreDAV's PDO backend with audit columns.
 *
 * Tracks channel_id, created_by, modified_by, created_at, and modified_by_at
 * on calendarobjects. Context is injected by AuditContextPlugin before each
 * write via setCurrentPrincipal() and setCurrentChannelId().
 *
 * Overrides createCalendarObject/updateCalendarObject to include audit
 * columns directly in the INSERT/UPDATE statement (single query).
 */

namespace Calendars\SabreDav;

use Sabre\CalDAV\Backend\PDO;

class AuditCalDAVBackend extends PDO
{
    /** @var string|null Authenticated principal email */
    private $currentPrincipal = null;

    /** @var string|null Channel UUID (when request comes via channel token) */
    private $currentChannelId = null;

    /**
     * Set the authenticated principal email for the current request.
     */
    public function setCurrentPrincipal(?string $email): void
    {
        $this->currentPrincipal = $email;
    }

    /**
     * Set the channel ID for the current request.
     */
    public function setCurrentChannelId(?string $channelId): void
    {
        $this->currentChannelId = $channelId;
    }

    /**
     * Creates a new calendar object with audit columns.
     *
     * Reproduces the parent logic with channel_id, created_by, modified_by,
     * created_at, and modified_by_at included in the INSERT.
     *
     * @param mixed $calendarId
     * @param string $objectUri
     * @param string $calendarData
     * @return string|null
     */
    public function createCalendarObject($calendarId, $objectUri, $calendarData)
    {
        if (!is_array($calendarId)) {
            throw new \InvalidArgumentException(
                'The value passed to $calendarId is expected to be an array'
                . ' with a calendarId and an instanceId'
            );
        }
        list($calendarId, $instanceId) = $calendarId;

        $extraData = $this->getDenormalizedData($calendarData);
        $now = time();

        $stmt = $this->pdo->prepare(
            'INSERT INTO ' . $this->calendarObjectTableName
            . ' (calendarid, uri, calendardata, lastmodified, etag, size,'
            . ' componenttype, firstoccurence, lastoccurence, uid,'
            . ' channel_id, created_by, modified_by, created_at, modified_by_at)'
            . ' VALUES'
            . ' (:calendarid, :uri, :calendardata, :lastmodified, :etag, :size,'
            . ' :componenttype, :firstoccurence, :lastoccurence, :uid,'
            . ' :channel_id, :created_by, :modified_by, :created_at, :modified_by_at)'
        );
        $stmt->bindParam('calendarid', $calendarId, \PDO::PARAM_INT);
        $stmt->bindParam('uri', $objectUri, \PDO::PARAM_STR);
        $stmt->bindParam('calendardata', $calendarData, \PDO::PARAM_LOB);
        $stmt->bindParam('lastmodified', $now, \PDO::PARAM_INT);
        $stmt->bindParam('etag', $extraData['etag'], \PDO::PARAM_STR);
        $stmt->bindParam('size', $extraData['size'], \PDO::PARAM_INT);
        $stmt->bindParam('componenttype', $extraData['componentType'], \PDO::PARAM_STR);
        $stmt->bindParam('firstoccurence', $extraData['firstOccurence'], \PDO::PARAM_INT);
        $stmt->bindParam('lastoccurence', $extraData['lastOccurence'], \PDO::PARAM_INT);
        $stmt->bindParam('uid', $extraData['uid'], \PDO::PARAM_STR);
        $stmt->bindParam('channel_id', $this->currentChannelId, \PDO::PARAM_STR);
        $stmt->bindParam('created_by', $this->currentPrincipal, \PDO::PARAM_STR);
        $stmt->bindParam('modified_by', $this->currentPrincipal, \PDO::PARAM_STR);
        $stmt->bindParam('created_at', $now, \PDO::PARAM_INT);
        $stmt->bindParam('modified_by_at', $now, \PDO::PARAM_INT);
        $stmt->execute();

        $this->addChange($calendarId, $objectUri, 1);

        return '"' . $extraData['etag'] . '"';
    }

    /**
     * Updates an existing calendar object with audit columns.
     *
     * Reproduces the parent logic with modified_by, modified_by_at, and
     * channel_id (via COALESCE to preserve original) in the UPDATE.
     *
     * @param mixed $calendarId
     * @param string $objectUri
     * @param string $calendarData
     * @return string|null
     */
    public function updateCalendarObject($calendarId, $objectUri, $calendarData)
    {
        if (!is_array($calendarId)) {
            throw new \InvalidArgumentException(
                'The value passed to $calendarId is expected to be an array'
                . ' with a calendarId and an instanceId'
            );
        }
        list($calendarId, $instanceId) = $calendarId;

        $extraData = $this->getDenormalizedData($calendarData);
        $now = time();

        $stmt = $this->pdo->prepare(
            'UPDATE ' . $this->calendarObjectTableName . ' SET'
            . ' calendardata = :calendardata, lastmodified = :lastmodified,'
            . ' etag = :etag, size = :size, componenttype = :componenttype,'
            . ' firstoccurence = :firstoccurence, lastoccurence = :lastoccurence,'
            . ' uid = :uid,'
            . ' modified_by = :modified_by, modified_by_at = :modified_by_at,'
            . ' channel_id = COALESCE(:channel_id, channel_id)'
            . ' WHERE calendarid = :calendarid AND uri = :uri'
        );
        $stmt->bindParam('calendardata', $calendarData, \PDO::PARAM_LOB);
        $stmt->bindParam('lastmodified', $now, \PDO::PARAM_INT);
        $stmt->bindParam('etag', $extraData['etag'], \PDO::PARAM_STR);
        $stmt->bindParam('size', $extraData['size'], \PDO::PARAM_INT);
        $stmt->bindParam('componenttype', $extraData['componentType'], \PDO::PARAM_STR);
        $stmt->bindParam('firstoccurence', $extraData['firstOccurence'], \PDO::PARAM_INT);
        $stmt->bindParam('lastoccurence', $extraData['lastOccurence'], \PDO::PARAM_INT);
        $stmt->bindParam('uid', $extraData['uid'], \PDO::PARAM_STR);
        $stmt->bindParam('modified_by', $this->currentPrincipal, \PDO::PARAM_STR);
        $stmt->bindParam('modified_by_at', $now, \PDO::PARAM_INT);
        $stmt->bindParam('channel_id', $this->currentChannelId, \PDO::PARAM_STR);
        $stmt->bindParam('calendarid', $calendarId, \PDO::PARAM_INT);
        $stmt->bindParam('uri', $objectUri, \PDO::PARAM_STR);
        $stmt->execute();

        $this->addChange($calendarId, $objectUri, 2);

        return '"' . $extraData['etag'] . '"';
    }

    /**
     * The ``calendarobjects.calendardata`` column is a PostgreSQL ``bytea``
     * (LOB), so PDO returns it as a stream resource on read. SabreDAV and
     * vobject's ITip\\Broker do ``is_string()`` checks downstream and
     * silently treat non-strings as "no data" — the most visible symptom is
     * that deleting an event with attendees produces zero CANCEL iTIP
     * messages because ``parseEvent`` bails when ``$node->get()`` is a
     * stream. We materialise the stream once at the backend boundary so
     * every caller (CalendarObject::get, REPORT calendar-multiget, the
     * scheduling plugin, the internal API, etc.) sees a string.
     */
    private static function materializeCalendarData(?array $row): ?array
    {
        if ($row === null) {
            return $row;
        }
        if (isset($row['calendardata']) && is_resource($row['calendardata'])) {
            $contents = stream_get_contents($row['calendardata']);
            // stream_get_contents() returns false on read failure; coerce to
            // null so downstream `is_string()` checks treat the row as
            // "no data" instead of `false` (a bool would otherwise sneak
            // through and corrupt iTIP/REPORT serialization).
            $row['calendardata'] = $contents === false ? null : $contents;
        }
        return $row;
    }

    public function getCalendarObject($calendarId, $objectUri)
    {
        return self::materializeCalendarData(parent::getCalendarObject($calendarId, $objectUri));
    }

    public function getMultipleCalendarObjects($calendarId, array $uris)
    {
        return array_map(
            [self::class, 'materializeCalendarData'],
            parent::getMultipleCalendarObjects($calendarId, $uris)
        );
    }
}
