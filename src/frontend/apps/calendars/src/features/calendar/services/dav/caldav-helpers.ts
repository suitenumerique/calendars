/**
 * CalDAV Helper Functions
 *
 * Factorized utilities for XML building, DAV requests, and error handling.
 */

import type { SharePrivilege, CalDavResponse } from "./types/caldav-service";

/** XML namespace prefix lookup used when building prop keys in PROPFIND
 * bodies. Mirrors what tsdav's `DAVNamespaceShort` used to provide; kept
 * here so the rest of the codebase can construct prop names like
 * `${NS.CALDAV}:calendar-availability` without depending on tsdav.
 */
export const NS = {
  DAV: "d",
  CALDAV: "c",
  CALDAV_APPLE: "ca",
  CALENDAR_SERVER: "cs",
  CARDDAV: "card",
} as const;

// ============================================================================
// XML Helpers
// ============================================================================

/** Escape special XML characters */
export function escapeXml(str: string | undefined | null): string {
  if (str === undefined || str === null) {
    return "";
  }
  if (typeof str !== "string") {
    str = String(str);
  }
  return str
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&apos;");
}

/** XML namespaces used in CalDAV */
export const XML_NS = {
  DAV: 'xmlns:D="DAV:"',
  CALDAV: 'xmlns:C="urn:ietf:params:xml:ns:caldav"',
  APPLE: 'xmlns:A="http://apple.com/ns/ical/"',
  CS: 'xmlns:CS="http://calendarserver.org/ns/"',
  LS: 'xmlns:LS="http://lasuite.numerique.gouv.fr/ns/"',
} as const;

/** Build XML prop element */
export function xmlProp(namespace: string, name: string, value: string): string {
  return `<${namespace}:${name}>${escapeXml(value)}</${namespace}:${name}>`;
}

// ============================================================================
// Calendar Property Builders
// ============================================================================

export type CalendarProps = {
  displayName?: string;
  description?: string;
  color?: string;
  /** VTIMEZONE block, sent as `<C:calendar-timezone>`. */
  timezone?: string;
  /**
   * `{http://apple.com/ns/ical/}calendar-order`. Integer used to manually
   * sort calendars in the sidebar; stored as a dead property by Sabre's
   * PropertyStorage.
   */
  order?: number;
  components?: string[];
  /** schedule-calendar-transp: 'opaque' (counts as busy) or 'transparent' */
  scheduleTransp?: "opaque" | "transparent";
};

/** Build calendar property XML elements */
export function buildCalendarPropsXml(props: CalendarProps): string[] {
  const elements: string[] = [];

  if (
    props.displayName !== undefined &&
    props.displayName !== null &&
    typeof props.displayName === "string"
  ) {
    elements.push(xmlProp("D", "displayname", props.displayName));
  }
  if (
    props.description !== undefined &&
    props.description !== null &&
    typeof props.description === "string"
  ) {
    elements.push(xmlProp("C", "calendar-description", props.description));
  }
  if (props.color !== undefined && props.color !== null && typeof props.color === "string") {
    elements.push(xmlProp("A", "calendar-color", props.color));
  }
  if (props.order !== undefined && props.order !== null && typeof props.order === "number") {
    elements.push(xmlProp("A", "calendar-order", String(props.order)));
  }
  if (props.components && props.components.length > 0) {
    const comps = props.components.map((c) => `<C:comp name="${escapeXml(c)}"/>`).join("");
    elements.push(
      `<C:supported-calendar-component-set>${comps}</C:supported-calendar-component-set>`,
    );
  }
  if (typeof props.timezone === "string" && props.timezone.length > 0) {
    elements.push(xmlProp("C", "calendar-timezone", props.timezone));
  }
  if (props.scheduleTransp !== undefined) {
    // RFC 6638: schedule-calendar-transp controls whether this calendar
    // participates in freebusy calculations. Standard CalDAV property.
    const value = props.scheduleTransp === "transparent" ? "<C:transparent/>" : "<C:opaque/>";
    elements.push(`<C:schedule-calendar-transp>${value}</C:schedule-calendar-transp>`);
  }

  return elements;
}

/** Build MKCALENDAR request body */
export function buildMkCalendarXml(props: CalendarProps): string {
  const propsXml = buildCalendarPropsXml(props);
  return `<?xml version="1.0" encoding="utf-8"?>
<C:mkcalendar ${XML_NS.DAV} ${XML_NS.CALDAV} ${XML_NS.APPLE}>
  <D:set>
    <D:prop>
      ${propsXml.join("\n      ")}
    </D:prop>
  </D:set>
</C:mkcalendar>`;
}

/** Build PROPPATCH request body */
export function buildProppatchXml(props: CalendarProps): string {
  const propsXml = buildCalendarPropsXml(props);
  return `<?xml version="1.0" encoding="utf-8"?>
<D:propertyupdate ${XML_NS.DAV} ${XML_NS.CALDAV} ${XML_NS.APPLE}>
  <D:set>
    <D:prop>
      ${propsXml.join("\n      ")}
    </D:prop>
  </D:set>
</D:propertyupdate>`;
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
function sharePrivilegeToXml(privilege: SharePrivilege): string {
  const map: Record<SharePrivilege, string> = {
    freebusy: "<CS:read/>",
    read: "<CS:read/>",
    "read-write": "<CS:read-write/>",
    admin: "<CS:read-write/>",
  };
  return map[privilege] ?? "<CS:read/>";
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
  if (shareAccess === "freebusy") return "freebusy";
  if (shareAccess === "admin") return "admin";
  if (!access) return "read";
  const accessObj = access as Record<string, unknown>;
  if (accessObj["read-write"] || accessObj["readWrite"]) return "read-write";
  return "read";
}

export type ShareeXmlParams = {
  href: string;
  displayName?: string;
  privilege: SharePrivilege;
};

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
function buildShareeSetXml(params: ShareeXmlParams): string {
  const privilege = sharePrivilegeToXml(params.privilege);
  const commonName = params.displayName
    ? `<CS:common-name>${escapeXml(params.displayName)}</CS:common-name>`
    : "";
  const overrideLevel =
    params.privilege === "freebusy" ? "freebusy" : params.privilege === "admin" ? "admin" : "";
  const shareAccess = `<LS:share-access>${overrideLevel}</LS:share-access>`;

  return `
    <CS:set>
      <D:href>${escapeXml(params.href)}</D:href>
      ${commonName}
      ${shareAccess}
      ${privilege}
    </CS:set>`;
}

/** Build CS:share request body */
export function buildShareRequestXml(sharees: ShareeXmlParams[]): string {
  const shareesXml = sharees.map(buildShareeSetXml).join("");
  return `<?xml version="1.0" encoding="utf-8"?>
<CS:share ${XML_NS.DAV} ${XML_NS.CS} ${XML_NS.LS}>
  ${shareesXml}
</CS:share>`;
}

/** Build CS:share remove request body */
export function buildUnshareRequestXml(shareeHref: string): string {
  return `<?xml version="1.0" encoding="utf-8"?>
<CS:share ${XML_NS.DAV} ${XML_NS.CS}>
  <CS:remove>
    <D:href>${escapeXml(shareeHref)}</D:href>
  </CS:remove>
</CS:share>`;
}

// ============================================================================
// Calendar Query XML Builder
// ============================================================================

/** Format a Date or ISO string as CalDAV `YYYYMMDDTHHMMSSZ` (RFC 4791). */
function toCalDavTime(value: Date | string): string {
  const d = typeof value === "string" ? new Date(value) : value;
  const pad = (n: number) => n.toString().padStart(2, "0");
  return (
    `${d.getUTCFullYear()}${pad(d.getUTCMonth() + 1)}${pad(d.getUTCDate())}` +
    `T${pad(d.getUTCHours())}${pad(d.getUTCMinutes())}${pad(d.getUTCSeconds())}Z`
  );
}

type CalendarQueryParams = {
  /** When provided, results are filtered to events overlapping this range. */
  timeRange?: { start: Date | string; end: Date | string };
  /**
   * When true, the server expands recurring events into individual
   * occurrences within `timeRange` (RFC 4791 §9.6.5). Requires `timeRange`.
   */
  expand?: boolean;
};

/** Build a calendar-query REPORT body that fetches `getetag` + `calendar-data`. */
export function buildCalendarQueryXml(params: CalendarQueryParams = {}): string {
  const timeRangeFilter = params.timeRange
    ? `<C:time-range start="${toCalDavTime(params.timeRange.start)}" end="${toCalDavTime(params.timeRange.end)}"/>`
    : "";

  const calendarData =
    params.expand && params.timeRange
      ? `<C:calendar-data><C:expand start="${toCalDavTime(params.timeRange.start)}" end="${toCalDavTime(params.timeRange.end)}"/></C:calendar-data>`
      : "<C:calendar-data/>";

  return `<?xml version="1.0" encoding="utf-8"?>
<C:calendar-query ${XML_NS.DAV} ${XML_NS.CALDAV}>
  <D:prop>
    <D:getetag/>
    ${calendarData}
  </D:prop>
  <C:filter>
    <C:comp-filter name="VCALENDAR">
      <C:comp-filter name="VEVENT">
        ${timeRangeFilter}
      </C:comp-filter>
    </C:comp-filter>
  </C:filter>
</C:calendar-query>`;
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
  [`${NS.CALDAV}:calendar-description`]: {},
  [`${NS.CALDAV}:calendar-timezone`]: {},
  [`${NS.DAV}:displayname`]: {},
  [`${NS.CALDAV_APPLE}:calendar-color`]: {},
  [`${NS.CALDAV_APPLE}:calendar-order`]: {},
  [`${NS.CALENDAR_SERVER}:getctag`]: {},
  [`${NS.DAV}:resourcetype`]: {},
  [`${NS.CALDAV}:supported-calendar-component-set`]: {},
  [`${NS.DAV}:sync-token`]: {},
  [`${NS.CALDAV}:schedule-calendar-transp`]: {},
  [`${NS.CALENDAR_SERVER}:invite`]: {},
  "LS:calendar-owner-type": {},
  "LS:share-access-map": {},
} as const;

// ============================================================================
// Response Parsing Helpers
// ============================================================================

/**
 * Coerce a parsed `calendar-order` PROPFIND value to an integer.
 *
 * tsdav's xml-js parser auto-coerces pure-digit element text to a JS
 * `number`, while non-numeric text stays a `string`. Either shape can
 * arrive depending on what the server stored. Anything else (nullish,
 * object, NaN, ±Infinity) is treated as "no order set" so sorting can
 * fall back to displayName.
 */
export function parseCalendarOrder(raw: unknown): number | undefined {
  if (typeof raw === "number" && Number.isFinite(raw)) {
    return raw;
  }
  if (typeof raw === "string") {
    // Require the entire (trimmed) string to be an optionally-signed
    // integer — otherwise `Number.parseInt` would happily turn "10abc"
    // into 10 and swallow attacker-supplied trailing junk.
    const trimmed = raw.trim();
    if (/^[+-]?\d+$/.test(trimmed)) {
      const n = Number.parseInt(trimmed, 10);
      if (Number.isFinite(n)) return n;
    }
  }
  return undefined;
}

/** Parse supported-calendar-component-set from PROPFIND response */
export function parseCalendarComponents(
  supportedCalendarComponentSet: unknown,
): string[] | undefined {
  if (!supportedCalendarComponentSet) return undefined;

  const comp = (supportedCalendarComponentSet as Record<string, unknown>).comp;
  if (Array.isArray(comp)) {
    return comp
      .map((sc: Record<string, unknown>) => (sc._attributes as Record<string, string>)?.name)
      .filter(Boolean);
  }
  const name = (comp as Record<string, unknown>)?._attributes as Record<string, string> | undefined;
  return name?.name ? [name.name] : undefined;
}

/** Parse share status from invite response */
function parseShareStatus(
  accepted: unknown,
  noResponse: unknown,
): "pending" | "accepted" | "declined" {
  if (accepted) return "accepted";
  if (noResponse) return "pending";
  return "declined";
}

/**
 * Build the ``href → access`` map from a parsed ``LS:share-access-map``
 * payload. The plugin emits ``<LS:sharee href="..." access="..."/>``
 * with attributes (not child elements), and tsdav lands those under
 * ``_attributes`` in xml-js compact mode. Used to recover ``freebusy``
 * and ``admin`` levels that the standard CalendarServer ``access``
 * tokens cannot express.
 */
function parseShareAccessMap(rawMap: unknown): Map<string, string> {
  const accessMap = new Map<string, string>();
  if (!rawMap) return accessMap;
  const map = rawMap as Record<string, unknown>;
  const sharees = Array.isArray(map.sharee) ? map.sharee : map.sharee ? [map.sharee] : [];
  for (const s of sharees) {
    const sharee = s as Record<string, unknown>;
    const attrs =
      (sharee._attributes as Record<string, string> | undefined) ??
      (sharee as Record<string, string>);
    const href = attrs?.href;
    const access = attrs?.access;
    if (href && access) {
      accessMap.set(href, access);
    }
  }
  return accessMap;
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
  if (!rawInvite) return [];
  const invite = rawInvite as Record<string, unknown>;
  if (!invite.user) return [];
  const accessMap = parseShareAccessMap(rawAccessMap);
  const users = Array.isArray(invite.user) ? invite.user : [invite.user];
  return users.map((u) => {
    const user = u as Record<string, unknown>;
    const href = (user.href as string) || "";
    const shareAccess = accessMap.get(href);
    return {
      href,
      displayName: user["common-name"] as string | undefined,
      privilege: parseSharePrivilege(user.access, shareAccess),
      status: parseShareStatus(user["invite-accepted"], user["invite-noresponse"]),
    };
  });
}

/** Shape returned by ``parseInviteSharees`` — kept here to avoid a
 *  cycle with ``types/caldav-service``. Identical structure to the
 *  ``CalDavSharee`` re-exported there. */
type SharePrivilegeAndStatus = {
  href: string;
  displayName?: string;
  privilege: SharePrivilege;
  status: "pending" | "accepted" | "declined";
};

/**
 * Parse the owning principal href from a ``CS:invite`` payload and
 * extract the email out of the principal URI.
 *
 * Used to derive the mailbox email for ``MAILBOX``-owned calendars
 * directly from the standard PROPFIND, with no dependency on the
 * Messages-side ``useMailboxSync`` hydration.
 */
export function parseInviteOrganizerEmail(rawInvite: unknown): string | undefined {
  if (!rawInvite) return undefined;
  const organizer = (rawInvite as Record<string, unknown>).organizer as
    | Record<string, unknown>
    | undefined;
  const href = organizer?.href as string | undefined;
  if (!href) return undefined;
  // The href looks like ``/caldav/principals/users/team@example.com``
  // (sometimes with a trailing slash). The email is always the last
  // path segment, URL-decoded.
  const trimmed = href.replace(/\/+$/, "");
  const lastSegment = trimmed.split("/").pop();
  if (!lastSegment) return undefined;
  try {
    return decodeURIComponent(lastSegment);
  } catch {
    return lastSegment;
  }
}

/** Extract calendar URL from event URL */
export function getCalendarUrlFromEventUrl(eventUrl: string): string {
  const parts = eventUrl.split("/");
  parts.pop(); // Remove filename
  return parts.join("/") + "/";
}

// ============================================================================
// Result wrapper
// ============================================================================

/** Error type that preserves an HTTP status code through `asResult`.
 *
 * Throw this (instead of a bare `Error`) when a DAV call fails so the
 * caller's `CalDavResponse.status` is populated. Lets callers branch on
 * the HTTP status (e.g. retry on 412) without parsing error strings.
 */
export class DavCallError extends Error {
  readonly status?: number;
  constructor(message: string, status?: number) {
    super(message);
    this.name = "DavCallError";
    this.status = status;
  }
}

/** Build a `DavCallError` from a failed `davRequest` result. */
export function davFailure(
  response: { error?: string; status?: number },
  fallback: string,
): DavCallError {
  const message = response.error ?? `${fallback}: ${response.status}`;
  return new DavCallError(message, response.status);
}

/** Run an async operation and pack its outcome into a `CalDavResponse`.
 *
 * Catches throws from the operation body (e.g. `convertIcsCalendar`
 * parse errors, network failures from `fetch`) and turns them into
 * `{ success: false, error }`. HTTP-level errors are already surfaced
 * as `{ success: false, … }` by `davRequest`, so callers should
 * `throw davFailure(result, "...")` inside the operation when a DAV
 * call fails — this wrapper then catches that throw, re-prefixes the
 * message, and preserves the HTTP status for the caller.
 *
 * 401 → redirect-to-login lives inside `davRequest`, not here.
 */
export async function asResult<T>(
  operation: () => Promise<T>,
  errorPrefix: string,
): Promise<CalDavResponse<T>> {
  try {
    const data = await operation();
    return { success: true, data };
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    const status = error instanceof DavCallError ? error.status : undefined;
    return {
      success: false,
      error: `${errorPrefix}: ${message}`,
      status,
    };
  }
}
