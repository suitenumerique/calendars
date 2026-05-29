/**
 * @jest-environment jsdom
 *
 * Tests for the unified `davRequest` entry point in DavClient.
 *
 * This file is the safety net for the hand-rolled DAV layer:
 * - `buildPropfindBody` — PROPFIND XML body (replaces tsdav's body builder)
 * - `parseMultistatus` — 207 multi-status response parser (replaces tsdav's)
 * - `davRequest` — the public function: shared headers, credentials,
 *   401 → redirect-to-login, SabreDAV error parsing.
 *
 * After dropping tsdav, these are what guarantees we still build and
 * parse CalDAV traffic correctly. Requires the jsdom environment because
 * `parseMultistatus` / `parseDavErrorMessage` use the native `DOMParser`.
 */

jest.mock('@/features/api/fetchApi', () => ({
  redirectToLogin: jest.fn(),
}))

import {
  buildPropfindBody,
  parseMultistatus,
  davRequest,
} from '../DavClient'
import { redirectToLogin } from '@/features/api/fetchApi'

const redirectToLoginMock = redirectToLogin as jest.MockedFunction<
  typeof redirectToLogin
>

const originalFetch = globalThis.fetch
let fetchMock: jest.Mock

beforeEach(() => {
  fetchMock = jest.fn()
  globalThis.fetch = fetchMock as unknown as typeof fetch
  redirectToLoginMock.mockClear()
})

afterEach(() => {
  globalThis.fetch = originalFetch
})

describe('buildPropfindBody', () => {
  it('wraps props in a <d:propfind><d:prop> envelope with all xmlns declared', () => {
    const xml = buildPropfindBody({
      'd:displayname': {},
      'c:calendar-timezone': {},
      'LS:share-access-map': {},
    })
    expect(xml).toContain('<?xml version="1.0"')
    expect(xml).toContain('<d:propfind ')
    expect(xml).toContain('xmlns:d="DAV:"')
    expect(xml).toContain('xmlns:c="urn:ietf:params:xml:ns:caldav"')
    expect(xml).toContain('xmlns:LS="http://lasuite.numerique.gouv.fr/ns/"')
    expect(xml).toContain('<d:displayname/>')
    expect(xml).toContain('<c:calendar-timezone/>')
    expect(xml).toContain('<LS:share-access-map/>')
    expect(xml).toContain('</d:propfind>')
  })

  it('emits self-closing prop elements verbatim from the keys', () => {
    // Key names carry their own prefix; we don't transform them.
    const xml = buildPropfindBody({ 'cs:getctag': {} })
    expect(xml).toContain('<cs:getctag/>')
    expect(xml).not.toContain('<getctag')
  })

  it('produces a valid empty-prop body when given no props', () => {
    const xml = buildPropfindBody({})
    expect(xml).toContain('<d:propfind ')
    expect(xml).toContain('<d:prop></d:prop>')
  })

  // Defensive hardening — if a future caller hands user-controlled input
  // as a PROPFIND key, we must refuse to build the body rather than emit
  // raw XML and let SabreDAV (or worse, the response parser) trip over it.
  describe('key validation', () => {
    it('throws on a key that breaks out of the element', () => {
      expect(() =>
        buildPropfindBody({ "d:displayname/><evil x='": {} }),
      ).toThrow(/Invalid PROPFIND prop name/)
    })

    it('throws on a key with whitespace', () => {
      expect(() => buildPropfindBody({ "d:bad name": {} })).toThrow(
        /Invalid PROPFIND prop name/,
      )
    })

    it('throws on a key with a leading digit', () => {
      expect(() => buildPropfindBody({ "1bad": {} })).toThrow(
        /Invalid PROPFIND prop name/,
      )
    })

    it('throws on a key with an attribute injection', () => {
      expect(() =>
        buildPropfindBody({ 'd:x" attr="value': {} }),
      ).toThrow(/Invalid PROPFIND prop name/)
    })

    it('throws on a key with multiple colons', () => {
      expect(() => buildPropfindBody({ 'd:foo:bar': {} })).toThrow(
        /Invalid PROPFIND prop name/,
      )
    })

    it('accepts every prop name actually used in the codebase', () => {
      // Pin the in-tree call sites so a regex tweak can't break production.
      const realKeys = [
        'd:displayname',
        'd:resourcetype',
        'd:acl',
        'd:owner',
        'd:sync-token',
        'c:calendar-description',
        'c:calendar-timezone',
        'c:calendar-availability',
        'c:supported-calendar-component-set',
        'c:schedule-calendar-transp',
        'c:schedule-outbox-URL',
        'c:schedule-inbox-URL',
        'c:calendar-user-type',
        'c:calendar-user-address-set',
        'c:calendar-home-set',
        'ca:calendar-color',
        'ca:calendar-order',
        'cs:getctag',
        'cs:invite',
        'cs:notification-URL',
        'cs:notification',
        'cs:email-address-set',
        'card:addressbook-home-set',
        'LS:calendar-owner-type',
        'LS:share-access-map',
      ]
      for (const k of realKeys) {
        expect(() => buildPropfindBody({ [k]: {} })).not.toThrow()
      }
    })
  })
})

describe('parseMultistatus', () => {
  it('returns [] for an unparseable body', () => {
    expect(parseMultistatus('not xml')).toEqual([])
  })

  it('returns [] when the root is not <d:multistatus>', () => {
    const xml = '<?xml version="1.0"?><d:error xmlns:d="DAV:"/>'
    expect(parseMultistatus(xml)).toEqual([])
  })

  it('parses a single <d:response> with href + 200 propstat', () => {
    const xml = `<?xml version="1.0"?>
      <d:multistatus xmlns:d="DAV:" xmlns:cal="urn:ietf:params:xml:ns:caldav">
        <d:response>
          <d:href>/caldav/calendars/u/cal-a/event.ics</d:href>
          <d:propstat>
            <d:prop>
              <d:getetag>"abc123"</d:getetag>
              <cal:calendar-data>BEGIN:VCALENDAR</cal:calendar-data>
            </d:prop>
            <d:status>HTTP/1.1 200 OK</d:status>
          </d:propstat>
        </d:response>
      </d:multistatus>`
    const responses = parseMultistatus(xml)
    expect(responses).toHaveLength(1)
    expect(responses[0].href).toBe('/caldav/calendars/u/cal-a/event.ics')
    expect(responses[0].status).toBe(200)
    expect(responses[0].ok).toBe(true)
    // Element names are camelCased and namespace prefixes stripped, so
    // `cal:calendar-data` lands at `props.calendarData`, matching what
    // CalDavService.fetchEvents iterates over.
    expect(responses[0].props.getetag).toBe('"abc123"')
    expect(responses[0].props.calendarData).toBe('BEGIN:VCALENDAR')
  })

  it('parses multiple <d:response> children', () => {
    const xml = `<?xml version="1.0"?>
      <d:multistatus xmlns:d="DAV:">
        <d:response>
          <d:href>/cal-a/</d:href>
          <d:propstat><d:prop><d:displayname>A</d:displayname></d:prop><d:status>HTTP/1.1 200 OK</d:status></d:propstat>
        </d:response>
        <d:response>
          <d:href>/cal-b/</d:href>
          <d:propstat><d:prop><d:displayname>B</d:displayname></d:prop><d:status>HTTP/1.1 200 OK</d:status></d:propstat>
        </d:response>
      </d:multistatus>`
    const responses = parseMultistatus(xml)
    expect(responses.map((r) => r.href)).toEqual(['/cal-a/', '/cal-b/'])
    expect(responses[0].props.displayname).toBe('A')
    expect(responses[1].props.displayname).toBe('B')
  })

  it('ignores 404 propstats (missing properties on a resource that exists)', () => {
    // SabreDAV PROPFIND returns BOTH a 200 propstat (for present props)
    // and a 404 propstat (for the requested-but-unavailable ones) on the
    // same response. The 404 props must not pollute the merged props.
    const xml = `<?xml version="1.0"?>
      <d:multistatus xmlns:d="DAV:" xmlns:cs="http://calendarserver.org/ns/">
        <d:response>
          <d:href>/cal/</d:href>
          <d:propstat>
            <d:prop><d:displayname>Present</d:displayname></d:prop>
            <d:status>HTTP/1.1 200 OK</d:status>
          </d:propstat>
          <d:propstat>
            <d:prop><cs:getctag/></d:prop>
            <d:status>HTTP/1.1 404 Not Found</d:status>
          </d:propstat>
        </d:response>
      </d:multistatus>`
    const responses = parseMultistatus(xml)
    expect(responses).toHaveLength(1)
    expect(responses[0].props.displayname).toBe('Present')
    expect(responses[0].props.getctag).toBeUndefined()
    // The outer entry status comes from the first propstat (200).
    expect(responses[0].status).toBe(200)
    expect(responses[0].ok).toBe(true)
  })

  it('falls back to response-level <d:status> when no propstat is present', () => {
    const xml = `<?xml version="1.0"?>
      <d:multistatus xmlns:d="DAV:">
        <d:response>
          <d:href>/missing/</d:href>
          <d:status>HTTP/1.1 404 Not Found</d:status>
        </d:response>
      </d:multistatus>`
    const responses = parseMultistatus(xml)
    expect(responses).toHaveLength(1)
    expect(responses[0].status).toBe(404)
    expect(responses[0].ok).toBe(false)
  })

  it('handles attributes on prop children (calendar-user-address-set href)', () => {
    // tsdav's xml-js parser lands attribute-bearing children's href under
    // `props.X.href`. CalDavService.findSchedulingOutbox depends on this
    // shape: `props.scheduleOutboxURL.href`.
    const xml = `<?xml version="1.0"?>
      <d:multistatus xmlns:d="DAV:" xmlns:cal="urn:ietf:params:xml:ns:caldav">
        <d:response>
          <d:href>/p/</d:href>
          <d:propstat>
            <d:prop>
              <cal:schedule-outbox-URL>
                <d:href>/p/outbox/</d:href>
              </cal:schedule-outbox-URL>
            </d:prop>
            <d:status>HTTP/1.1 200 OK</d:status>
          </d:propstat>
        </d:response>
      </d:multistatus>`
    const responses = parseMultistatus(xml)
    // 'schedule-outbox-URL' → 'scheduleOutboxURL'
    expect(responses[0].props.scheduleOutboxURL.href).toBe('/p/outbox/')
  })

  it('handles a sole <multistatus> root without the d: prefix', () => {
    // Defensive — some servers may bind DAV as the default namespace
    // with no prefix.
    const xml = `<?xml version="1.0"?>
      <multistatus xmlns="DAV:">
        <response>
          <href>/x/</href>
          <propstat>
            <prop><displayname>X</displayname></prop>
            <status>HTTP/1.1 200 OK</status>
          </propstat>
        </response>
      </multistatus>`
    const responses = parseMultistatus(xml)
    expect(responses).toHaveLength(1)
    expect(responses[0].href).toBe('/x/')
    expect(responses[0].props.displayname).toBe('X')
  })

  it('returns text node values as strings (no auto-numeric coercion)', () => {
    // tsdav passed prop text through a `nativeType` coercer that turned
    // `<getetag>1700000000</getetag>` into the number `1700000000`. We
    // intentionally leave text as-is so etag comparisons (`=== '"old"'`)
    // are stable and never silently change a string to a number.
    // `parseCalendarOrder` handles the string form itself.
    const xml = `<?xml version="1.0"?>
      <d:multistatus xmlns:d="DAV:" xmlns:ca="http://apple.com/ns/ical/">
        <d:response>
          <d:href>/x/</d:href>
          <d:propstat>
            <d:prop>
              <d:getetag>"abc"</d:getetag>
              <ca:calendar-order>42</ca:calendar-order>
            </d:prop>
            <d:status>HTTP/1.1 200 OK</d:status>
          </d:propstat>
        </d:response>
      </d:multistatus>`
    const responses = parseMultistatus(xml)
    expect(responses[0].props.getetag).toBe('"abc"')
    expect(typeof responses[0].props.getetag).toBe('string')
    expect(responses[0].props.calendarOrder).toBe('42')
    expect(typeof responses[0].props.calendarOrder).toBe('string')
  })

  it('surfaces per-resource <d:responsedescription> and <d:error>', () => {
    // RFC 4918 §11 — SabreDAV may emit either alongside a 207 entry to
    // explain a per-resource fault more specifically than HTTP status alone.
    const xml = `<?xml version="1.0"?>
      <d:multistatus xmlns:d="DAV:">
        <d:response>
          <d:href>/locked/</d:href>
          <d:status>HTTP/1.1 423 Locked</d:status>
          <d:error><d:lock-token-submitted/></d:error>
          <d:responsedescription>Resource is locked by another user.</d:responsedescription>
        </d:response>
      </d:multistatus>`
    const responses = parseMultistatus(xml)
    expect(responses[0].status).toBe(423)
    expect(responses[0].ok).toBe(false)
    expect(responses[0].responseDescription).toBe(
      'Resource is locked by another user.',
    )
    // The <d:error> child is normalized into the response's `error` field.
    expect(responses[0].error).toEqual(
      expect.objectContaining({ lockTokenSubmitted: expect.any(Object) }),
    )
  })

  it('strips a single namespace prefix and camelCases local names', () => {
    // Documented behavior: `<x:foo>` lands at `props.foo`, and
    // `<cs:share-access-map>` lands at `props.shareAccessMap`.
    const xml = `<?xml version="1.0"?>
      <d:multistatus xmlns:d="DAV:" xmlns:x="DAV:" xmlns:cs="http://calendarserver.org/ns/">
        <d:response>
          <d:href>/x/</d:href>
          <d:propstat>
            <d:prop>
              <x:foo>value</x:foo>
              <cs:share-access-map>map</cs:share-access-map>
            </d:prop>
            <d:status>HTTP/1.1 200 OK</d:status>
          </d:propstat>
        </d:response>
      </d:multistatus>`
    const responses = parseMultistatus(xml)
    expect(responses[0].props.foo).toBe('value')
    expect(responses[0].props.shareAccessMap).toBe('map')
  })
})

describe('davRequest — non-XML response body handling', () => {
  it('returns responses=undefined when a 207 body has a non-XML content-type', async () => {
    // Defensive — if a misconfigured backend ever returns a 207 with
    // `text/html`, blindly running it through `parseMultistatus` would
    // yield `[]`, which a caller might mistake for "no resources found".
    // Signalling `undefined` lets the caller distinguish parse failure
    // from an empty multistatus.
    fetchMock.mockResolvedValue({
      ok: true,
      status: 207,
      headers: new Headers({ 'content-type': 'text/html' }),
      text: async () => '<html><body>not xml</body></html>',
    })
    const result = await davRequest({
      url: 'http://srv/cal/',
      method: 'PROPFIND',
      props: { 'd:displayname': {} },
    })
    expect(result.success).toBe(true)
    expect(result.responses).toBeUndefined()
    // The raw body is still surfaced so callers can log/inspect.
    expect(result.body).toContain('not xml')
  })
})

describe('davRequest — request shape', () => {
  function ok207(body: string) {
    return {
      ok: true,
      status: 207,
      headers: new Headers({ 'content-type': 'application/xml' }),
      text: async () => body,
    }
  }

  it('includes credentials and X-LS-Client: web on every request', async () => {
    fetchMock.mockResolvedValue({
      ok: true,
      status: 200,
      headers: new Headers(),
      text: async () => '',
    })
    await davRequest({
      url: 'http://srv/caldav/cal/event.ics',
      method: 'GET',
      headers: { Accept: 'text/calendar' },
    })
    expect(fetchMock).toHaveBeenCalledTimes(1)
    const [, init] = fetchMock.mock.calls[0]
    expect(init.credentials).toBe('include')
    expect(init.headers).toMatchObject({
      'X-LS-Client': 'web',
      Accept: 'text/calendar',
    })
  })

  it('sends a PROPFIND with Depth + structured XML body and parses the multistatus', async () => {
    fetchMock.mockResolvedValue(
      ok207(
        `<?xml version="1.0"?>
        <d:multistatus xmlns:d="DAV:">
          <d:response>
            <d:href>/cal/</d:href>
            <d:propstat><d:prop><d:displayname>X</d:displayname></d:prop><d:status>HTTP/1.1 200 OK</d:status></d:propstat>
          </d:response>
        </d:multistatus>`,
      ),
    )
    const result = await davRequest({
      url: 'http://srv/cal/',
      method: 'PROPFIND',
      props: { 'd:displayname': {} },
      depth: '0',
    })
    expect(result.success).toBe(true)
    const [, init] = fetchMock.mock.calls[0]
    expect(init.method).toBe('PROPFIND')
    expect(init.headers).toMatchObject({
      Depth: '0',
      'Content-Type': 'application/xml; charset=utf-8',
    })
    expect(init.body).toContain('<d:propfind ')
    expect(init.body).toContain('<d:displayname/>')
    expect(result.responses).toHaveLength(1)
    expect(result.responses?.[0].props.displayname).toBe('X')
  })

  it('parses a REPORT (calendar-query) multistatus into responses', async () => {
    fetchMock.mockResolvedValue(
      ok207(
        `<?xml version="1.0"?>
        <d:multistatus xmlns:d="DAV:" xmlns:cal="urn:ietf:params:xml:ns:caldav">
          <d:response>
            <d:href>/cal/evt.ics</d:href>
            <d:propstat>
              <d:prop>
                <d:getetag>"e1"</d:getetag>
                <cal:calendar-data>ICS-BODY</cal:calendar-data>
              </d:prop>
              <d:status>HTTP/1.1 200 OK</d:status>
            </d:propstat>
          </d:response>
        </d:multistatus>`,
      ),
    )
    const result = await davRequest({
      url: 'http://srv/cal/',
      method: 'REPORT',
      body: '<C:calendar-query/>',
      depth: '1',
    })
    expect(result.success).toBe(true)
    expect(result.responses?.[0].props.getetag).toBe('"e1"')
    expect(result.responses?.[0].props.calendarData).toBe('ICS-BODY')
  })

  it('returns the response body on GET', async () => {
    fetchMock.mockResolvedValue({
      ok: true,
      status: 200,
      headers: new Headers({ etag: '"e2"' }),
      text: async () => 'BEGIN:VCALENDAR',
    })
    const result = await davRequest({
      url: 'http://srv/cal/event.ics',
      method: 'GET',
    })
    expect(result.success).toBe(true)
    expect(result.body).toBe('BEGIN:VCALENDAR')
    expect(result.responseHeaders?.get('etag')).toBe('"e2"')
  })

  it('treats 204 No Content as success with no body', async () => {
    // Real-world Response: 204 falls in 200-299, so Response.ok is true.
    fetchMock.mockResolvedValue({
      ok: true,
      status: 204,
      headers: new Headers(),
      text: async () => '',
    })
    const result = await davRequest({
      url: 'http://srv/cal/event.ics',
      method: 'DELETE',
    })
    expect(result.success).toBe(true)
    expect(result.body).toBeUndefined()
  })

  it('calls redirectToLogin on 401 and surfaces success=false', async () => {
    fetchMock.mockResolvedValue({
      ok: false,
      status: 401,
      headers: new Headers(),
      text: async () => '',
    })
    const result = await davRequest({
      url: 'http://srv/cal/',
      method: 'PROPFIND',
      props: { 'd:displayname': {} },
    })
    expect(result.success).toBe(false)
    expect(result.status).toBe(401)
    expect(redirectToLoginMock).toHaveBeenCalledTimes(1)
  })

  it('does NOT call redirectToLogin on non-auth failures', async () => {
    fetchMock.mockResolvedValue({
      ok: false,
      status: 500,
      headers: new Headers(),
      text: async () => '<d:error/>',
    })
    const result = await davRequest({
      url: 'http://srv/cal/',
      method: 'POST',
      body: '<xml/>',
    })
    expect(result.success).toBe(false)
    expect(result.status).toBe(500)
    expect(redirectToLoginMock).not.toHaveBeenCalled()
  })

  it('surfaces the SabreDAV <s:message> as the friendly error', async () => {
    const errBody =
      '<?xml version="1.0"?>' +
      '<d:error xmlns:d="DAV:" xmlns:s="http://sabredav.org/ns">' +
      '<s:exception>X</s:exception>' +
      '<s:message>This sharee is managed by Messages</s:message>' +
      '</d:error>'
    fetchMock.mockResolvedValue({
      ok: false,
      status: 403,
      headers: new Headers(),
      text: async () => errBody,
    })
    const result = await davRequest({
      url: 'http://srv/cal/',
      method: 'POST',
      body: '<x/>',
    })
    expect(result.success).toBe(false)
    expect(result.error).toBe('This sharee is managed by Messages')
  })

  it('converts a thrown network error into success=false with status=0', async () => {
    fetchMock.mockRejectedValue(new Error('TypeError: Failed to fetch'))
    const result = await davRequest({
      url: 'http://srv/cal/',
      method: 'GET',
    })
    expect(result.success).toBe(false)
    expect(result.status).toBe(0)
    expect(result.error).toContain('Failed to fetch')
  })

  it('sets If-Match when caller passes it via headers (PUT)', async () => {
    fetchMock.mockResolvedValue({
      ok: true,
      status: 204,
      headers: new Headers({ etag: '"new"' }),
      text: async () => '',
    })
    await davRequest({
      url: 'http://srv/cal/event.ics',
      method: 'PUT',
      body: 'ICS',
      contentType: 'text/calendar; charset=utf-8',
      headers: { 'If-Match': '"old"' },
    })
    const [, init] = fetchMock.mock.calls[0]
    expect(init.headers['If-Match']).toBe('"old"')
    expect(init.headers['Content-Type']).toBe('text/calendar; charset=utf-8')
    expect(init.body).toBe('ICS')
  })
})
