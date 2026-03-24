/**
 * CalDAV Helper Functions
 *
 * Factorized utilities for XML building, DAV requests, and error handling.
 */

import { davRequest, propfind, DAVNamespaceShort } from 'tsdav'
import type { DAVMethods } from 'tsdav'

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

/** Freebusy access is stored as read at CalDAV level with a summary marker */
const FREEBUSY_SUMMARY_MARKER = 'access:freebusy'

/** Convert SharePrivilege to CalDAV XML element (freebusy maps to read) */
export function sharePrivilegeToXml(privilege: SharePrivilege): string {
  const map: Record<SharePrivilege, string> = {
    freebusy: '<CS:read/>',
    read: '<CS:read/>',
    'read-write': '<CS:read-write/>',
    admin: '<CS:admin/>',
  }
  return map[privilege] ?? '<CS:read/>'
}

/** Get the summary string to store with a share (encodes freebusy marker) */
export function sharePrivilegeToSummary(privilege: SharePrivilege): string | undefined {
  return privilege === 'freebusy' ? FREEBUSY_SUMMARY_MARKER : undefined
}

/** Parse access object to SharePrivilege, using summary to distinguish freebusy from read.
 *
 * Note: tsdav's XML parser camelCases element names (e.g. cs:read-write -> readWrite),
 * so we check both kebab-case and camelCase variants.
 */
export function parseSharePrivilege(access: unknown, summary?: string): SharePrivilege {
  if (!access) return 'read'
  const accessObj = access as Record<string, unknown>
  if (accessObj['read-write'] || accessObj['readWrite']) return 'read-write'
  if (accessObj['admin']) return 'admin'
  if (summary === FREEBUSY_SUMMARY_MARKER) return 'freebusy'
  return 'read'
}

export type ShareeXmlParams = {
  href: string
  displayName?: string
  privilege: SharePrivilege
  summary?: string
}

/** Build share set XML for a single sharee */
export function buildShareeSetXml(params: ShareeXmlParams): string {
  const privilege = sharePrivilegeToXml(params.privilege)
  const commonName = params.displayName
    ? `<CS:common-name>${escapeXml(params.displayName)}</CS:common-name>`
    : ''
  const summaryValue = params.summary ?? sharePrivilegeToSummary(params.privilege)
  const summary = summaryValue ? `<CS:summary>${escapeXml(summaryValue)}</CS:summary>` : ''

  return `
    <CS:set>
      <D:href>${escapeXml(params.href)}</D:href>
      ${commonName}
      ${summary}
      ${privilege}
    </CS:set>`
}

/** Build CS:share request body */
export function buildShareRequestXml(sharees: ShareeXmlParams[]): string {
  const shareesXml = sharees.map(buildShareeSetXml).join('')
  return `<?xml version="1.0" encoding="utf-8"?>
<CS:share ${XML_NS.DAV} ${XML_NS.CS}>
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
        return {
          success: false,
          error: `Request failed: ${response.status} ${errorText}`,
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

/** Standard PROPFIND props for calendar fetching */
export const CALENDAR_PROPS = {
  [`${DAVNamespaceShort.CALDAV}:calendar-description`]: {},
  [`${DAVNamespaceShort.CALDAV}:calendar-timezone`]: {},
  [`${DAVNamespaceShort.DAV}:displayname`]: {},
  [`${DAVNamespaceShort.CALDAV_APPLE}:calendar-color`]: {},
  [`${DAVNamespaceShort.CALENDAR_SERVER}:getctag`]: {},
  [`${DAVNamespaceShort.DAV}:resourcetype`]: {},
  [`${DAVNamespaceShort.CALDAV}:supported-calendar-component-set`]: {},
  [`${DAVNamespaceShort.DAV}:sync-token`]: {},
} as const

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
    const response = await propfind({
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
