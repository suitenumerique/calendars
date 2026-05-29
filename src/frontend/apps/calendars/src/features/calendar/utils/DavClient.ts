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

import { xml2js, type ElementCompact } from "xml-js";

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
  /** Raw xml-js node — useful for callers that need to dig deeper. */
  raw?: unknown;
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

/**
 * Extract the SabreDAV `<s:message>` from a DAV error body.
 *
 * Uses `xml-js` with namespace prefixes stripped so `<s:message>` lands
 * at `parsed.error.message` regardless of which prefix the server emits.
 * Works in both browser and `jest` (no `DOMParser` dependency).
 *
 * Safe to render in React: the value is plain text from our own SabreDAV
 * server, and `server.php`'s exception handler already masks any
 * non-DAV exception as `Internal server error` so internal details
 * (DB errors, file paths, SQL state) cannot leak through this channel.
 */
export function parseDavErrorMessage(xmlBody: string): string | undefined {
  if (!xmlBody) return undefined;
  let parsed: ElementCompact;
  try {
    parsed = xml2js(xmlBody, {
      compact: true,
      trim: true,
      elementNameFn: (name: string) => name.replace(/^.+:/, ""),
    }) as ElementCompact;
  } catch {
    return undefined;
  }
  const error = parsed.error as ElementCompact | undefined;
  const messageNode = error?.message as
    | ElementCompact
    | ElementCompact[]
    | undefined;
  if (!messageNode) return undefined;
  const first = Array.isArray(messageNode) ? messageNode[0] : messageNode;
  const text = first?._text;
  if (typeof text !== "string") return undefined;
  const trimmed = text.trim();
  return trimmed ? trimmed : undefined;
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

// Strip any `prefix:` from an element name.
function stripPrefix(name: string): string {
  const idx = name.indexOf(":");
  return idx >= 0 ? name.slice(idx + 1) : name;
}

// `calendar-data` -> `calendarData`, `schedule-outbox-URL` -> `scheduleOutboxURL`.
// We swallow the hyphen before *any* next character so `-URL` (already
// uppercase) is preserved; CalDavService accesses
// `props.scheduleOutboxURL` and depends on this shape.
function toCamel(name: string): string {
  return name.replace(/-(.)/g, (_, ch: string) => ch.toUpperCase());
}

// Recursively normalize an xml-js ElementCompact node into the
// camelCase / prefix-stripped shape callers consume (e.g.
// `props.calendarData`, `props.getetag`, `props.scheduleOutboxURL`).
function normalizeNode(node: ElementCompact): unknown {
  const out: Record<string, unknown> = {};
  if (node._attributes) out._attributes = node._attributes;
  if (node._text !== undefined) out._text = node._text;
  if (node._cdata !== undefined) out._cdata = node._cdata;

  for (const [rawKey, value] of Object.entries(node)) {
    if (rawKey.startsWith("_")) continue;
    const localKey = toCamel(stripPrefix(rawKey));
    const normalized = Array.isArray(value)
      ? value.map((v) => normalizeNode(v as ElementCompact))
      : normalizeNode(value as ElementCompact);
    out[localKey] = normalized;
  }

  const keys = Object.keys(out);
  if (keys.length === 1 && keys[0] === "_text") {
    return out._text;
  }
  return out;
}

function asArray<T>(value: T | T[] | undefined): T[] {
  if (value === undefined) return [];
  return Array.isArray(value) ? value : [value];
}

/** Parse a 207 multi-status body into per-resource entries.
 *
 * Exported for tests; production callers receive parsed entries via
 * `davRequest(...).responses`.
 */
export function parseMultistatus(xml: string): DavResponseEntry[] {
  let parsed: ElementCompact;
  try {
    parsed = xml2js(xml, {
      compact: true,
      ignoreDeclaration: true,
      ignoreInstruction: true,
      ignoreComment: true,
      ignoreDoctype: true,
    }) as ElementCompact;
  } catch {
    return [];
  }

  const root = (parsed["d:multistatus"] ?? parsed["multistatus"]) as
    | ElementCompact
    | undefined;
  if (!root) return [];

  const responses = asArray(
    (root["d:response"] ?? root["response"]) as
      | ElementCompact
      | ElementCompact[]
      | undefined,
  );

  return responses.map((resp): DavResponseEntry => {
    const hrefNode = (resp["d:href"] ?? resp["href"]) as
      | ElementCompact
      | undefined;
    const href = (hrefNode?._text ?? hrefNode?._cdata) as string | undefined;

    const propstats = asArray(
      (resp["d:propstat"] ?? resp["propstat"]) as
        | ElementCompact
        | ElementCompact[]
        | undefined,
    );

    let combinedProps: Record<string, unknown> = {};
    let firstStatus: number | undefined;
    for (const ps of propstats) {
      const propNode = (ps["d:prop"] ?? ps["prop"]) as
        | ElementCompact
        | undefined;
      const statusNode = (ps["d:status"] ?? ps["status"]) as
        | ElementCompact
        | undefined;
      const statusText = (statusNode?._text ?? statusNode?._cdata) as
        | string
        | undefined;
      const statusMatch = statusText?.match(/HTTP\/[\d.]+ (\d+)/);
      const status = statusMatch ? Number.parseInt(statusMatch[1], 10) : 200;
      if (firstStatus === undefined) firstStatus = status;
      if (propNode && status >= 200 && status < 300) {
        const normalized = normalizeNode(propNode) as Record<string, unknown>;
        combinedProps = { ...combinedProps, ...normalized };
      }
    }

    // Some servers emit `<d:status>` at the response level instead of
    // inside a propstat (e.g. 207 with a single 404 for a non-existent
    // resource). Fall back to that when no propstat statuses applied.
    if (firstStatus === undefined) {
      const respStatusNode = (resp["d:status"] ?? resp["status"]) as
        | ElementCompact
        | undefined;
      const statusText = (respStatusNode?._text ?? respStatusNode?._cdata) as
        | string
        | undefined;
      const m = statusText?.match(/HTTP\/[\d.]+ (\d+)/);
      firstStatus = m ? Number.parseInt(m[1], 10) : 200;
    }

    // RFC 4918 §11.5 — per-resource `<d:responsedescription>` carries a
    // human-readable summary; useful for surfacing a specific cause when
    // a write fails inside a 207.
    const respDescNode = (resp["d:responsedescription"] ??
      resp["responsedescription"]) as ElementCompact | undefined;
    const responseDescription = (
      respDescNode?._text ?? respDescNode?._cdata
    ) as string | undefined;

    // RFC 4918 §11.4 — per-resource `<d:error>` block. Surface it normalized
    // so callers can switch on the precondition name.
    const respErrorNode = (resp["d:error"] ?? resp["error"]) as
      | ElementCompact
      | undefined;
    const responseError = respErrorNode
      ? (normalizeNode(respErrorNode) as Record<string, unknown>)
      : undefined;

    const ok = firstStatus >= 200 && firstStatus < 300;
    return {
      href,
      status: firstStatus,
      ok,
      props: combinedProps,
      responseDescription,
      error: responseError,
      raw: resp,
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
