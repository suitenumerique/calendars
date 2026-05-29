/**
 * @jest-environment jsdom
 *
 * Tests for CalDAV Helper functions. Uses jsdom because the imported
 * `parseDavErrorMessage` (from `DavClient`) parses via native `DOMParser`.
 */
import {
  escapeXml,
  XML_NS,
  xmlProp,
  buildCalendarPropsXml,
  buildMkCalendarXml,
  buildProppatchXml,
  buildCalendarQueryXml,
  parseSharePrivilege,
  buildShareRequestXml,
  buildUnshareRequestXml,
  parseCalendarComponents,
  parseCalendarOrder,
  getCalendarUrlFromEventUrl,
} from '../caldav-helpers'
import { parseDavErrorMessage } from '@/features/calendar/utils/DavClient'

describe('caldav-helpers', () => {
  // ============================================================================
  // XML Helpers
  // ============================================================================
  describe('XML Helpers', () => {
    describe('escapeXml', () => {
      it('escapes ampersand', () => {
        expect(escapeXml('Tom & Jerry')).toBe('Tom &amp; Jerry')
      })

      it('escapes less than', () => {
        expect(escapeXml('1 < 2')).toBe('1 &lt; 2')
      })

      it('escapes greater than', () => {
        expect(escapeXml('2 > 1')).toBe('2 &gt; 1')
      })

      it('escapes double quotes', () => {
        expect(escapeXml('He said "hello"')).toBe('He said &quot;hello&quot;')
      })

      it('escapes single quotes', () => {
        expect(escapeXml("It's fine")).toBe('It&apos;s fine')
      })

      it('escapes multiple characters', () => {
        expect(escapeXml('<tag attr="val">text & more</tag>')).toBe(
          '&lt;tag attr=&quot;val&quot;&gt;text &amp; more&lt;/tag&gt;'
        )
      })
    })

    describe('XML_NS', () => {
      it('contains correct namespaces', () => {
        expect(XML_NS.DAV).toBe('xmlns:D="DAV:"')
        expect(XML_NS.CALDAV).toBe('xmlns:C="urn:ietf:params:xml:ns:caldav"')
        expect(XML_NS.APPLE).toBe('xmlns:A="http://apple.com/ns/ical/"')
        expect(XML_NS.CS).toBe('xmlns:CS="http://calendarserver.org/ns/"')
      })
    })

    describe('xmlProp', () => {
      it('creates XML element with namespace', () => {
        expect(xmlProp('D', 'displayname', 'My Calendar')).toBe(
          '<D:displayname>My Calendar</D:displayname>'
        )
      })

      it('escapes value content', () => {
        expect(xmlProp('D', 'displayname', 'Tom & Jerry')).toBe(
          '<D:displayname>Tom &amp; Jerry</D:displayname>'
        )
      })
    })

  })

  // ============================================================================
  // Calendar Property Builders
  // ============================================================================
  describe('Calendar Property Builders', () => {
    describe('buildCalendarPropsXml', () => {
      it('builds displayName property', () => {
        const result = buildCalendarPropsXml({ displayName: 'My Calendar' })
        expect(result).toContain('<D:displayname>My Calendar</D:displayname>')
      })

      it('builds description property', () => {
        const result = buildCalendarPropsXml({ description: 'A test calendar' })
        expect(result).toContain('<C:calendar-description>A test calendar</C:calendar-description>')
      })

      it('builds color property', () => {
        const result = buildCalendarPropsXml({ color: '#ff0000' })
        expect(result).toContain('<A:calendar-color>#ff0000</A:calendar-color>')
      })

      it('builds components property', () => {
        const result = buildCalendarPropsXml({ components: ['VEVENT', 'VTODO'] })
        expect(result.join('')).toContain('supported-calendar-component-set')
        expect(result.join('')).toContain('<C:comp name="VEVENT"/>')
        expect(result.join('')).toContain('<C:comp name="VTODO"/>')
      })

      it('builds multiple properties', () => {
        const result = buildCalendarPropsXml({
          displayName: 'Work',
          description: 'Work calendar',
          color: '#0000ff',
        })
        expect(result).toHaveLength(3)
      })
    })

    describe('buildMkCalendarXml', () => {
      it('creates valid MKCALENDAR XML', () => {
        const result = buildMkCalendarXml({ displayName: 'New Calendar' })
        expect(result).toContain('<?xml version="1.0"')
        expect(result).toContain('<C:mkcalendar')
        expect(result).toContain('xmlns:D="DAV:"')
        expect(result).toContain('xmlns:C="urn:ietf:params:xml:ns:caldav"')
        expect(result).toContain('<D:displayname>New Calendar</D:displayname>')
        expect(result).toContain('</C:mkcalendar>')
      })

      it('emits calendar-timezone when timezone is provided', () => {
        // Calendar-timezone carries the VTIMEZONE block that SabreDAV
        // uses to render floating events for this calendar.
        const result = buildMkCalendarXml({
          displayName: 'TZ Calendar',
          timezone: 'BEGIN:VTIMEZONE\nTZID:Europe/Paris\nEND:VTIMEZONE',
        })
        expect(result).toContain('<C:calendar-timezone>')
        expect(result).toContain('TZID:Europe/Paris')
      })

      it('emits calendar-color when color is provided', () => {
        const result = buildMkCalendarXml({
          displayName: 'C',
          color: '#ff0000',
        })
        expect(result).toContain('<A:calendar-color>#ff0000</A:calendar-color>')
      })

      it('escapes displayName to prevent XML/XSS injection', () => {
        // Verified end-to-end in the browser: a calendar named
        // `<script>alert(1)</script><img src=x onerror=alert(2)>` renders as
        // plain text in the sidebar (React auto-escape) AND is stored by
        // SabreDAV with the angle brackets entity-encoded. The key
        // invariant: every `<` and `>` is escaped, so no opening tag of
        // any element survives in the body.
        const evil = `<script>alert('xss')</script>"><img src=x onerror=alert(2)>`
        const result = buildMkCalendarXml({ displayName: evil })
        expect(result).toContain(
          '<D:displayname>&lt;script&gt;alert(&apos;xss&apos;)&lt;/script&gt;&quot;&gt;&lt;img src=x onerror=alert(2)&gt;</D:displayname>',
        )
        // No raw `<script>` or `<img …>` start tag survives the escaping.
        expect(result).not.toContain('<script>')
        expect(result).not.toContain('<img ')
        expect(result).not.toContain('<img>')
      })
    })

    describe('buildProppatchXml', () => {
      it('creates valid PROPPATCH XML', () => {
        const result = buildProppatchXml({ displayName: 'Updated Name' })
        expect(result).toContain('<?xml version="1.0"')
        expect(result).toContain('<D:propertyupdate')
        expect(result).toContain('<D:set>')
        expect(result).toContain('<D:displayname>Updated Name</D:displayname>')
      })

      it('emits schedule-calendar-transp transparent when includeInAvailability is false', () => {
        const result = buildProppatchXml({ scheduleTransp: 'transparent' })
        expect(result).toContain('<C:schedule-calendar-transp>')
        expect(result).toContain('<C:transparent/>')
      })

      it('emits schedule-calendar-transp opaque when includeInAvailability is true', () => {
        const result = buildProppatchXml({ scheduleTransp: 'opaque' })
        expect(result).toContain('<C:schedule-calendar-transp>')
        expect(result).toContain('<C:opaque/>')
      })
    })

    describe('buildCalendarQueryXml', () => {
      it('builds a bare calendar-query with no filter when no timeRange given', () => {
        const result = buildCalendarQueryXml()
        expect(result).toContain('<?xml version="1.0"')
        expect(result).toContain('<C:calendar-query')
        expect(result).toContain('xmlns:D="DAV:"')
        expect(result).toContain('xmlns:C="urn:ietf:params:xml:ns:caldav"')
        expect(result).toContain('<D:getetag/>')
        expect(result).toContain('<C:calendar-data/>')
        expect(result).toContain('<C:comp-filter name="VCALENDAR"')
        expect(result).toContain('<C:comp-filter name="VEVENT"')
        expect(result).not.toContain('<C:time-range')
        expect(result).not.toContain('<C:expand')
      })

      it('includes a time-range filter when timeRange is provided', () => {
        const result = buildCalendarQueryXml({
          timeRange: {
            start: '2026-05-01T00:00:00Z',
            end: '2026-06-01T00:00:00Z',
          },
        })
        // RFC 4791 §9.6: time-range start/end use the compact
        // `YYYYMMDDTHHMMSSZ` UTC format.
        expect(result).toContain('<C:time-range')
        expect(result).toContain('start="20260501T000000Z"')
        expect(result).toContain('end="20260601T000000Z"')
      })

      it('accepts Date objects for timeRange bounds', () => {
        const result = buildCalendarQueryXml({
          timeRange: {
            start: new Date(Date.UTC(2026, 4, 1, 12, 30, 45)),
            end: new Date(Date.UTC(2026, 5, 1, 0, 0, 0)),
          },
        })
        expect(result).toContain('start="20260501T123045Z"')
        expect(result).toContain('end="20260601T000000Z"')
      })

      it('emits <C:expand> inside <C:calendar-data> when expand=true with timeRange', () => {
        // expand=true asks SabreDAV to materialise individual occurrences
        // of recurring events for the given window, instead of returning
        // the master VEVENT with its RRULE.
        const result = buildCalendarQueryXml({
          timeRange: {
            start: '2026-05-01T00:00:00Z',
            end: '2026-06-01T00:00:00Z',
          },
          expand: true,
        })
        expect(result).toContain('<C:calendar-data>')
        expect(result).toContain('<C:expand')
        expect(result).toContain('start="20260501T000000Z"')
        expect(result).toContain('end="20260601T000000Z"')
        expect(result).toContain('</C:calendar-data>')
      })

      it('does not emit <C:expand> when expand=true but no timeRange', () => {
        // RFC 4791 §9.6.5: expand requires a time-range bound.
        const result = buildCalendarQueryXml({ expand: true })
        expect(result).not.toContain('<C:expand')
        expect(result).toContain('<C:calendar-data/>')
      })
    })
  })

  // ============================================================================
  // Sharing XML Builders
  // ============================================================================
  describe('Sharing XML Builders', () => {
    describe('parseSharePrivilege', () => {
      it('returns read-write when present and no override', () => {
        expect(parseSharePrivilege({ 'read-write': true })).toBe('read-write')
      })

      it('returns read-write when camelCase key from tsdav (readWrite)', () => {
        expect(parseSharePrivilege({ readWrite: true })).toBe('read-write')
      })

      it('returns read as default', () => {
        expect(parseSharePrivilege({})).toBe('read')
        expect(parseSharePrivilege(null)).toBe('read')
      })

      it('LS:share-access "freebusy" wins over CS:read', () => {
        expect(parseSharePrivilege({}, 'freebusy')).toBe('freebusy')
      })

      it('LS:share-access "admin" wins over CS:read-write', () => {
        // Admin shares are stored as ACCESS_READWRITE upstream + an
        // LS:share-access "admin" override; the override must take
        // precedence so the UI shows "admin" instead of "read-write".
        expect(parseSharePrivilege({ 'read-write': true }, 'admin')).toBe('admin')
        expect(parseSharePrivilege({ readWrite: true }, 'admin')).toBe('admin')
      })

      it('returns read when no override and access is empty', () => {
        expect(parseSharePrivilege({}, 'something-else')).toBe('read')
        expect(parseSharePrivilege({}, undefined)).toBe('read')
      })
    })

    describe('buildShareRequestXml', () => {
      it('builds share request with multiple sharees', () => {
        const result = buildShareRequestXml([
          { href: 'mailto:user1@example.com', privilege: 'read' },
          { href: 'mailto:user2@example.com', privilege: 'read-write' },
        ])
        expect(result).toContain('<?xml version="1.0"')
        expect(result).toContain('<CS:share')
        expect(result).toContain('mailto:user1@example.com')
        expect(result).toContain('mailto:user2@example.com')
      })

      it('declares the LS namespace so LS:share-access is valid', () => {
        const result = buildShareRequestXml([
          { href: 'mailto:user@example.com', privilege: 'freebusy' },
        ])
        expect(result).toMatch(/xmlns:LS=['"]/)
        expect(result).toContain('<LS:share-access>freebusy</LS:share-access>')
      })

      it('emits CS:read for freebusy with LS:share-access marker', () => {
        // Upstream sabre/dav's CS:share parser only knows CS:read and
        // CS:read-write — freebusy rides on CS:read with an LS marker.
        const result = buildShareRequestXml([
          { href: 'mailto:user@example.com', privilege: 'freebusy' },
        ])
        expect(result).toContain('<CS:read/>')
        expect(result).toContain('<LS:share-access>freebusy</LS:share-access>')
      })

      it('emits CS:read-write for admin with LS:share-access marker', () => {
        // Admin rides on CS:read-write because sabre/dav has no CS:admin.
        const result = buildShareRequestXml([
          { href: 'mailto:user@example.com', privilege: 'admin' },
        ])
        expect(result).toContain('<CS:read-write/>')
        expect(result).toContain('<LS:share-access>admin</LS:share-access>')
      })

      it('emits empty LS:share-access for read so backend clears any prior override', () => {
        // Without the empty marker, share_access_level stays pinned to
        // its previous value (e.g. a sharee being demoted from freebusy).
        const result = buildShareRequestXml([
          { href: 'mailto:user@example.com', privilege: 'read' },
        ])
        expect(result).toContain('<LS:share-access></LS:share-access>')
      })

      it('emits empty LS:share-access for read-write so backend clears any prior override', () => {
        const result = buildShareRequestXml([
          { href: 'mailto:user@example.com', privilege: 'read-write' },
        ])
        expect(result).toContain('<LS:share-access></LS:share-access>')
      })

      it('includes CS:common-name when displayName is provided', () => {
        const result = buildShareRequestXml([
          {
            href: 'mailto:user@example.com',
            displayName: 'John Doe',
            privilege: 'read',
          },
        ])
        expect(result).toContain('<CS:common-name>John Doe</CS:common-name>')
      })

      it('escapes displayName to prevent XML injection', () => {
        const result = buildShareRequestXml([
          {
            href: 'mailto:user@example.com',
            displayName: 'Evil <script>',
            privilege: 'read',
          },
        ])
        expect(result).toContain(
          '<CS:common-name>Evil &lt;script&gt;</CS:common-name>',
        )
      })
    })

    describe('buildUnshareRequestXml', () => {
      it('builds unshare request', () => {
        const result = buildUnshareRequestXml('mailto:user@example.com')
        expect(result).toContain('<CS:share')
        expect(result).toContain('<CS:remove>')
        expect(result).toContain('<D:href>mailto:user@example.com</D:href>')
      })
    })

  })

  // ============================================================================
  // Response Parsing Helpers
  // ============================================================================
  describe('Response Parsing Helpers', () => {
    describe('parseCalendarComponents', () => {
      it('returns undefined for empty input', () => {
        expect(parseCalendarComponents(null)).toBeUndefined()
        expect(parseCalendarComponents(undefined)).toBeUndefined()
      })

      it('parses array of components', () => {
        const input = {
          comp: [
            { _attributes: { name: 'VEVENT' } },
            { _attributes: { name: 'VTODO' } },
          ],
        }
        const result = parseCalendarComponents(input)
        expect(result).toEqual(['VEVENT', 'VTODO'])
      })

      it('parses single component', () => {
        const input = {
          comp: { _attributes: { name: 'VEVENT' } },
        }
        const result = parseCalendarComponents(input)
        expect(result).toEqual(['VEVENT'])
      })
    })

    describe('parseCalendarOrder', () => {
      // tsdav's xml-js parser auto-coerces pure-digit element text to a
      // JS number — the actual bug that broke calendar reordering once.
      it('returns a finite number unchanged', () => {
        expect(parseCalendarOrder(0)).toBe(0)
        expect(parseCalendarOrder(42)).toBe(42)
        expect(parseCalendarOrder(-1)).toBe(-1)
      })

      it('parses an integer-shaped string', () => {
        expect(parseCalendarOrder('0')).toBe(0)
        expect(parseCalendarOrder('100')).toBe(100)
        expect(parseCalendarOrder('-3')).toBe(-3)
        expect(parseCalendarOrder('+5')).toBe(5)
        expect(parseCalendarOrder('  42  ')).toBe(42)
      })

      it('rejects strings with trailing junk', () => {
        // Number.parseInt would happily eat the prefix and return 10;
        // the full-match guard prevents that.
        expect(parseCalendarOrder('10abc')).toBeUndefined()
        expect(parseCalendarOrder('1.5')).toBeUndefined()
        expect(parseCalendarOrder('1 2')).toBeUndefined()
      })

      it('returns undefined for missing / nullish / wrong-typed input', () => {
        expect(parseCalendarOrder(undefined)).toBeUndefined()
        expect(parseCalendarOrder(null)).toBeUndefined()
        expect(parseCalendarOrder({})).toBeUndefined()
        expect(parseCalendarOrder([])).toBeUndefined()
      })

      it('returns undefined for non-finite numbers', () => {
        expect(parseCalendarOrder(Number.NaN)).toBeUndefined()
        expect(parseCalendarOrder(Number.POSITIVE_INFINITY)).toBeUndefined()
        expect(parseCalendarOrder(Number.NEGATIVE_INFINITY)).toBeUndefined()
      })

      it('returns undefined for non-numeric strings', () => {
        expect(parseCalendarOrder('')).toBeUndefined()
        expect(parseCalendarOrder('abc')).toBeUndefined()
      })
    })

    describe('parseDavErrorMessage', () => {
      const SABREDAV_FORBIDDEN = (
        '<?xml version="1.0" encoding="utf-8"?>\n'
        + '<d:error xmlns:d="DAV:" xmlns:s="http://sabredav.org/ns">\n'
        + '  <s:sabredav-version>4.7.0</s:sabredav-version>\n'
        + '  <s:exception>Sabre\\DAV\\Exception\\Forbidden</s:exception>\n'
        + '  <s:message>This sharee is managed by Messages and can only be '
        + 'changed there. Update the mailbox permissions in Messages '
        + 'instead.</s:message>\n'
        + '</d:error>'
      )

      it('extracts the s:message from a SabreDAV Forbidden error', () => {
        expect(parseDavErrorMessage(SABREDAV_FORBIDDEN)).toBe(
          'This sharee is managed by Messages and can only be '
          + 'changed there. Update the mailbox permissions in Messages '
          + 'instead.',
        )
      })

      it('returns undefined for an empty body', () => {
        expect(parseDavErrorMessage('')).toBeUndefined()
      })

      it('returns undefined for malformed XML', () => {
        expect(parseDavErrorMessage('not <xml at all >>>')).toBeUndefined()
      })

      it('returns undefined when no s:message element is present', () => {
        const body = (
          '<?xml version="1.0"?>'
          + '<d:error xmlns:d="DAV:"><d:other/></d:error>'
        )
        expect(parseDavErrorMessage(body)).toBeUndefined()
      })

      it('returns undefined when s:message is empty / whitespace only', () => {
        const body = (
          '<?xml version="1.0"?>'
          + '<d:error xmlns:d="DAV:" xmlns:s="http://sabredav.org/ns">'
          + '<s:message>   </s:message>'
          + '</d:error>'
        )
        expect(parseDavErrorMessage(body)).toBeUndefined()
      })

      it('handles multi-element bodies and picks the first s:message', () => {
        const body = (
          '<?xml version="1.0"?>'
          + '<d:error xmlns:d="DAV:" xmlns:s="http://sabredav.org/ns">'
          + '<s:exception>X</s:exception>'
          + '<s:message>first</s:message>'
          + '<s:message>second</s:message>'
          + '</d:error>'
        )
        expect(parseDavErrorMessage(body)).toBe('first')
      })

      it('strips namespace prefixes so any prefix binding works', () => {
        // Defensive — SabreDAV always uses `s:` for its namespace, but
        // the parser is prefix-agnostic via `elementNameFn`. Verify a
        // body with a non-`s:` prefix still lands at `error.message`.
        const body = (
          '<?xml version="1.0"?>'
          + '<x:error xmlns:x="DAV:" xmlns:y="http://sabredav.org/ns">'
          + '<y:message>weird prefix</y:message>'
          + '</x:error>'
        )
        expect(parseDavErrorMessage(body)).toBe('weird prefix')
      })

      it('trims surrounding whitespace from the message', () => {
        const body = (
          '<?xml version="1.0"?>'
          + '<d:error xmlns:d="DAV:" xmlns:s="http://sabredav.org/ns">'
          + '<s:message>  spaced out  </s:message>'
          + '</d:error>'
        )
        expect(parseDavErrorMessage(body)).toBe('spaced out')
      })

      it('safely handles a 500 with non-DAV HTML body', () => {
        // Django's debug page (or any non-DAV 500) is HTML, not XML.
        // We must not throw or surface the HTML as a "friendly" message.
        const html =
          '<html><body><h1>500 Internal Server Error</h1></body></html>'
        expect(parseDavErrorMessage(html)).toBeUndefined()
      })

      it('returns undefined when the body is a JSON blob', () => {
        // Some endpoints may serve JSON errors; this isn't DAV.
        const body = '{"error":"bad","detail":"nope"}'
        expect(parseDavErrorMessage(body)).toBeUndefined()
      })
    })

    describe('getCalendarUrlFromEventUrl', () => {
      it('extracts calendar URL from event URL', () => {
        const eventUrl = '/calendars/user/calendar-1/event-123.ics'
        expect(getCalendarUrlFromEventUrl(eventUrl)).toBe('/calendars/user/calendar-1/')
      })

      it('handles URL without trailing slash', () => {
        const eventUrl = '/calendars/user/calendar-1/event.ics'
        expect(getCalendarUrlFromEventUrl(eventUrl)).toBe('/calendars/user/calendar-1/')
      })
    })
  })
})
