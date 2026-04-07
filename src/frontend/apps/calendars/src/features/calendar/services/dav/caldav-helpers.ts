/**
 * CalDAV Helper Functions
 *
 * Factorized utilities for XML building, DAV requests, and error handling.
 */

import { davRequest, DAVNamespaceShort } from 'tsdav'
import type { DAVMethods } from 'tsdav'
import { xml2js, type ElementCompact } from 'xml-js'

type HTTPMethods = 'GET' | 'HEAD' | 'POST' | 'PUT' | 'DELETE' | 'CONNECT' | 'OPTIONS' | 'TRACE' | 'PATCH'
type AllowedMethods = DAVMethods | HTTPMethods
import type { SharePrivilege, CalDavResponse } from './types/caldav-service'

// ============================================================================
// XML Helpers
// ============================================================================

/** Escape special XML characters */
export function escapeXml(str: string | undefined | null): string {
  if (str === undefined || str === null) {
    return '';
  }
  if (typeof str !== 'string') {
    str = String(str);
  }
  return str
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&apos;')
}

/** XML namespaces used in CalDAV */
export const XML_NS = {
  DAV: 'xmlns:D="DAV:"',
  CALDAV: 'xmlns:C="urn:ietf:params:xml:ns:caldav"',
  APPLE: 'xmlns:A="http://apple.com/ns/ical/"',
  CS: 'xmlns:CS="http://calendarserver.org/ns/"',
  LS: 'xmlns:LS="http://lasuite.numerique.gouv.fr/ns/"',
} as const

/** Build XML prop element */
export function xmlProp(namespace: string, name: string, value: string): string {
  return `<${namespace}:${name}>${escapeXml(value)}</${namespace}:${name}>`
}

/** Build XML with optional value (returns empty string if value is undefined) */
export function xmlPropOptional(namespace: string, name: string, value: string | undefined): string {
  return value !== undefined ? xmlProp(namespace, name, value) : ''
}

// ============================================================================
// Calendar Property Builders
// ============================================================================

export type CalendarProps = {
  displayName?: string
  description?: string
  color?: string
  components?: string[]
  /** schedule-calendar-transp: 'opaque' (counts as busy) or 'transparent' */
  scheduleTransp?: 'opaque' | 'transparent'
}

/** Build calendar property XML elements */
export function buildCalendarPropsXml(props: CalendarProps): string[] {
  const elements: string[] = []

  if (props.displayName !== undefined && props.displayName !== null && typeof props.displayName === 'string') {
    elements.push(xmlProp('D', 'displayname', props.displayName))
  }
  if (props.description !== undefined && props.description !== null && typeof props.description === 'string') {
    elements.push(xmlProp('C', 'calendar-description', props.description))
  }
  if (props.color !== undefined && props.color !== null && typeof props.color === 'string') {
    elements.push(xmlProp('A', 'calendar-color', props.color))
  }
  if (props.components && props.components.length > 0) {
    const comps = props.components.map((c) => `<C:comp name="${escapeXml(c)}"/>`).join('')
    elements.push(`<C:supported-calendar-component-set>${comps}</C:supported-calendar-component-set>`)
  }
  if (props.scheduleTransp !== undefined) {
    // RFC 6638: schedule-calendar-transp controls whether this calendar
    // participates in freebusy calculations. Standard CalDAV property.
    const value = props.scheduleTransp === 'transparent'
      ? '<C:transparent/>'
      : '<C:opaque/>'
    elements.push(`<C:schedule-calendar-transp>${value}</C:schedule-calendar-transp>`)
  }

  return elements
}

/** Build MKCALENDAR request body */
export function buildMkCalendarXml(props: CalendarProps): string {
  const propsXml = buildCalendarPropsXml(props)
  return `<?xml version="1.0" encoding="utf-8"?>
<C:mkcalendar ${XML_NS.DAV} ${XML_NS.CALDAV} ${XML_NS.APPLE}>
  <D:set>
    <D:prop>
      ${propsXml.join('\n      ')}
    </D:prop>
  </D:set>
</C:mkcalendar>`
}

/** Build PROPPATCH request body */
export function buildProppatchXml(props: CalendarProps): string {
  const propsXml = buildCalendarPropsXml(props)
  return `<?xml version="1.0" encoding="utf-8"?>
<D:propertyupdate ${XML_NS.DAV} ${XML_NS.CALDAV} ${XML_NS.APPLE}>
  <D:set>
    <D:prop>
      ${propsXml.join('\n      ')}
    </D:prop>
  </D:set>
</D:propertyupdate>`
}

// ============================================================================
// Sharing XML Builders
// ============================================================================

/** Convert SharePrivilege to CalDAV XML element.
 *
 * Both ``freebusy`` and ``admin`` ride on standard CalDAV access levels
 * because upstream SabreDAV's CS:share parser only recognizes
 * ``<CS:read/>`` and ``<CS:read-write/>`` (everything else, including
 * a hypothetical ``<CS:admin/>``, is silently demoted to read — see
 * sabre/dav lib/CalDAV/Xml/Request/Share.php). The actual logical
 * level is then carried by an LS:share-access marker (see
 * ``buildShareeSetXml``):
 *
 *   - freebusy → ``<CS:read/>`` + ``<LS:share-access>freebusy</LS:share-access>``
 *   - read     → ``<CS:read/>``
 *   - r/write  → ``<CS:read-write/>``
 *   - admin    → ``<CS:read-write/>`` + ``<LS:share-access>admin</LS:share-access>``
 */
export function sharePrivilegeToXml(privilege: SharePrivilege): string {
  const map: Record<SharePrivilege, string> = {
    freebusy: '<CS:read/>',
    read: '<CS:read/>',
    'read-write': '<CS:read-write/>',
    admin: '<CS:read-write/>',
  }
  return map[privilege] ?? '<CS:read/>'
}

/** Parse access object to SharePrivilege.
 *
 * The CalDAV-level access (CS:read, CS:read-write) is augmented by a
 * custom LS:share-access property on the calendar instance. The
 * override (if any) wins over the underlying CalDAV access:
 *
 *   - LS:share-access "freebusy" → freebusy (CS:read underlying)
 *   - LS:share-access "admin"    → admin (CS:read-write underlying)
 *   - else CS:read-write         → read-write
 *   - else                       → read
 *
 * Note: tsdav's XML parser camelCases element names (e.g. cs:read-write -> readWrite),
 * so we check both kebab-case and camelCase variants.
 */
export function parseSharePrivilege(access: unknown, shareAccess?: string): SharePrivilege {
  if (shareAccess === 'freebusy') return 'freebusy'
  if (shareAccess === 'admin') return 'admin'
  if (!access) return 'read'
  const accessObj = access as Record<string, unknown>
  if (accessObj['read-write'] || accessObj['readWrite']) return 'read-write'
  return 'read'
}

export type ShareeXmlParams = {
  href: string
  displayName?: string
  privilege: SharePrivilege
}

/** Build share set XML for a single sharee.
 *
 * Always emits an ``<LS:share-access>`` element so the backend knows
 * the precise logical level — including the empty case which signals
 * "this is a plain CS:read or CS:read-write, clear any previous
 * override". Without that marker the backend's afterPost hook would
 * leave a stale ``share_access_level`` row pinned to its previous
 * value (e.g. a sharee being moved from ``freebusy`` back to ``read``
 * would still read back as ``freebusy``).
 */
export function buildShareeSetXml(params: ShareeXmlParams): string {
  const privilege = sharePrivilegeToXml(params.privilege)
  const commonName = params.displayName
    ? `<CS:common-name>${escapeXml(params.displayName)}</CS:common-name>`
    : ''
  const overrideLevel =
    params.privilege === 'freebusy' ? 'freebusy'
    : params.privilege === 'admin' ? 'admin'
    : ''
  const shareAccess = `<LS:share-access>${overrideLevel}</LS:share-access>`

  return `
    <CS:set>
      <D:href>${escapeXml(params.href)}</D:href>
      ${commonName}
      ${shareAccess}
      ${privilege}
    </CS:set>`
}

/** Build CS:share request body */
export function buildShareRequestXml(sharees: ShareeXmlParams[]): string {
  const shareesXml = sharees.map(buildShareeSetXml).join('')
  return `<?xml version="1.0" encoding="utf-8"?>
<CS:share ${XML_NS.DAV} ${XML_NS.CS} ${XML_NS.LS}>
  ${shareesXml}
</CS:share>`
}

/** Build CS:share remove request body */
export function buildUnshareRequestXml(shareeHref: string): string {
  return `<?xml version="1.0" encoding="utf-8"?>
<CS:share ${XML_NS.DAV} ${XML_NS.CS}>
  <CS:remove>
    <D:href>${escapeXml(shareeHref)}</D:href>
  </CS:remove>
</CS:share>`
}

/** Build invite-reply request body */
export function buildInviteReplyXml(inReplyTo: string, accept: boolean): string {
  return `<?xml version="1.0" encoding="utf-8"?>
<CS:invite-reply ${XML_NS.DAV} ${XML_NS.CS}>
  <CS:in-reply-to>${escapeXml(inReplyTo)}</CS:in-reply-to>
  <CS:invite-${accept ? 'accepted' : 'declined'}/>
</CS:invite-reply>`
}

// ============================================================================
// Sync XML Builders
// ============================================================================

export type SyncCollectionParams = {
  syncToken: string
  syncLevel?: number | 'infinite'
}

/** Build sync-collection REPORT body */
export function buildSyncCollectionXml(params: SyncCollectionParams): string {
  return `<?xml version="1.0" encoding="utf-8"?>
<D:sync-collection ${XML_NS.DAV} ${XML_NS.CALDAV}>
  <D:sync-token>${escapeXml(params.syncToken)}</D:sync-token>
  <D:sync-level>${params.syncLevel ?? 1}</D:sync-level>
  <D:prop>
    <D:getetag/>
    <C:calendar-data/>
  </D:prop>
</D:sync-collection>`
}

// ============================================================================
// Principal Search XML Builder
// ============================================================================

/** Build principal-property-search REPORT body */
export function buildPrincipalSearchXml(query: string): string {
  return `<?xml version="1.0" encoding="utf-8"?>
<D:principal-property-search ${XML_NS.DAV}>
  <D:property-search>
    <D:prop>
      <D:displayname/>
    </D:prop>
    <D:match>${escapeXml(query)}</D:match>
  </D:property-search>
  <D:prop>
    <D:displayname/>
    <C:calendar-home-set ${XML_NS.CALDAV}/>
  </D:prop>
</D:principal-property-search>`
}

// ============================================================================
// DAV Request Helpers
// ============================================================================

export type DavRequestOptions = {
  url: string
  method: AllowedMethods
  body: string
  headers?: Record<string, string>
  fetchOptions?: RequestInit
  contentType?: string
}

/** Redirect to login if a response indicates an expired session. */
function handleAuthError(status: number | undefined) {
  if (status === 401) {
    // Dynamic import to avoid circular dependencies
    import("@/features/api/fetchApi").then(({ redirectToLogin }) =>
      redirectToLogin(),
    );
  }
}

/** Execute a DAV request with standard error handling */
export async function executeDavRequest(options: DavRequestOptions): Promise<CalDavResponse> {
  try {
    // Use fetch directly for methods that davRequest doesn't handle well
    // POST is included because CalDAV sharing requires specific Content-Type handling
    const useDirectFetch = ['PROPPATCH', 'DELETE', 'POST'].includes(options.method);

    if (useDirectFetch) {
      const response = await fetch(options.url, {
        method: options.method,
        headers: {
          'Content-Type': options.contentType ?? 'application/xml; charset=utf-8',
          ...options.headers,
        },
        body: options.body || undefined,
        ...options.fetchOptions,
      });

      if (!response.ok && response.status !== 204 && response.status !== 207) {
        handleAuthError(response.status);
        const errorText = await response.text().catch(() => '');
        console.error(`[CalDAV] ${options.method} request failed:`, {
          url: options.url,
          status: response.status,
          error: errorText,
        });
        // Prefer the SabreDAV ``<s:message>`` over the raw XML body so
        // users see "This sharee is managed by Messages..." instead of
        // a wall of escaped angle brackets.
        const friendly = parseDavErrorMessage(errorText);
        return {
          success: false,
          error: friendly
            ? `Request failed: ${response.status} ${friendly}`
            : `Request failed: ${response.status} ${errorText}`,
          status: response.status,
        };
      }

      return { success: true };
    }

    // Use davRequest for standard WebDAV methods
    const responses = await davRequest({
      url: options.url,
      init: {
        method: options.method as DAVMethods,
        headers: {
          'Content-Type': options.contentType ?? 'application/xml; charset=utf-8',
          ...options.headers,
        },
        body: options.body,
      },
      fetchOptions: options.fetchOptions,
    })

    const response = responses[0]
    if (!response?.ok && response?.status !== 204) {
      handleAuthError(response?.status);
      return {
        success: false,
        error: `Request failed: ${response?.status}`,
        status: response?.status,
      }
    }

    return { success: true }
  } catch (error) {
    return {
      success: false,
      error: `Request failed: ${error instanceof Error ? error.message : String(error)}`,
    }
  }
}

/** Standard PROPFIND props for calendar fetching.
 *
 * Includes ``CS:invite`` so the parsed calendar already carries:
 *   - The owner principal (used to derive the mailbox email when
 *     ``LS:calendar-owner-type`` is ``MAILBOX``).
 *   - The list of sharees, so the share modal can render without a
 *     second PROPFIND round-trip.
 *
 * ``LS:share-access-map`` is fetched alongside because freebusy/admin
 * levels are not expressible via the standard CalendarServer access
 * tokens — ``parseSharePrivilege`` needs the override map to round-trip
 * those levels correctly.
 */
export const CALENDAR_PROPS = {
  [`${DAVNamespaceShort.CALDAV}:calendar-description`]: {},
  [`${DAVNamespaceShort.CALDAV}:calendar-timezone`]: {},
  [`${DAVNamespaceShort.DAV}:displayname`]: {},
  [`${DAVNamespaceShort.CALDAV_APPLE}:calendar-color`]: {},
  [`${DAVNamespaceShort.CALENDAR_SERVER}:getctag`]: {},
  [`${DAVNamespaceShort.DAV}:resourcetype`]: {},
  [`${DAVNamespaceShort.CALDAV}:supported-calendar-component-set`]: {},
  [`${DAVNamespaceShort.DAV}:sync-token`]: {},
  [`${DAVNamespaceShort.CALDAV}:schedule-calendar-transp`]: {},
  [`${DAVNamespaceShort.CALENDAR_SERVER}:invite`]: {},
  'LS:calendar-owner-type': {},
  'LS:share-access-map': {},
} as const

/**
 * Drop-in replacement for tsdav's ``propfind()`` that also declares
 * ``xmlns:LS=...`` on the root ``<propfind>`` element.
 *
 * tsdav's built-in ``propfind()`` hardcodes the xmlns map and has no
 * extension point for custom namespaces, so any ``LS:<prop>`` we put in
 * the props object would be serialized as ``<LS:foo/>`` in a body that
 * never declared the prefix — SabreDAV rejects it with
 * ``BadRequest: Namespace prefix LS is not defined``.
 *
 * This wrapper mirrors tsdav's body shape exactly so the response
 * shape matches what callers already expect (camelCased keys with
 * namespace prefixes stripped).
 */
export async function propfindLs(params: {
  url: string
  props: Record<string, unknown>
  depth?: '0' | '1' | 'infinity'
  headers?: Record<string, string>
  fetchOptions?: RequestInit
}) {
  return davRequest({
    url: params.url,
    init: {
      method: 'PROPFIND' as DAVMethods,
      headers: { depth: params.depth ?? '0', ...params.headers },
      namespace: DAVNamespaceShort.DAV,
      body: {
        propfind: {
          _attributes: {
            'xmlns:c': 'urn:ietf:params:xml:ns:caldav',
            'xmlns:ca': 'http://apple.com/ns/ical/',
            'xmlns:cs': 'http://calendarserver.org/ns/',
            'xmlns:card': 'urn:ietf:params:xml:ns:carddav',
            'xmlns:d': 'DAV:',
            'xmlns:LS': 'http://lasuite.numerique.gouv.fr/ns/',
          },
          prop: params.props,
        },
      },
    },
    fetchOptions: params.fetchOptions,
  })
}

/** Execute PROPFIND with error handling */
export async function executePropfind<T>(
  url: string,
  props: Record<string, unknown>,
  options?: {
    headers?: Record<string, string>
    fetchOptions?: RequestInit
    depth?: '0' | '1' | 'infinity'
  }
): Promise<CalDavResponse<T>> {
  try {
    const response = await propfindLs({
      url,
      props,
      headers: options?.headers,
      fetchOptions: options?.fetchOptions,
      depth: options?.depth ?? '0',
    })

    const rs = response[0]
    if (!rs.ok) {
      return {
        success: false,
        error: `PROPFIND failed: ${rs.status}`,
        status: rs.status,
      }
    }

    return { success: true, data: rs.props as T }
  } catch (error) {
    return {
      success: false,
      error: `PROPFIND failed: ${error instanceof Error ? error.message : String(error)}`,
    }
  }
}

// ============================================================================
// Response Parsing Helpers
// ============================================================================

/** Parse supported-calendar-component-set from PROPFIND response */
export function parseCalendarComponents(supportedCalendarComponentSet: unknown): string[] | undefined {
  if (!supportedCalendarComponentSet) return undefined

  const comp = (supportedCalendarComponentSet as Record<string, unknown>).comp
  if (Array.isArray(comp)) {
    return comp
      .map((sc: Record<string, unknown>) => (sc._attributes as Record<string, string>)?.name)
      .filter(Boolean)
  }
  const name = (comp as Record<string, unknown>)?._attributes as Record<string, string> | undefined
  return name?.name ? [name.name] : undefined
}

/** Parse share status from invite response */
export function parseShareStatus(
  accepted: unknown,
  noResponse: unknown
): 'pending' | 'accepted' | 'declined' {
  if (accepted) return 'accepted'
  if (noResponse) return 'pending'
  return 'declined'
}

/**
 * Extract the human-readable ``<s:message>`` from a SabreDAV-style
 * XML error body. Returns ``undefined`` when the body is empty,
 * malformed, missing the ``s:message`` element, or whitespace-only.
 *
 * Background: SabreDAV serialises errors as
 * ``<d:error xmlns:d="DAV:" xmlns:s="http://sabredav.org/ns">
 *   <s:exception>...</s:exception>
 *   <s:message>human-readable text</s:message>
 *  </d:error>``
 * Surfacing the raw XML to the user is unhelpful — the message child
 * is what we actually want to display.
 *
 * Uses ``xml-js``'s ``xml2js`` (the same parser tsdav itself uses
 * internally), with namespace prefixes stripped so ``<s:message>``
 * lands at ``parsed.error.message`` regardless of which prefix the
 * server happens to bind. Works in both browser and ``node``
 * jest environments — no ``DOMParser`` dependency.
 *
 * Safe to render in React: the value is plain text from our own
 * SabreDAV server (not user-supplied), and ``server.php``'s exception
 * handler already masks any non-DAV exception's message as
 * ``Internal server error`` so internal details (DB errors, file
 * paths, SQL state) cannot leak through this channel.
 */
export function parseDavErrorMessage(xmlBody: string): string | undefined {
  if (!xmlBody) return undefined
  let parsed: ElementCompact
  try {
    parsed = xml2js(xmlBody, {
      compact: true,
      trim: true,
      // Strip namespace prefixes (``s:message`` → ``message``) so the
      // resulting object is prefix-agnostic. Mirrors how tsdav parses
      // its own DAV responses internally.
      elementNameFn: (name) => name.replace(/^.+:/, ''),
    }) as ElementCompact
  } catch {
    return undefined
  }
  const error = parsed.error as ElementCompact | undefined
  const messageNode = error?.message as ElementCompact | ElementCompact[] | undefined
  if (!messageNode) return undefined
  // xml-js compact mode: multiple same-named children → array.
  const first = Array.isArray(messageNode) ? messageNode[0] : messageNode
  const text = first?._text
  if (typeof text !== 'string') return undefined
  const trimmed = text.trim()
  return trimmed ? trimmed : undefined
}

/**
 * Build the ``href → access`` map from a parsed ``LS:share-access-map``
 * payload. The plugin emits ``<LS:sharee href="..." access="..."/>``
 * with attributes (not child elements), and tsdav lands those under
 * ``_attributes`` in xml-js compact mode. Used to recover ``freebusy``
 * and ``admin`` levels that the standard CalendarServer ``access``
 * tokens cannot express.
 */
export function parseShareAccessMap(rawMap: unknown): Map<string, string> {
  const accessMap = new Map<string, string>()
  if (!rawMap) return accessMap
  const map = rawMap as Record<string, unknown>
  const sharees = Array.isArray(map.sharee)
    ? map.sharee
    : map.sharee
      ? [map.sharee]
      : []
  for (const s of sharees) {
    const sharee = s as Record<string, unknown>
    const attrs = (sharee._attributes as Record<string, string> | undefined)
      ?? (sharee as Record<string, string>)
    const href = attrs?.href
    const access = attrs?.access
    if (href && access) {
      accessMap.set(href, access)
    }
  }
  return accessMap
}

/**
 * Parse the ``CS:invite`` payload returned by SabreDAV for a calendar
 * collection into the typed sharee list the UI uses. ``rawAccessMap``
 * is the matching ``LS:share-access-map`` payload (may be undefined).
 *
 * Returns ``[]`` when no invite is present.
 */
export function parseInviteSharees(
  rawInvite: unknown,
  rawAccessMap?: unknown,
): SharePrivilegeAndStatus[] {
  if (!rawInvite) return []
  const invite = rawInvite as Record<string, unknown>
  if (!invite.user) return []
  const accessMap = parseShareAccessMap(rawAccessMap)
  const users = Array.isArray(invite.user) ? invite.user : [invite.user]
  return users.map((u) => {
    const user = u as Record<string, unknown>
    const href = (user.href as string) || ''
    const shareAccess = accessMap.get(href)
    return {
      href,
      displayName: user['common-name'] as string | undefined,
      privilege: parseSharePrivilege(user.access, shareAccess),
      status: parseShareStatus(user['invite-accepted'], user['invite-noresponse']),
    }
  })
}

/** Shape returned by ``parseInviteSharees`` — kept here to avoid a
 *  cycle with ``types/caldav-service``. Identical structure to the
 *  ``CalDavSharee`` re-exported there. */
export type SharePrivilegeAndStatus = {
  href: string
  displayName?: string
  privilege: SharePrivilege
  status: 'pending' | 'accepted' | 'declined'
}

/**
 * Parse the owning principal href from a ``CS:invite`` payload and
 * extract the email out of the principal URI.
 *
 * Used to derive the mailbox email for ``MAILBOX``-owned calendars
 * directly from the standard PROPFIND, with no dependency on the
 * Messages-side ``useMailboxSync`` hydration.
 */
export function parseInviteOrganizerEmail(rawInvite: unknown): string | undefined {
  if (!rawInvite) return undefined
  const organizer = (rawInvite as Record<string, unknown>).organizer as
    | Record<string, unknown>
    | undefined
  const href = organizer?.href as string | undefined
  if (!href) return undefined
  // The href looks like ``/caldav/principals/users/team@example.com``
  // (sometimes with a trailing slash). The email is always the last
  // path segment, URL-decoded.
  const trimmed = href.replace(/\/+$/, '')
  const lastSegment = trimmed.split('/').pop()
  if (!lastSegment) return undefined
  try {
    return decodeURIComponent(lastSegment)
  } catch {
    return lastSegment
  }
}

/** Extract calendar URL from event URL */
export function getCalendarUrlFromEventUrl(eventUrl: string): string {
  const parts = eventUrl.split('/')
  parts.pop() // Remove filename
  return parts.join('/') + '/'
}

/** Extract calendar ID from calendar URL (e.g., /calendars/user/calendar-id/ -> calendar-id) */
export function getCalendarIdFromUrl(calendarUrl: string): string {
  const parts = calendarUrl.replace(/\/$/, '').split('/')
  return parts[parts.length - 1]
}

// ============================================================================
// Error Handling
// ============================================================================

/** Wrap async operation with standard error handling */
export async function withErrorHandling<T>(
  operation: () => Promise<T>,
  errorPrefix: string
): Promise<CalDavResponse<T>> {
  try {
    const data = await operation()
    return { success: true, data }
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    if (message.includes('401')) {
      handleAuthError(401);
    }
    return {
      success: false,
      error: `${errorPrefix}: ${message}`,
    }
  }
}
