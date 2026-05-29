/**
 * CalDavService.connect — URL derivation regression test.
 *
 * connect() builds principal/home URLs by URI-encoding the user's email and
 * substituting it into a fixed SabreDAV path template. The encoding has to
 * match what SabreDAV emits in its PROPFIND hrefs *exactly* — otherwise the
 * hardcoded homeUrl won't be a string-prefix of the calendar URLs we later
 * receive, and the owned-vs-shared bucket logic in CalendarContext breaks.
 *
 * SabreDAV's `URLUtil::encodePath` leaves RFC 3986 sub-delims and `@` literal.
 * `encodeURIComponent` escapes `@` (→ `%40`) and `+` (→ `%2B`), so connect()
 * has to put those two back. This test pins that behaviour.
 */
import { CalDavService } from '../CalDavService'

describe('CalDavService.connect — URL derivation', () => {
  it('derives principalUrl and homeUrl from a plain email', async () => {
    const svc = new CalDavService()
    const result = await svc.connect({
      serverUrl: 'http://srv/caldav/',
      userEmail: 'user1@example.local',
    })
    expect(result.success).toBe(true)
    expect(result.data?.principalUrl).toBe(
      'http://srv/caldav/principals/users/user1@example.local/',
    )
    expect(result.data?.homeUrl).toBe(
      'http://srv/caldav/calendars/users/user1@example.local/',
    )
  })

  it('appends a trailing slash to a serverUrl that lacks one', async () => {
    const svc = new CalDavService()
    const result = await svc.connect({
      serverUrl: 'http://srv/caldav', // no trailing slash
      userEmail: 'user1@example.local',
    })
    expect(result.success).toBe(true)
    expect(result.data?.serverUrl).toBe('http://srv/caldav/')
    expect(result.data?.homeUrl).toBe(
      'http://srv/caldav/calendars/users/user1@example.local/',
    )
  })

  it('preserves @ literally (does not percent-encode it)', async () => {
    const svc = new CalDavService()
    const result = await svc.connect({
      serverUrl: 'http://srv/caldav/',
      userEmail: 'firstname.lastname@example.com',
    })
    // SabreDAV's URLUtil::encodePath leaves @ alone, so the homeUrl in
    // our cache must match the hrefs we'll receive from PROPFIND. If this
    // regressed to %40, the owned/shared bucket split in CalendarContext
    // would treat every calendar as "shared" (URL prefix mismatch).
    expect(result.data?.homeUrl).toContain('@example.com/')
    expect(result.data?.homeUrl).not.toContain('%40')
  })

  it('preserves + literally for emails like user+tag@example.com', async () => {
    const svc = new CalDavService()
    const result = await svc.connect({
      serverUrl: 'http://srv/caldav/',
      userEmail: 'sub+plus@example.com',
    })
    expect(result.data?.homeUrl).toContain('sub+plus@example.com/')
    expect(result.data?.homeUrl).not.toContain('%2B')
  })

  it('encodes characters that DO need escaping (e.g. spaces, slashes)', async () => {
    const svc = new CalDavService()
    const result = await svc.connect({
      serverUrl: 'http://srv/caldav/',
      // Pathological email — not a real-world one, but encoding any character
      // that breaks URL parsing should still happen.
      userEmail: 'has space@example.com',
    })
    expect(result.success).toBe(true)
    expect(result.data?.homeUrl).toContain('has%20space@example.com/')
  })

  it('rejects connect() without a userEmail', async () => {
    const svc = new CalDavService()
    // Cast away the type guard to exercise the runtime check; this also
    // documents that we no longer have the legacy discovery fallback.
    const result = await svc.connect({
      serverUrl: 'http://srv/caldav/',
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
    } as any)
    expect(result.success).toBe(false)
    expect(result.error).toMatch(/userEmail/)
  })

  it('makes the account observable via getAccount() after connect succeeds', async () => {
    const svc = new CalDavService()
    expect(svc.isConnected()).toBe(false)
    await svc.connect({
      serverUrl: 'http://srv/caldav/',
      userEmail: 'user1@example.local',
    })
    expect(svc.isConnected()).toBe(true)
    expect(svc.getAccount()?.homeUrl).toBe(
      'http://srv/caldav/calendars/users/user1@example.local/',
    )
  })
})
