/**
 * CalDavService.moveEvent — auth-fallback regression test.
 *
 * The MOVE request is built with raw fetch (tsdav doesn't expose
 * a high-level move helper), so it has to assemble auth headers and
 * fetch options itself. If the source calendar isn't in the cache
 * (refresh race, stale state, source URL whose calendar key doesn't
 * normalize to a cached entry), the original spread-of-undefined
 * implementation silently dropped Authorization and credentials,
 * causing opaque 401s. moveEvent must fall back to the target
 * calendar's headers/options — both belong to the same CalDAV
 * account, so they're interchangeable.
 */
import { CalDavService } from '../CalDavService'

type CalendarStubInit = {
  url: string
  headers?: Record<string, string>
  fetchOptions?: RequestInit
}

function injectCalendar(svc: CalDavService, init: CalendarStubInit) {
  // _calendars is private; we poke it directly because constructing a
  // real one through connect() would require mocking the entire tsdav
  // PROPFIND chain.
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const calendars: Map<string, unknown> = (svc as any)._calendars
  calendars.set(init.url, {
    url: init.url,
    headers: init.headers,
    fetchOptions: init.fetchOptions,
    // The remaining fields are unused by moveEvent but required by
    // CalDavCalendar — leave as undefined.
  })
}

describe('CalDavService.moveEvent — auth fallback', () => {
  const originalFetch = globalThis.fetch
  let fetchMock: jest.Mock

  beforeEach(() => {
    fetchMock = jest.fn().mockResolvedValue({
      ok: true,
      status: 201,
      headers: new Headers({ etag: '"new-etag"' }),
    })
    globalThis.fetch = fetchMock as unknown as typeof fetch
  })

  afterEach(() => {
    globalThis.fetch = originalFetch
  })

  it('falls back to target calendar headers when source is not cached', async () => {
    const svc = new CalDavService()
    const targetCalendarUrl = 'http://srv/cal/B/'
    const sourceEventUrl = 'http://srv/cal/A/event-uid.ics'

    // Only the target calendar is cached. The source calendar entry is
    // missing — this is the failure mode we're testing.
    injectCalendar(svc, {
      url: targetCalendarUrl,
      headers: { Authorization: 'Bearer target-token' },
      fetchOptions: { credentials: 'include' as RequestCredentials },
    })

    const result = await svc.moveEvent({
      sourceEventUrl,
      targetCalendarUrl,
      sourceEtag: '"src-etag"',
    })

    expect(result.success).toBe(true)
    expect(fetchMock).toHaveBeenCalledTimes(1)

    const [calledUrl, init] = fetchMock.mock.calls[0]
    expect(calledUrl).toBe(sourceEventUrl)
    expect(init.method).toBe('MOVE')

    // Auth must come through despite the missing source calendar entry.
    expect(init.headers).toMatchObject({
      Authorization: 'Bearer target-token',
      Destination: 'http://srv/cal/B/event-uid.ics',
      Overwrite: 'F',
      'If-Match': '"src-etag"',
    })
    expect(init.credentials).toBe('include')
  })

  it('uses source calendar headers when both source and target are cached, target only as fallback', async () => {
    const svc = new CalDavService()
    const sourceCalendarUrl = 'http://srv/cal/A/'
    const targetCalendarUrl = 'http://srv/cal/B/'
    const sourceEventUrl = `${sourceCalendarUrl}event-uid.ics`

    injectCalendar(svc, {
      url: targetCalendarUrl,
      headers: { Authorization: 'Bearer target-token' },
      fetchOptions: { credentials: 'include' as RequestCredentials },
    })
    injectCalendar(svc, {
      url: sourceCalendarUrl,
      headers: { Authorization: 'Bearer source-token' },
      fetchOptions: { credentials: 'include' as RequestCredentials },
    })

    const result = await svc.moveEvent({
      sourceEventUrl,
      targetCalendarUrl,
    })

    expect(result.success).toBe(true)
    const [, init] = fetchMock.mock.calls[0]
    // Source headers win when both are present (per spread order:
    // ...target, ...source). Target only fills gaps.
    expect(init.headers.Authorization).toBe('Bearer source-token')
  })
})
