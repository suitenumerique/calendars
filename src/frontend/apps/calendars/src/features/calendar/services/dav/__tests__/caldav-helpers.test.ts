/**
 * Tests for CalDAV Helper functions
 */
import {
  escapeXml,
  XML_NS,
  xmlProp,
  xmlPropOptional,
  buildCalendarPropsXml,
  buildMkCalendarXml,
  buildProppatchXml,
  sharePrivilegeToXml,
  parseSharePrivilege,
  buildShareeSetXml,
  buildShareRequestXml,
  buildUnshareRequestXml,
  buildInviteReplyXml,
  buildSyncCollectionXml,
  buildPrincipalSearchXml,
  parseCalendarComponents,
  parseDavErrorMessage,
  parseShareStatus,
  getCalendarUrlFromEventUrl,
} from '../caldav-helpers'
import type { SharePrivilege } from '../types/caldav-service'

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

    describe('xmlPropOptional', () => {
      it('returns element when value is defined', () => {
        expect(xmlPropOptional('D', 'displayname', 'Test')).toBe(
          '<D:displayname>Test</D:displayname>'
        )
      })

      it('returns empty string when value is undefined', () => {
        expect(xmlPropOptional('D', 'displayname', undefined)).toBe('')
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
    })

    describe('buildProppatchXml', () => {
      it('creates valid PROPPATCH XML', () => {
        const result = buildProppatchXml({ displayName: 'Updated Name' })
        expect(result).toContain('<?xml version="1.0"')
        expect(result).toContain('<D:propertyupdate')
        expect(result).toContain('<D:set>')
        expect(result).toContain('<D:displayname>Updated Name</D:displayname>')
      })
    })
  })

  // ============================================================================
  // Sharing XML Builders
  // ============================================================================
  describe('Sharing XML Builders', () => {
    describe('sharePrivilegeToXml', () => {
      it('converts read privilege', () => {
        expect(sharePrivilegeToXml('read')).toBe('<CS:read/>')
      })

      it('converts read-write privilege', () => {
        expect(sharePrivilegeToXml('read-write')).toBe('<CS:read-write/>')
      })

      it('rides admin on top of read-write (no <CS:admin/> upstream)', () => {
        // Upstream sabre/dav silently demotes <CS:admin/> to read; we
        // carry the admin marker via LS:share-access instead.
        expect(sharePrivilegeToXml('admin')).toBe('<CS:read-write/>')
      })

      it('converts freebusy privilege to read (CalDAV level)', () => {
        expect(sharePrivilegeToXml('freebusy')).toBe('<CS:read/>')
      })

      it('defaults to read for unknown', () => {
        expect(sharePrivilegeToXml('unknown' as SharePrivilege)).toBe('<CS:read/>')
      })
    })

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

    describe('buildShareeSetXml', () => {
      it('builds basic sharee XML', () => {
        const result = buildShareeSetXml({
          href: 'mailto:user@example.com',
          privilege: 'read-write',
        })
        expect(result).toContain('<CS:set>')
        expect(result).toContain('<D:href>mailto:user@example.com</D:href>')
        expect(result).toContain('<CS:read-write/>')
      })

      it('includes displayName when provided', () => {
        const result = buildShareeSetXml({
          href: 'mailto:user@example.com',
          displayName: 'John Doe',
          privilege: 'read',
        })
        expect(result).toContain('<CS:common-name>John Doe</CS:common-name>')
      })

      it('includes LS:share-access "freebusy" for freebusy privilege', () => {
        const result = buildShareeSetXml({
          href: 'mailto:user@example.com',
          privilege: 'freebusy',
        })
        expect(result).toContain('<CS:read/>')
        expect(result).toContain('<LS:share-access>freebusy</LS:share-access>')
      })

      it('includes LS:share-access "admin" for admin privilege', () => {
        const result = buildShareeSetXml({
          href: 'mailto:user@example.com',
          privilege: 'admin',
        })
        // Admin rides on read-write because upstream sabre/dav has no
        // CS:admin element; the marker is what makes it admin.
        expect(result).toContain('<CS:read-write/>')
        expect(result).toContain('<LS:share-access>admin</LS:share-access>')
      })

      it('emits empty LS:share-access for read so backend resets the override', () => {
        // The empty marker tells the backend to clear any previously
        // stored override (e.g. a sharee being moved off freebusy).
        // Without it, the share_access_level column stays pinned.
        const result = buildShareeSetXml({
          href: 'mailto:user@example.com',
          privilege: 'read',
        })
        expect(result).toContain('<LS:share-access></LS:share-access>')
      })

      it('emits empty LS:share-access for read-write so backend resets the override', () => {
        const result = buildShareeSetXml({
          href: 'mailto:user@example.com',
          privilege: 'read-write',
        })
        expect(result).toContain('<LS:share-access></LS:share-access>')
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
    })

    describe('buildUnshareRequestXml', () => {
      it('builds unshare request', () => {
        const result = buildUnshareRequestXml('mailto:user@example.com')
        expect(result).toContain('<CS:share')
        expect(result).toContain('<CS:remove>')
        expect(result).toContain('<D:href>mailto:user@example.com</D:href>')
      })
    })

    describe('buildInviteReplyXml', () => {
      it('builds accept reply', () => {
        const result = buildInviteReplyXml('invite-123', true)
        expect(result).toContain('<CS:invite-reply')
        expect(result).toContain('<CS:in-reply-to>invite-123</CS:in-reply-to>')
        expect(result).toContain('<CS:invite-accepted/>')
      })

      it('builds decline reply', () => {
        const result = buildInviteReplyXml('invite-123', false)
        expect(result).toContain('<CS:invite-declined/>')
      })
    })
  })

  // ============================================================================
  // Sync XML Builders
  // ============================================================================
  describe('Sync XML Builders', () => {
    describe('buildSyncCollectionXml', () => {
      it('builds sync-collection XML', () => {
        const result = buildSyncCollectionXml({
          syncToken: 'token-123',
        })
        expect(result).toContain('<?xml version="1.0"')
        expect(result).toContain('<D:sync-collection')
        expect(result).toContain('<D:sync-token>token-123</D:sync-token>')
        expect(result).toContain('<D:sync-level>1</D:sync-level>')
        expect(result).toContain('<D:getetag/>')
        expect(result).toContain('<C:calendar-data/>')
      })

      it('uses custom sync level', () => {
        const result = buildSyncCollectionXml({
          syncToken: 'token-123',
          syncLevel: 'infinite',
        })
        expect(result).toContain('<D:sync-level>infinite</D:sync-level>')
      })
    })
  })

  // ============================================================================
  // Principal Search XML Builder
  // ============================================================================
  describe('Principal Search XML Builder', () => {
    describe('buildPrincipalSearchXml', () => {
      it('builds principal search XML', () => {
        const result = buildPrincipalSearchXml('john')
        expect(result).toContain('<?xml version="1.0"')
        expect(result).toContain('<D:principal-property-search')
        expect(result).toContain('<D:match>john</D:match>')
        expect(result).toContain('<D:displayname/>')
        expect(result).toContain('<C:calendar-home-set')
      })

      it('escapes query', () => {
        const result = buildPrincipalSearchXml('Tom & Jerry')
        expect(result).toContain('<D:match>Tom &amp; Jerry</D:match>')
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

    describe('parseShareStatus', () => {
      it('returns accepted when accepted is truthy', () => {
        expect(parseShareStatus(true, false)).toBe('accepted')
      })

      it('returns pending when noResponse is truthy', () => {
        expect(parseShareStatus(false, true)).toBe('pending')
      })

      it('returns declined as default', () => {
        expect(parseShareStatus(false, false)).toBe('declined')
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
