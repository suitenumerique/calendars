/**
 * CalDAV client configuration + unified request entry point.
 *
 * `davRequest` is the single function every CalDAV call in the app should go
 * through. It bakes in the shared `X-LS-Client: web` header (which makes the
 * Django proxy drop `WWW-Authenticate: Basic` on 401), `credentials: include`,
 * SabreDAV error-message parsing, multi-status response parsing for
 * PROPFIND/REPORT, and `redirectToLogin` on 401. No code path should call
 * raw `fetch` against `/caldav/` directly.
 *
 * Scope: this client targets our own SabreDAV instance at the URL derived
 * from `getOrigin()`. Service discovery (`.well-known/{caldav}`,
 * `current-user-principal` PROPFIND, `calendar-home-set` lookup — what
 * tsdav's `createAccount` does) is intentionally NOT implemented; the
 * principal and home URLs are derived from the user's email in
 * `CalDavService.connect`. Any future support for third-party CalDAV
 * federation (Apple iCloud, Google CalDAV, Fastmail…) would need to
 * reintroduce that discovery flow.
 *
 * Server defaults assume SabreDAV: `Content-Type: application/xml` (some
 * legacy servers want `text/xml` — switch `requestHeaders["Content-Type"]`
 * below if you ever point this at a non-SabreDAV target).
 */

import { redirectToLogin } from "@/features/api/fetchApi";
import { getOrigin } from "@/features/api/utils";

export const caldavServerUrl = `${getOrigin()}/caldav/`;

const SHARED_HEADERS: Readonly<Record<string, string>> = {
  "X-LS-Client": "web",
};

const SHARED_FETCH_OPTIONS: RequestInit = {
  credentials: "include",
};

const XML_NAMESPACES =
  'xmlns:c="urn:ietf:params:xml:ns:caldav" ' +
  'xmlns:ca="http://apple.com/ns/ical/" ' +
  'xmlns:cs="http://calendarserver.org/ns/" ' +
  'xmlns:card="urn:ietf:params:xml:ns:carddav" ' +
  'xmlns:d="DAV:" ' +
  'xmlns:LS="http://lasuite.numerique.gouv.fr/ns/"';

export type DavMethod =
  | "GET"
  | "PROPFIND"
  | "REPORT"
  | "PUT"
  | "POST"
  | "DELETE"
  | "PROPPATCH"
  | "MKCALENDAR"
  | "MOVE";

/**
 * Map of PROPFIND prop names. Each key becomes a self-closing element under
 * `<d:prop>`. Values are intentionally `Record<string, never>` (`{}` only) —
 * `buildPropfindBody` ignores them. If you need to emit a structured prop
 * body (e.g. `<c:calendar-data><c:expand .../></c:calendar-data>`), pass it
 * as a raw `body` string instead.
 */
export type PropfindProps = Record<string, Record<string, never>>;

export type DavRequestParams = {
  url: string;
  method: DavMethod;
  /**
   * For PROPFIND: structured prop map. Wrapped in a `<d:propfind><d:prop>…</d:prop></d:propfind>`
   * body with the standard xmlns declarations. Mutually exclusive with `body`.
   */
  props?: PropfindProps;
  /** Raw body (XML string, ICS string, or empty). Mutually exclusive with `props`. */
  body?: string;
  /** PROPFIND/REPORT only. */
  depth?: "0" | "1" | "infinity";
  headers?: Record<string, string>;
  fetchOptions?: RequestInit;
  /**
   * Override the Content-Type header. Defaults to `application/xml; charset=utf-8`
   * for everything except GET (where it's dropped).
   */
  contentType?: string;
};

/** Parsed multi-status entry (PROPFIND / REPORT).
 *
 * `props` is intentionally loosely typed: DAV property shapes are
 * inherently dynamic (per-prop element trees with `href`, `_cdata`,
 * nested structures), and the previous tsdav-based API also exposed
 * `any` here. Callers access fields like `props.calendarData`,
 * `props.getetag`, `props.invite['invite-notification']`, etc.
 */
export type DavResponseEntry = {
  href?: string;
  status: number;
  ok: boolean;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  props: Record<string, any>;
  /**
   * `<d:responsedescription>` text on the response, when SabreDAV provides
   * a human-readable summary alongside a multi-status entry (RFC 4918 §11).
   */
  responseDescription?: string;
  /**
   * `<d:error>` block on the response, when SabreDAV signals a per-resource
   * fault (RFC 4918 §11.4). Used by callers that want to surface a more
   * specific cause than just `status`.
   */
  error?: Record<string, unknown>;
};

export type DavRequestResult = {
  success: boolean;
  status: number;
  /**
   * SabreDAV `<s:message>` if present, otherwise the raw response body or a
   * generic message.
   */
  error?: string;
  /** Parsed multi-status responses (PROPFIND / REPORT). */
  responses?: DavResponseEntry[];
  /** Raw response body text (used for GET ICS, schedule-response, error bodies). */
  body?: string;
  /** Response headers, for callers that need ETag etc. */
  responseHeaders?: Headers;
};

const MULTISTATUS_VERBS: ReadonlySet<DavMethod> = new Set([
  "PROPFIND",
  "REPORT",
]);

function isAuthFailure(status: number | undefined): boolean {
  return status === 401;
}

// === XML parsing primitives (native DOMParser) ===
//
// We parse with the browser-native `DOMParser` so nothing ships in the
// bundle and the parser is maintained by browser vendors. Hard rules:
//
//   1. Always parse with `"application/xml"`. `"text/html"` would change
//      the security model (`<script>` becomes executable HTML), so it's
//      pinned to a `const` and never threaded through as a parameter.
//   2. Detect parse failure by the browser's `<parsererror>` element's
//      *namespace*, not by tag name — otherwise a malicious server could
//      sneak a literal `<parsererror>` element into otherwise-valid XML
//      and trick us into treating the body as malformed.
//   3. The result tree is read-only. We extract `localName`, `textContent`,
//      and attribute values into a plain JS shape, then render via React
//      (auto-escaped). No `innerHTML`, no `setAttribute('on*')`, no eval.
//
// External entities, DOCTYPE includes, and billion-laughs are all
// disabled / capped by every shipping browser; we don't need extra
// hardening for the SabreDAV traffic we control end-to-end.

const XML_PARSE_TYPE = "application/xml" as const;
const PARSERERROR_NS =
  "http://www.mozilla.org/newlayout/xml/parsererror.xml";
const DAV_NS = "DAV:";
const SABREDAV_NS = "http://sabredav.org/ns";

function safeParseXml(xml: string): Document | undefined {
  if (!xml) return undefined;
  let doc: Document;
  try {
    doc = new DOMParser().parseFromString(xml, XML_PARSE_TYPE);
  } catch {
    return undefined;
  }
  if (doc.getElementsByTagNameNS(PARSERERROR_NS, "parsererror").length > 0) {
    return undefined;
  }
  return doc;
}

/**
 * Extract the SabreDAV `<s:message>` from a DAV error body.
 *
 * Safe to render in React: the value is plain text from our own SabreDAV
 * server, and `server.php`'s exception handler already masks any
 * non-DAV exception as `Internal server error` so internal details
 * (DB errors, file paths, SQL state) cannot leak through this channel.
 */
export function parseDavErrorMessage(xmlBody: string): string | undefined {
  const doc = safeParseXml(xmlBody);
  if (!doc) return undefined;
  const text = doc
    .getElementsByTagNameNS(SABREDAV_NS, "message")[0]
    ?.textContent?.trim();
  return text ? text : undefined;
}

/** Build the PROPFIND XML body. Each key in `props` becomes a self-closing
 * element under `<d:prop>` — keys are expected to carry their own namespace
 * prefix (e.g. `c:calendar-availability`, `LS:share-access-map`).
 *
 * Exported for tests; production callers should use `davRequest({props})`.
 */
export function buildPropfindBody(props: Record<string, unknown>): string {
  const propElements = Object.keys(props)
    .map((key) => {
      // Defensive: enforce the `prefix:local-name` (or `local-name`) shape so
      // a future caller can't accidentally inject `</prop><evil-element/>`
      // by feeding user-controlled strings as PROPFIND keys. All in-tree
      // callers pass hardcoded XML names that match this pattern.
      if (!/^(?:[A-Za-z][A-Za-z0-9_-]*:)?[A-Za-z][A-Za-z0-9_-]*$/.test(key)) {
        throw new Error(`Invalid PROPFIND prop name: ${key}`);
      }
      return `<${key}/>`;
    })
    .join("");
  return (
    `<?xml version="1.0" encoding="utf-8"?>` +
    `<d:propfind ${XML_NAMESPACES}>` +
    `<d:prop>${propElements}</d:prop>` +
    `</d:propfind>`
  );
}

// `calendar-data` -> `calendarData`, `schedule-outbox-URL` -> `scheduleOutboxURL`.
// We swallow the hyphen before *any* next character so `-URL` (already
// uppercase) is preserved; CalDavService accesses
// `props.scheduleOutboxURL` and depends on this shape.
function toCamel(name: string): string {
  return name.replace(/-(.)/g, (_, ch: string) => ch.toUpperCase());
}

function parseStatusLine(text: string | null | undefined): number | undefined {
  const m = text?.match(/HTTP\/[\d.]+ (\d+)/);
  return m ? Number.parseInt(m[1], 10) : undefined;
}

// Walk a DOM element into the plain JS shape callers consume, e.g.
// `props.scheduleOutboxURL.href`, `props.invite['invite-notification']`.
//
// Rules (mirrors what xml-js's compact mode gave us; verified by the
// `parseMultistatus` test suite):
//   - Element local names are camelCased (`calendar-data` → `calendarData`).
//   - A leaf element with text content collapses to that string,
//     trimmed: `<d:displayname>Calendar A</d:displayname>` → `"Calendar A"`.
//   - An empty element (`<x/>`) collapses to `{}` so callers can do
//     `if (props.somePreCondition)`-style detection.
//   - An element with attributes hoists them as direct keys, alongside
//     any child elements. `<x href="…" access="…"/>` → `{href, access}`.
//   - Repeated sibling element names → array.
//   - xmlns attributes are skipped (they're transport, not data).
function elementToProps(el: Element): Record<string, unknown> {
  const out: Record<string, unknown> = {};
  for (const child of Array.from(el.children)) {
    const key = toCamel(child.localName);
    const value = elementToValue(child);
    const existing = out[key];
    if (existing === undefined) {
      out[key] = value;
    } else if (Array.isArray(existing)) {
      existing.push(value);
    } else {
      out[key] = [existing, value];
    }
  }
  return out;
}

function elementToValue(el: Element): unknown {
  const attrs: Record<string, string> = {};
  let hasAttrs = false;
  for (const attr of Array.from(el.attributes)) {
    if (attr.name === "xmlns" || attr.name.startsWith("xmlns:")) continue;
    attrs[attr.name] = attr.value;
    hasAttrs = true;
  }
  const hasChildren = el.children.length > 0;

  if (!hasChildren && !hasAttrs) {
    const text = el.textContent?.trim() ?? "";
    // Empty leaf → `{}` so callers can detect presence via key existence;
    // non-empty leaf collapses to the string.
    return text === "" ? {} : text;
  }

  const obj: Record<string, unknown> = { ...attrs };
  if (hasChildren) Object.assign(obj, elementToProps(el));
  return obj;
}

/** Parse a 207 multi-status body into per-resource entries.
 *
 * Exported for tests; production callers receive parsed entries via
 * `davRequest(...).responses`.
 */
export function parseMultistatus(xml: string): DavResponseEntry[] {
  const doc = safeParseXml(xml);
  if (!doc) return [];

  const root = doc.documentElement;
  if (!root || root.localName !== "multistatus") return [];

  const responses = Array.from(
    root.getElementsByTagNameNS(DAV_NS, "response"),
  );

  return responses.map((resp): DavResponseEntry => {
    const href =
      resp.getElementsByTagNameNS(DAV_NS, "href")[0]?.textContent?.trim() ??
      undefined;

    // Only look at *direct* propstat children — `<d:error>` nesting can
    // legally contain its own `<d:status>` and we don't want to pull
    // that into the response-level status.
    const propstats = Array.from(resp.children).filter(
      (c) => c.namespaceURI === DAV_NS && c.localName === "propstat",
    );

    let combinedProps: Record<string, unknown> = {};
    let firstStatus: number | undefined;
    for (const ps of propstats) {
      const statusEl = Array.from(ps.children).find(
        (c) => c.namespaceURI === DAV_NS && c.localName === "status",
      );
      const status = parseStatusLine(statusEl?.textContent) ?? 200;
      if (firstStatus === undefined) firstStatus = status;
      if (status >= 200 && status < 300) {
        const propEl = Array.from(ps.children).find(
          (c) => c.namespaceURI === DAV_NS && c.localName === "prop",
        );
        if (propEl) {
          combinedProps = { ...combinedProps, ...elementToProps(propEl) };
        }
      }
    }

    // Response-level status fallback (some servers emit it directly
    // inside <d:response> when there's nothing to enumerate).
    if (firstStatus === undefined) {
      const directStatus = Array.from(resp.children).find(
        (c) => c.namespaceURI === DAV_NS && c.localName === "status",
      );
      firstStatus = parseStatusLine(directStatus?.textContent) ?? 200;
    }

    // RFC 4918 §11.5
    const respDescEl = Array.from(resp.children).find(
      (c) =>
        c.namespaceURI === DAV_NS && c.localName === "responsedescription",
    );
    const responseDescription = respDescEl?.textContent?.trim() || undefined;

    // RFC 4918 §11.4 — normalize the <d:error> subtree like any prop.
    const respErrorEl = Array.from(resp.children).find(
      (c) => c.namespaceURI === DAV_NS && c.localName === "error",
    );
    const responseError = respErrorEl ? elementToProps(respErrorEl) : undefined;

    const ok = firstStatus >= 200 && firstStatus < 300;
    return {
      href,
      status: firstStatus,
      ok,
      props: combinedProps,
      responseDescription,
      error: responseError,
    };
  });
}

export async function davRequest(
  params: DavRequestParams,
): Promise<DavRequestResult> {
  const mergedFetchOptions: RequestInit = {
    ...SHARED_FETCH_OPTIONS,
    ...params.fetchOptions,
  };
  const mergedHeaders: Record<string, string> = {
    ...SHARED_HEADERS,
    ...params.headers,
  };

  const requestHeaders: Record<string, string> = { ...mergedHeaders };
  if (params.method !== "GET") {
    requestHeaders["Content-Type"] =
      params.contentType ?? "application/xml; charset=utf-8";
  }
  if (params.depth) {
    requestHeaders.Depth = params.depth;
  }

  const body =
    params.method === "PROPFIND" && params.props
      ? buildPropfindBody(params.props)
      : params.body;

  try {
    const response = await fetch(params.url, {
      ...mergedFetchOptions,
      method: params.method,
      headers: requestHeaders,
      body: body && body.length > 0 ? body : undefined,
    });

    // `Response.ok` is true for 200-299, so 204 and 207 are both already
    // captured. No extra guards needed.
    if (!response.ok) {
      if (isAuthFailure(response.status)) {
        redirectToLogin();
      }
      const errorBody = await response.text().catch(() => "");
      const friendly = parseDavErrorMessage(errorBody);
      return {
        success: false,
        status: response.status,
        error: friendly ?? errorBody ?? `Request failed: ${response.status}`,
        body: errorBody,
        responseHeaders: response.headers,
      };
    }

    // 204 No Content has no body; everything else (GET ICS, POST
    // schedule-response, multistatus, etc.) may carry payload.
    const responseBody =
      response.status === 204
        ? undefined
        : await response.text().catch(() => undefined);

    // Defensive: only attempt multistatus parsing if the server actually
    // sent XML. A misconfigured backend that returns `text/html` with a
    // 207 would otherwise be parsed as garbage; signalling `undefined`
    // lets the caller distinguish "no resources" from "could not parse".
    const contentType = response.headers.get("content-type") ?? "";
    const looksXml = /xml/i.test(contentType);
    const responses =
      MULTISTATUS_VERBS.has(params.method) && responseBody && looksXml
        ? parseMultistatus(responseBody)
        : undefined;

    return {
      success: true,
      status: response.status,
      body: responseBody,
      responseHeaders: response.headers,
      responses,
    };
  } catch (error) {
    return {
      success: false,
      status: 0,
      error: error instanceof Error ? error.message : String(error),
    };
  }
}
