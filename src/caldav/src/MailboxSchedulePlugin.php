<?php
/**
 * Scheduling with one identity per calendar.
 *
 * SabreDAV takes the scheduling addresses from the principal of the
 * calendar instance. MailboxPlugin adds to them all the mailboxes that the
 * user can write to. When the organizer is one of these mailboxes, SabreDAV
 * processes the reply of an attendee as a change by the organizer.
 *
 * This plugin uses the identity of the calendar when the event contains it:
 *  - a mailbox calendar speaks for its mailbox;
 *  - another calendar speaks for the email of its principal.
 *
 * An event can be in a calendar that is not its identity, for example after
 * a move. Then the plugin uses all the addresses of the principal, as
 * SabreDAV does.
 */

namespace Calendars\SabreDav;

use Sabre\CalDAV\ICalendarObject;
use Sabre\CalDAV\Schedule\ISchedulingObject;
use Sabre\CalDAV\Schedule\Plugin;
use Sabre\DAV\INode;
use Sabre\HTTP\RequestInterface;
use Sabre\HTTP\ResponseInterface;
use Sabre\Uri;
use Sabre\VObject\Component\VCalendar;
use Sabre\VObject\Reader;

class MailboxSchedulePlugin extends Plugin
{
    public function calendarObjectChange(RequestInterface $request, ResponseInterface $response, VCalendar $vCal, $calendarPath, &$modified, $isNew)
    {
        if (!$this->scheduleReply($this->server->httpRequest)) {
            return;
        }

        $old = null;
        if (!$isNew) {
            $node = $this->server->tree->getNodeForPath($request->getPath());
            $old = Reader::read($node->get());
        }

        $addresses = $this->getAddresses(
            $this->server->tree->getNodeForPath($calendarPath),
            array_filter([$vCal, $old])
        );

        $this->processICalendarChange($old, $vCal, $addresses, [], $modified);

        $old?->destroy();
    }

    public function beforeUnbind($path)
    {
        // A MOVE is not a deletion of the event.
        if ('MOVE' === $this->server->httpRequest->getMethod()) {
            return;
        }

        $node = $this->server->tree->getNodeForPath($path);
        if (!$node instanceof ICalendarObject || $node instanceof ISchedulingObject) {
            return;
        }

        if (!$this->scheduleReply($this->server->httpRequest)) {
            return;
        }

        $event = Reader::read($node->get());
        [$calendarPath] = Uri\split($path);
        $addresses = $this->getAddresses(
            $this->server->tree->getNodeForPath($calendarPath),
            [$event]
        );

        $broker = $this->createITipBroker();
        foreach ($broker->parseEvent(null, $addresses, $event) as $message) {
            $this->deliver($message);
        }
        $event->destroy();
    }

    /**
     * Returns the addresses that the user speaks for in the calendar.
     *
     * @param VCalendar[] $events The event, and its stored version if any.
     * @return string[]
     */
    private function getAddresses(INode $calendar, array $events): array
    {
        $identity = $this->getCalendarIdentity($calendar);
        if ($identity && $this->containsAddress($events, $identity)) {
            return [$identity];
        }
        return $this->getAddressesForPrincipal($calendar->getOwner());
    }

    private function getCalendarIdentity(INode $calendar): ?string
    {
        if ($calendar instanceof MailboxSharedCalendar) {
            $email = $calendar->getMailboxEmail();
        } else {
            $prop = '{http://sabredav.org/ns}email-address';
            $email = $this->server->getProperties($calendar->getOwner(), [$prop])[$prop] ?? null;
        }
        return $email ? 'mailto:' . strtolower($email) : null;
    }

    /**
     * Tells if the address is the organizer or an attendee of an event.
     *
     * @param VCalendar[] $events
     */
    private function containsAddress(array $events, string $address): bool
    {
        $address = strtolower($address);
        foreach ($events as $event) {
            foreach ($event->getComponents() as $component) {
                $properties = [...$component->select('ORGANIZER'), ...$component->select('ATTENDEE')];
                foreach ($properties as $property) {
                    if (strtolower($property->getNormalizedValue()) === $address) {
                        return true;
                    }
                }
            }
        }
        return false;
    }
}
