<?php

namespace Calendars\SabreDav;

use Sabre\VObject\Component;
use Sabre\VObject\Component\VCalendar;
use Sabre\VObject\Component\VEvent;
use Sabre\VObject\Property;
use Sabre\VObject\Recur\EventIterator;

/**
 * Compares a new version of an event with the stored version.
 *
 * SabreDAV marks each new entry of a recurring event as a significant
 * change for all the attendees. A copy of a regular date with other
 * answers changes nothing for them.
 */
final class AnswerOnlyChange
{
    private const WRITE_PROPERTIES = ['CREATED', 'DTSTAMP', 'LAST-MODIFIED', 'SEQUENCE'];

    private const TIME_PROPERTIES = ['DTEND', 'DTSTART', 'DURATION', 'RECURRENCE-ID'];

    private const ANSWER_PARAMETERS = ['PARTSTAT', 'RSVP', 'SCHEDULE-STATUS'];

    private const WEEKDAYS = ['MO', 'TU', 'WE', 'TH', 'FR', 'SA', 'SU'];

    private const COMMON_RRULE_PARTS = ['FREQ', 'COUNT', 'INTERVAL', 'UNTIL', 'WKST'];

    /**
     * The other RRULE parts that EventIterator expands correctly, for each
     * frequency.
     */
    private const RRULE_PARTS = [
        'DAILY' => [],
        'WEEKLY' => ['BYDAY'],
        'MONTHLY' => ['BYDAY', 'BYMONTHDAY'],
        'YEARLY' => ['BYDAY', 'BYMONTH', 'BYMONTHDAY'],
    ];

    /**
     * Tell if the write only records answers.
     *
     * The write adds at least one copy of a regular date, and keeps all
     * the stored entries. All other changes are in the answers of the
     * attendees or in the write properties, such as DTSTAMP or SEQUENCE.
     * The answers do not have to change.
     */
    public function isAnswerOnly(VCalendar $vCal, VCalendar $stored): bool
    {
        if (!isset($stored->VEVENT->ORGANIZER)
            || $this->hasRange($vCal)
            || $this->timezones($vCal) !== $this->timezones($stored)) {
            return false;
        }

        $storedEntries = [];
        foreach ($stored->VEVENT as $vevent) {
            $storedEntries[$this->recurrenceId($vevent)] = $vevent;
        }
        // Without a master, EventIterator takes the first entry as the
        // master, so the regular dates are not known.
        if (!isset($storedEntries['master'])) {
            return false;
        }
        if (!$this->isPlainSeries($storedEntries['master'])) {
            return false;
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
            } elseif ($this->matchesRegularDate($vevent, $stored, $storedEntries['master'])) {
                $added = true;
            } else {
                return false;
            }
        }
        return $added && $kept === count($storedEntries);
    }

    /**
     * Tell if the master only uses the supported recurrence properties:
     * one RRULE with supported parts, and EXDATE lines.
     *
     * EventIterator does not handle the other combinations well. For
     * example, it ignores EXRULE, reads RDATE in the timezone of DTSTART,
     * and ignores BYMONTH in a daily rule. Other series use the usual
     * scheduling rules.
     *
     * @see https://github.com/sabre-io/vobject/issues/819 (RDATE)
     */
    private function isPlainSeries(VEvent $master): bool
    {
        $rules = $master->select('RRULE');
        if (1 !== count($rules) || isset($master->RDATE) || isset($master->EXRULE)) {
            return false;
        }

        $parts = reset($rules)->getParts();
        $supported = self::RRULE_PARTS[$parts['FREQ'] ?? ''] ?? null;
        if (null === $supported
            || array_diff(array_keys($parts), self::COMMON_RRULE_PARTS, $supported)) {
            return false;
        }
        if ('YEARLY' !== $parts['FREQ']) {
            return true;
        }
        // In a yearly rule, EventIterator needs BYMONTH together with
        // BYDAY or BYMONTHDAY. Each of them alone gives wrong dates.
        return isset($parts['BYMONTH']) === (isset($parts['BYDAY']) || isset($parts['BYMONTHDAY']));
    }

    /**
     * Tell if an entry has a RANGE, such as RANGE=THISANDFUTURE.
     *
     * Such an entry also changes the later dates. EventIterator does not
     * support it, so the regular dates are not known. A stored entry with
     * a RANGE is also in the new event, or the comparison fails because
     * the new event drops it.
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
     * Tell if a new entry is a copy of its date in the stored series.
     *
     * The times can have another form with the same value. The answers of
     * the attendees and the write properties can differ.
     */
    private function matchesRegularDate(VEvent $vevent, VCalendar $stored, VEvent $master): bool
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
        if (!$this->fitsRule($date, $master)) {
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
            && $this->endOf($vevent) == $this->regularEnd($regular, $master)
            && $this->endIsFloating($vevent) === $this->endIsFloating($regular)
            && $this->answerless($vevent, $skipped) === $this->answerless($regular, $skipped);
    }

    /**
     * Give the end of a regular date of the series.
     *
     * With DTEND, all the dates have the exact length of the master, in
     * seconds. EventIterator adds this length to the clock time, so its
     * DTEND is one hour wrong across a change to or from summer time.
     *
     * @see https://github.com/sabre-io/vobject/issues/818
     */
    private function regularEnd(VEvent $regular, VEvent $master): \DateTimeImmutable
    {
        if (!isset($master->DTEND)) {
            return $this->endOf($regular);
        }
        $length = $master->DTEND->getDateTime()->getTimestamp()
            - $master->DTSTART->getDateTime()->getTimestamp();
        $start = $regular->DTSTART->getDateTime();
        return $start->setTimestamp($start->getTimestamp() + $length);
    }

    /**
     * Tell if the day of a date can be in the RRULE of the master.
     *
     * EventIterator can give dates outside the rule. For example, a
     * monthly rule with BYMONTHDAY can give the UNTIL date. This check
     * rejects the days that do not fit the BY parts or the INTERVAL.
     */
    private function fitsRule(\DateTimeImmutable $date, VEvent $master): bool
    {
        $parts = $master->RRULE->getParts();
        $start = $master->DTSTART->getDateTime();
        $date = $date->setTimezone($start->getTimezone());
        $byMonth = array_map('intval', (array) ($parts['BYMONTH'] ?? []));
        $byMonthDay = array_map('intval', (array) ($parts['BYMONTHDAY'] ?? []));
        $byDay = (array) ($parts['BYDAY'] ?? []);
        // Without these parts, the rule repeats the day of DTSTART.
        if ('WEEKLY' === $parts['FREQ'] && !$byDay) {
            $byDay = [self::WEEKDAYS[(int) $start->format('N') - 1]];
        }
        if ('DAILY' !== $parts['FREQ'] && 'WEEKLY' !== $parts['FREQ'] && !$byDay && !$byMonthDay) {
            $byMonthDay = [(int) $start->format('j')];
        }
        if ('YEARLY' === $parts['FREQ'] && !$byMonth) {
            $byMonth = [(int) $start->format('n')];
        }

        $day = (int) $date->format('j');
        $monthLength = (int) $date->format('t');
        if ($byMonth && !in_array((int) $date->format('n'), $byMonth, true)) {
            return false;
        }
        if ($byMonthDay && !in_array($day, array_map(
            fn (int $monthDay): int => $monthDay > 0 ? $monthDay : $monthLength + 1 + $monthDay,
            $byMonthDay
        ), true)) {
            return false;
        }
        $inMonth = 'MONTHLY' === $parts['FREQ'] || 'YEARLY' === $parts['FREQ'];
        if ($byDay && !array_filter($byDay, fn (string $entry): bool => $this->fitsByDay($date, $entry, $inMonth))) {
            return false;
        }

        $days = $this->dayNumber($date) - $this->dayNumber($start);
        $weekStart = array_search($parts['WKST'] ?? 'MO', self::WEEKDAYS, true) + 1;
        $steps = match ($parts['FREQ']) {
            'DAILY' => $days,
            'WEEKLY' => intdiv($days + ((int) $start->format('N') - $weekStart + 7) % 7, 7),
            'MONTHLY' => 12 * ((int) $date->format('Y') - (int) $start->format('Y'))
                + (int) $date->format('n') - (int) $start->format('n'),
            'YEARLY' => (int) $date->format('Y') - (int) $start->format('Y'),
        };
        return 0 === $steps % (int) ($parts['INTERVAL'] ?? 1);
    }

    /**
     * Tell if a date fits one BYDAY entry, such as "TU", "2TU" or "-1FR".
     * A number counts the weeks of the month. A weekly rule ignores it.
     */
    private function fitsByDay(\DateTimeImmutable $date, string $entry, bool $inMonth): bool
    {
        if (!preg_match('/^([+-]?\d*)([A-Z]{2})$/', strtoupper($entry), $match)
            || self::WEEKDAYS[(int) $date->format('N') - 1] !== $match[2]) {
            return false;
        }
        $week = $inMonth ? (int) $match[1] : 0;
        $day = (int) $date->format('j');
        return match (true) {
            $week > 0 => intdiv($day - 1, 7) + 1 === $week,
            $week < 0 => intdiv((int) $date->format('t') - $day, 7) + 1 === -$week,
            default => true,
        };
    }

    private function dayNumber(\DateTimeImmutable $date): int
    {
        $day = new \DateTimeImmutable($date->format('Y-m-d'), new \DateTimeZone('UTC'));
        return intdiv($day->getTimestamp(), 86400);
    }

    private function endIsFloating(VEvent $vevent): bool
    {
        return isset($vevent->DTEND) ? $vevent->DTEND->isFloating() : $vevent->DTSTART->isFloating();
    }

    /**
     * Give the nominal end of a date.
     *
     * The DURATION is added to the start of this date. A day thus stays a
     * day across a change to summer time.
     */
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
     * @param string[] $skipped Names of the direct children to leave out.
     *                          Nested components keep all their properties.
     * @return string[] Sorted strings for the comparison. They are not
     *                  valid iCalendar. The parameters are sorted, and the
     *                  answers of the attendees are removed. Nested
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

    private function normalizeEmail(string $address): string
    {
        return strtolower(preg_replace('/^mailto:/i', '', trim($address)));
    }
}
