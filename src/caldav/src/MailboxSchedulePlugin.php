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
 * A move of a meeting to a calendar with another identity changes the
 * organizer to this identity. The previous organizer becomes an attendee
 * that accepts. The attendees receive the update. The meeting replaces the
 * attendee copy that the new organizer had. An attendee copy cannot move to a
 * calendar with another identity.
 *
 * An event can be in a calendar that is not its identity, for example after
 * a move by an older version or by another client. Then the plugin uses all
 * the addresses of the principal, as SabreDAV does.
 */

namespace Calendars\SabreDav;

use Sabre\CalDAV\ICalendarObject;
use Sabre\CalDAV\Schedule\ISchedulingObject;
use Sabre\CalDAV\Schedule\Plugin;
use Sabre\DAV\Exception\Forbidden;
use Sabre\DAV\INode;
use Sabre\DAV\Server;
use Sabre\HTTP\RequestInterface;
use Sabre\HTTP\ResponseInterface;
use Sabre\Uri;
use Sabre\VObject\Component\VCalendar;
use Sabre\VObject\Reader;

class MailboxSchedulePlugin extends Plugin
{
    /**
     * Organizer change of the current MOVE.
     *
     * `copy` is the path of the event with the same UID that the new
     * organizer owns before the move, if any.
     *
     * @var array{destination: string, previous: string, organizer: string, uid: string, copy: ?string}|null
     */
    private ?array $transfer = null;

    public function initialize(Server $server)
    {
        parent::initialize($server);
        $server->on('beforeMethod:MOVE', [$this, 'beforeMoveMethod']);
        $server->on('beforeMove', [$this, 'beforeMove']);
        $server->on('afterMove', [$this, 'afterMove']);
    }

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
     * Lets a MOVE replace the attendee copy of the meeting at its destination.
     *
     * The new organizer can be an attendee of the meeting, with a copy at
     * the destination path. A client sends "Overwrite: F" to keep another
     * event that has this path. The copy is the same meeting, so the
     * request continues as a MOVE that overwrites.
     */
    public function beforeMoveMethod(RequestInterface $request): void
    {
        $header = $request->getHeader('Destination');
        if (!$header || 'F' !== strtoupper((string) $request->getHeader('Overwrite'))) {
            return;
        }

        $tree = $this->server->tree;
        $source = $request->getPath();
        $destination = $this->server->calculateUri($header);
        if (!$tree->nodeExists($source) || !$tree->nodeExists($destination)) {
            return;
        }

        try {
            $change = $this->getOrganizerChange($source, $destination);
        } catch (Forbidden) {
            return;
        }
        if ($change === null) {
            return;
        }

        if ($this->isAttendeeCopy($tree->getNodeForPath($destination), $change['uid'], $change['organizer'])) {
            $request->setHeader('Overwrite', 'T');
        }
    }

    /**
     * Prepares the organizer change of a MOVE.
     *
     * A meeting that moves to a calendar with another identity gets this
     * identity as organizer. This hook only records the change, and
     * afterMove applies it when the event is in its new calendar.
     *
     * A move between calendars with the same identity changes nothing. So
     * does the move of an event without attendees.
     *
     * @throws Forbidden when an attendee copy moves to a calendar with
     *                   another identity
     */
    public function beforeMove(string $source, string $destination): void
    {
        $change = $this->getOrganizerChange($source, $destination);
        if ($change === null) {
            return;
        }

        [$calendarPath] = Uri\split($destination);
        $this->transfer = [
            'destination' => $destination,
            'previous' => $change['previous'],
            'organizer' => $change['organizer'],
            'uid' => $change['uid'],
            'copy' => $this->findOwnedEvent($this->server->tree->getNodeForPath($calendarPath), $change['uid']),
        ];
    }

    /**
     * Returns the organizer change that a MOVE makes, or null.
     *
     * @return array{previous: string, organizer: string, uid: string}|null
     * @throws Forbidden when an attendee copy moves to a calendar with
     *                   another identity
     */
    private function getOrganizerChange(string $source, string $destination): ?array
    {
        $node = $this->server->tree->getNodeForPath($source);
        if (!$node instanceof ICalendarObject) {
            return null;
        }

        $event = Reader::read($node->get());
        $organizer = $this->getOrganizer($event);
        if (!$organizer || !$this->hasAttendees($event)) {
            $event->destroy();
            return null;
        }

        [$sourcePath] = Uri\split($source);
        [$destinationPath] = Uri\split($destination);
        $sourceCalendar = $this->server->tree->getNodeForPath($sourcePath);
        $addresses = array_map('strtolower', $this->getAddresses($sourceCalendar, [$event]));
        $uid = (string) $event->VEVENT->UID;
        $event->destroy();
        $identity = $this->getCalendarIdentity($this->server->tree->getNodeForPath($destinationPath));
        $identity = $identity ? strtolower($identity) : null;
        $sourceIdentity = $this->getCalendarIdentity($sourceCalendar);
        $sourceIdentity = $sourceIdentity ? strtolower($sourceIdentity) : null;

        if ($identity === $sourceIdentity) {
            return null;
        }

        if (!in_array($organizer, $addresses, true)) {
            throw new Forbidden('An attendee copy cannot move to a calendar with another identity.');
        }

        if (!$identity || $identity === $organizer) {
            return null;
        }

        return ['previous' => $organizer, 'organizer' => $identity, 'uid' => $uid];
    }

    /**
     * Applies the organizer change that beforeMove recorded.
     *
     * This hook writes the new organizer in the moved event, and removes
     * the attendee copy that the new organizer had. Then it sends the update
     * to the attendees, but not to the previous organizer. A request with
     * "Schedule-Reply: F" sends no message.
     */
    public function afterMove(string $source, string $destination): void
    {
        $transfer = $this->transfer;
        $this->transfer = null;
        if ($transfer === null || $transfer['destination'] !== $destination) {
            return;
        }
        ['previous' => $previous, 'organizer' => $organizer] = $transfer;

        $node = $this->server->tree->getNodeForPath($destination);
        $event = Reader::read($node->get());
        $this->changeOrganizer($event, $previous, $organizer);
        $etag = $node->put($event->serialize());
        if ($etag) {
            $this->server->httpResponse->setHeader('ETag', $etag);
        }
        $this->removeAttendeeCopy($transfer['copy'], $transfer['uid'], $organizer);

        if (!$this->scheduleReply($this->server->httpRequest)) {
            $event->destroy();
            return;
        }

        // The previous organizer moved the event away, so it gets no update.
        $broker = $this->createITipBroker();
        foreach ($broker->parseEvent($event, [$organizer]) as $message) {
            if ($message->recipient !== $previous) {
                $this->deliver($message);
            }
        }
        $event->destroy();
    }

    /**
     * Returns the path of the event with this UID in the calendars that
     * the identity of the calendar owns, or null.
     */
    private function findOwnedEvent(INode $calendar, string $uid): ?string
    {
        $principal = $calendar instanceof MailboxSharedCalendar
            ? 'principals/mailboxes/' . $calendar->getMailboxEmail()
            : $calendar->getOwner();
        $homePath = 'calendars/' . substr($principal, strlen('principals/'));
        $path = $this->server->tree->getNodeForPath($homePath)->getCalendarObjectByUID($uid);
        return $path ? $homePath . '/' . $path : null;
    }

    /**
     * Removes the attendee copy of the meeting that the new organizer had.
     *
     * A MOVE that overwrites puts the meeting at the path of the copy.
     * Another request can also change the event at this path during the
     * move. Thus the event at this path is examined again.
     */
    private function removeAttendeeCopy(?string $path, string $uid, string $organizer): void
    {
        if ($path === null || !$this->server->tree->nodeExists($path)) {
            return;
        }

        if ($this->isAttendeeCopy($this->server->tree->getNodeForPath($path), $uid, $organizer)) {
            $this->server->tree->delete($path);
        }
    }

    /**
     * Tells if the node is an event with this UID that another address
     * than the organizer organizes.
     */
    private function isAttendeeCopy(INode $node, string $uid, string $organizer): bool
    {
        if (!$node instanceof ICalendarObject) {
            return false;
        }

        $event = Reader::read($node->get());
        $isCopy = (string) $event->VEVENT?->UID === $uid && $this->getOrganizer($event) !== $organizer;
        $event->destroy();
        return $isCopy;
    }

    /**
     * Makes the address the organizer of all the components of the event.
     *
     * All the components get the new organizer and a new SEQUENCE. Only the
     * components with attendees get the previous organizer as an attendee
     * that accepts. The new organizer is no longer an attendee.
     */
    private function changeOrganizer(VCalendar $event, string $previous, string $organizer): void
    {
        // SabreDAV takes the SEQUENCE of a CANCEL from the master. All the
        // components get the same new SEQUENCE, above all the old ones.
        $sequence = 0;
        foreach ($event->select('VEVENT') as $component) {
            if (isset($component->SEQUENCE)) {
                $sequence = max($sequence, (int) $component->SEQUENCE->getValue());
            }
        }

        foreach ($event->select('VEVENT') as $component) {
            $component->SEQUENCE = $sequence + 1;
            $component->remove('ORGANIZER');
            $component->add('ORGANIZER', $organizer);
            if (!isset($component->ATTENDEE)) {
                continue;
            }
            foreach ($component->select('ATTENDEE') as $attendee) {
                $address = strtolower($attendee->getNormalizedValue());
                if ($address === $organizer || $address === $previous) {
                    $component->remove($attendee);
                }
            }
            $component->add('ATTENDEE', $previous, ['PARTSTAT' => 'ACCEPTED']);
        }
    }

    /**
     * Returns the organizer of the event. An override can come before the
     * master, so the plugin reads all the components.
     */
    private function getOrganizer(VCalendar $event): ?string
    {
        foreach ($event->select('VEVENT') as $component) {
            if (isset($component->ORGANIZER)) {
                return strtolower($component->ORGANIZER->getNormalizedValue());
            }
        }
        return null;
    }

    /** Tells if a component of the event has attendees. */
    private function hasAttendees(VCalendar $event): bool
    {
        foreach ($event->select('VEVENT') as $component) {
            if (isset($component->ATTENDEE)) {
                return true;
            }
        }
        return false;
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
