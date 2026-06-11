/**
 * CalDavService - Pure CalDAV client service
 *
 * This service provides a clean, framework-agnostic interface for CalDAV operations.
 * It handles calendars, events, sharing, scheduling, and ACL management.
 *
 * NOT coupled to EventCalendar - use EventCalendarAdapter for conversions.
 */

import {
  convertIcsCalendar,
  convertIcsTimezone,
  generateIcsCalendar,
  type IcsCalendar,
  type IcsDateObject,
  type IcsEvent,
} from "ts-ics";
import { davRequest } from "@/features/calendar/utils/DavClient";
import type {
  CalDavCredentials,
  CalDavAccount,
  CalDavCalendar,
  CalDavCalendarCreate,
  CalDavCalendarUpdate,
  CalDavEvent,
  CalDavEventCreate,
  CalDavEventUpdate,
  CalDavEventMove,
  EventFilter,
  CalDavShareInvite,
  CalDavShareResponse,
  CalDavResponse,
  FreeBusyRequest,
  FreeBusyResponse,
  SchedulingResponse,
  CalDavAttendee,
} from "./types/caldav-service";

import {
  buildProppatchXml,
  buildShareRequestXml,
  buildUnshareRequestXml,
  buildMkCalendarXml,
  buildCalendarQueryXml,
  escapeXml,
  CALENDAR_PROPS,
  NS,
  parseCalendarComponents,
  parseInviteSharees,
  parseInviteOrganizerEmail,
  parseCalendarOrder,
  getCalendarUrlFromEventUrl,
  asResult,
  davFailure,
  type ShareeXmlParams,
  type CalendarProps,
} from "./caldav-helpers";
import { getIcalTimezoneBlock } from "./helpers/ical-timezones";
import { buildFreeBusyRequestIcs } from "./helpers/freebusy-builder";

/** Resolve an ICS date to its authoritative wall-clock instant. When a
 * TZID is present `local.date` is the wall-clock value; otherwise fall
 * back to `date` (real UTC). Mirrors getResolvedUntilDate in the editor. */
function resolvedInstant(d: IcsDateObject | null | undefined): number | undefined {
  const date = d?.local?.date ?? d?.date;
  return date instanceof Date ? date.getTime() : undefined;
}

// Order-independent structural compare. `JSON.stringify` is sensitive to
// key insertion order, and the old (parsed-from-server) and new (built-by-
// form) events take different code paths through ts-ics, so their objects
// can carry the same data in a different key order. Canonicalize by sorting
// keys recursively before comparing so a pure reordering is NOT mistaken for
// a real change (which would wrongly reset every attendee's response).
function canonical(value: unknown): string {
  return JSON.stringify(value, function replacer(_key, val) {
    if (val && typeof val === "object" && !Array.isArray(val)) {
      return Object.keys(val as Record<string, unknown>)
        .sort()
        .reduce<Record<string, unknown>>((acc, k) => {
          acc[k] = (val as Record<string, unknown>)[k];
          return acc;
        }, {});
    }
    return val;
  });
}

/**
 * Decide whether an edit reschedules the event in the RFC 6638 sense —
 * a change to DTSTART, DTEND, DURATION or RRULE (i.e. the timing), or a
 * switch between all-day and timed. Title/description/location edits are
 * NOT significant and must preserve attendee responses.
 *
 * SabreDAV resets PARTSTAT only in the outgoing REQUEST (so the attendee
 * re-prompts) and never rewrites the organizer's stored copy — it treats
 * the PUT body as authoritative. So the organizer client is responsible
 * for clearing the responses it persists.
 */
function isSignificantReschedule(oldEvent: IcsEvent, newEvent: IcsEvent): boolean {
  if (resolvedInstant(oldEvent.start) !== resolvedInstant(newEvent.start)) return true;
  if (resolvedInstant(oldEvent.end) !== resolvedInstant(newEvent.end)) return true;
  if (oldEvent.start.type !== newEvent.start.type) return true; // all-day ⇄ timed
  if (canonical(oldEvent.duration) !== canonical(newEvent.duration)) return true;
  // RRULE change (frequency / interval / until / count / byDay / …).
  if (canonical(oldEvent.recurrenceRule) !== canonical(newEvent.recurrenceRule)) return true;
  return false;
}

export class CalDavService {
  private _account: CalDavAccount | null = null;
  private _calendars: Map<string, CalDavCalendar> = new Map();
  private _events: Map<string, CalDavEvent> = new Map();

  // ============================================================================
  // Connection & Authentication
  // ============================================================================

  async connect(credentials: CalDavCredentials): Promise<CalDavResponse<CalDavAccount>> {
    return asResult(async () => {
      // SabreDAV exposes principals and calendar homes at fixed paths
      // derived from the user's email (see src/caldav/server.php), so we
      // can build the account locally without round-tripping discovery.
      //
      // The path segment encoding must match what SabreDAV emits in its
      // PROPFIND hrefs — otherwise the hardcoded homeUrl won't be a
      // string-prefix of the calendar URLs we later receive, and the
      // owned-vs-shared bucket logic in CalendarContext breaks. SabreDAV's
      // URLUtil::encodePath leaves RFC 3986 sub-delims and `@` literal,
      // whereas encodeURIComponent escapes `@` (→ %40) and `+` (→ %2B),
      // so we put those two back.
      //
      // Defensive runtime check — TypeScript marks `userEmail` as required,
      // but callers could pass `undefined` at runtime (JSON, dynamic, etc).
      // Without this, `encodeURIComponent(undefined)` yields the literal
      // string `"undefined"` and silently produces a bogus homeUrl.
      if (!credentials.userEmail) {
        throw new Error("CalDAV connect requires a userEmail");
      }
      const serverUrl = credentials.serverUrl.endsWith("/")
        ? credentials.serverUrl
        : `${credentials.serverUrl}/`;
      const encodedEmail = encodeURIComponent(credentials.userEmail)
        .replace(/%40/g, "@")
        .replace(/%2B/g, "+");
      this._account = {
        serverUrl,
        principalUrl: `${serverUrl}principals/users/${encodedEmail}/`,
        homeUrl: `${serverUrl}calendars/users/${encodedEmail}/`,
      };
      return this._account;
    }, "Failed to connect");
  }

  getAccount(): CalDavAccount | null {
    return this._account;
  }

  isConnected(): boolean {
    return this._account !== null;
  }

  // ============================================================================
  // Calendar CRUD Operations
  // ============================================================================

  async fetchCalendars(): Promise<CalDavResponse<CalDavCalendar[]>> {
    if (!this._account) {
      return { success: false, error: "Not connected to server" };
    }
    if (!this._account.homeUrl) {
      return { success: false, error: "Calendar home URL not available" };
    }

    return asResult(async () => {
      const result = await davRequest({
        url: this._account!.homeUrl!,
        method: "PROPFIND",
        props: CALENDAR_PROPS,
        depth: "1",
      });
      if (!result.success || !result.responses) {
        throw new Error(result.error ?? "Failed to fetch calendars");
      }

      const calendars: CalDavCalendar[] = result.responses
        .filter((r) =>
          Object.keys((r.props?.resourcetype ?? {}) as Record<string, unknown>).includes(
            "calendar",
          ),
        )
        .map((rs) =>
          this.parseCalendarPropfindResponse(
            new URL(rs.href ?? "", this._account!.serverUrl).href,
            rs.props,
          ),
        );

      this._calendars.clear();
      calendars.forEach((cal) => this._calendars.set(cal.url, cal));

      return calendars;
    }, "Failed to fetch calendars");
  }

  /** Build a CalDavCalendar from a tsdav-parsed PROPFIND props object. */
  private parseCalendarPropfindResponse(
    url: string,
    props: Record<string, unknown> | undefined,
  ): CalDavCalendar {
    // schedule-calendar-transp (RFC 6638): "transparent" means the
    // calendar does NOT count for freebusy.
    const rawTransp =
      props?.scheduleCalendarTransp ??
      (props as Record<string, unknown> | undefined)?.["schedule-calendar-transp"];
    const isTransparent =
      rawTransp != null &&
      (typeof rawTransp === "string"
        ? rawTransp.toLowerCase().includes("transparent")
        : typeof rawTransp === "object" && rawTransp !== null && "transparent" in rawTransp);

    // LS:calendar-owner-type: "MAILBOX" for mailbox-owned shared calendars.
    const rawOwnerType = (props as Record<string, unknown> | undefined)?.calendarOwnerType;
    const ownerType = typeof rawOwnerType === "string" ? rawOwnerType : undefined;

    // CS:invite is requested as part of CALENDAR_PROPS so the mailbox
    // email and the sharee list both come back with the standard
    // calendar fetch — no second PROPFIND, no dependency on
    // useMailboxSync hydration.
    const rawInvite = (props as Record<string, unknown> | undefined)?.invite;
    const rawAccessMap =
      (props as Record<string, unknown> | undefined)?.shareAccessMap ??
      (props as Record<string, unknown> | undefined)?.["share-access-map"];
    const sharees = parseInviteSharees(rawInvite, rawAccessMap);
    const mailboxEmail = ownerType === "MAILBOX" ? parseInviteOrganizerEmail(rawInvite) : undefined;

    const displayname = (props as Record<string, unknown> | undefined)?.displayname;
    const displayName =
      typeof displayname === "string"
        ? displayname
        : ((displayname as { _cdata?: string } | undefined)?._cdata ?? "");

    const order = parseCalendarOrder((props as Record<string, unknown> | undefined)?.calendarOrder);

    return {
      url,
      displayName,
      description: (props as Record<string, string | undefined> | undefined)?.calendarDescription,
      color: (props as Record<string, string | undefined> | undefined)?.calendarColor,
      order,
      includeInAvailability: !isTransparent,
      ownerType,
      mailboxEmail,
      sharees,
      ctag: (props as Record<string, string | undefined> | undefined)?.getctag,
      syncToken: (props as Record<string, string | undefined> | undefined)?.syncToken,
      timezone: (props as Record<string, string | undefined> | undefined)?.calendarTimezone,
      components: parseCalendarComponents(
        (props as Record<string, unknown> | undefined)?.supportedCalendarComponentSet,
      ),
      resourcetype: props?.resourcetype
        ? Object.keys(props.resourcetype as Record<string, unknown>)
        : undefined,
    };
  }

  async fetchCalendar(calendarUrl: string): Promise<CalDavResponse<CalDavCalendar>> {
    return asResult(async () => {
      const result = await davRequest({
        url: calendarUrl,
        method: "PROPFIND",
        props: CALENDAR_PROPS,
        depth: "0",
      });
      if (!result.success || !result.responses) {
        throw new Error(result.error ?? `Calendar not found: ${result.status}`);
      }

      const rs = result.responses[0];
      if (!rs?.ok) {
        throw new Error(`Calendar not found: ${rs?.status}`);
      }

      const calendar = this.parseCalendarPropfindResponse(calendarUrl, rs.props);

      this._calendars.set(calendar.url, calendar);
      return calendar;
    }, "Failed to fetch calendar");
  }

  async createCalendar(params: CalDavCalendarCreate): Promise<CalDavResponse<CalDavCalendar>> {
    if (!this._account?.homeUrl) {
      return {
        success: false,
        error: "Not connected or home URL not available",
      };
    }

    return asResult(async () => {
      const calendarUrl = `${this._account!.homeUrl}${crypto.randomUUID()}/`;

      const body = buildMkCalendarXml({
        displayName: params.displayName,
        description: params.description,
        color: params.color,
        timezone: params.timezone,
      });

      const result = await davRequest({
        url: calendarUrl,
        method: "MKCALENDAR",
        body,
      });

      if (!result.success) {
        throw new Error(result.error ?? `Failed to create calendar: ${result.status}`);
      }

      const calendarResult = await this.fetchCalendar(calendarUrl);
      if (!calendarResult.success || !calendarResult.data) {
        throw new Error(calendarResult.error || "Failed to fetch created calendar");
      }

      return calendarResult.data;
    }, "Failed to create calendar");
  }

  async updateCalendar(
    calendarUrl: string,
    params: CalDavCalendarUpdate,
  ): Promise<CalDavResponse<CalDavCalendar>> {
    const hasProps =
      params.displayName !== undefined ||
      params.description !== undefined ||
      params.color !== undefined ||
      params.timezone !== undefined ||
      params.includeInAvailability !== undefined ||
      params.order !== undefined;
    if (!hasProps) {
      return { success: false, error: "No properties to update" };
    }

    const proppatchParams: CalendarProps = { ...params };
    if (params.includeInAvailability !== undefined) {
      proppatchParams.scheduleTransp = params.includeInAvailability ? "opaque" : "transparent";
    }
    const body = buildProppatchXml(proppatchParams);

    const result = await davRequest({
      url: calendarUrl,
      method: "PROPPATCH",
      body,
    });

    if (!result.success) {
      return { success: false, error: result.error, status: result.status };
    }

    return this.fetchCalendar(calendarUrl);
  }

  async deleteCalendar(calendarUrl: string): Promise<CalDavResponse> {
    const result = await davRequest({
      url: calendarUrl,
      method: "DELETE",
    });

    if (result.success) {
      this._calendars.delete(calendarUrl);
      return { success: true };
    }

    return { success: false, error: result.error, status: result.status };
  }

  getCalendar(calendarUrl: string): CalDavCalendar | undefined {
    return this._calendars.get(calendarUrl);
  }

  // ============================================================================
  // Event CRUD Operations
  // ============================================================================

  async fetchEvents(
    calendarUrl: string,
    filter?: EventFilter,
  ): Promise<CalDavResponse<CalDavEvent[]>> {
    const calendar = this._calendars.get(calendarUrl);
    if (!calendar) {
      return {
        success: false,
        error: "Calendar not found in cache. Fetch calendars first.",
      };
    }

    return asResult(async () => {
      const timeRange = filter?.timeRange
        ? {
            start:
              typeof filter.timeRange.start === "string"
                ? filter.timeRange.start
                : filter.timeRange.start.toISOString(),
            end:
              typeof filter.timeRange.end === "string"
                ? filter.timeRange.end
                : filter.timeRange.end.toISOString(),
          }
        : undefined;

      const body = buildCalendarQueryXml({
        timeRange,
        expand: filter?.expand ?? false,
      });

      const result = await davRequest({
        url: calendar.url,
        method: "REPORT",
        body,
        depth: "1",
      });
      if (!result.success || !result.responses) {
        throw new Error(result.error ?? "Failed to fetch events");
      }

      const events: CalDavEvent[] = result.responses
        .filter((r) => r.ok && r.props?.calendarData)
        .map((r) => {
          const url = new URL(r.href ?? "", this._account!.serverUrl).href;
          const ics = r.props?.calendarData as string;
          return {
            url,
            etag: r.props?.getetag as string | undefined,
            calendarUrl,
            data: convertIcsCalendar(undefined, ics),
          };
        });

      events.forEach((evt) => this._events.set(evt.url, evt));
      return events;
    }, "Failed to fetch events");
  }

  /**
   * Check if excluding an occurrence would leave zero valid occurrences.
   *
   * This happens when a recurring series has been truncated to a single
   * occurrence (e.g. UNTIL = DTSTART) and we try to EXDATE that one
   * remaining occurrence. SabreDAV rejects such ICS with a 500.
   */
  private isLastOccurrence(sourceEvent: IcsEvent, exdateDate: Date): boolean {
    const rule = sourceEvent.recurrenceRule;
    if (!rule) return false;

    // Unbounded series (no UNTIL and no COUNT) always have more occurrences
    if (!rule.until && !rule.count) return false;

    // COUNT=1 means only one occurrence — if we exclude it, zero remain
    if (rule.count === 1) return true;

    const dtstart = sourceEvent.start.local?.date ?? sourceEvent.start.date;

    // If the exdate doesn't match DTSTART, there are other occurrences
    const exdateMs = exdateDate.getTime();
    const dtstartMs = dtstart.getTime();
    if (exdateMs !== dtstartMs) return false;

    // DTSTART matches the exdate — check if UNTIL allows a second occurrence
    if (rule.until) {
      const untilDate = rule.until.local?.date ?? rule.until.date;
      const interval = rule.interval ?? 1;
      const MS_PER_DAY = 86_400_000;

      const intervalMs: Record<string, number> = {
        SECONDLY: 1000 * interval,
        MINUTELY: 60_000 * interval,
        HOURLY: 3_600_000 * interval,
        DAILY: MS_PER_DAY * interval,
        WEEKLY: 7 * MS_PER_DAY * interval,
        MONTHLY: 31 * MS_PER_DAY * interval,
        YEARLY: 366 * MS_PER_DAY * interval,
      };

      const step = intervalMs[rule.frequency] ?? MS_PER_DAY;
      if (untilDate.getTime() < dtstartMs + step) return true;
    }

    return false;
  }

  /**
   * Add EXDATE to a recurring event to exclude specific occurrences.
   *
   * Uses ts-ics to parse and regenerate the ICS, ensuring correct
   * EXDATE formatting (DATE vs DATE-TIME, timezone handling).
   */
  async addExdateToEvent(
    eventUrl: string,
    exdateToAdd: Date,
    etag?: string,
  ): Promise<CalDavResponse<{ etag?: string; shouldDeleteEntireEvent?: boolean }>> {
    return asResult(async () => {
      // Fetch the raw ICS file
      const fetchResult = await davRequest({
        url: eventUrl,
        method: "GET",
        headers: { Accept: "text/calendar" },
      });

      if (!fetchResult.success || fetchResult.body === undefined) {
        throw new Error(fetchResult.error ?? `Failed to fetch event: ${fetchResult.status}`);
      }

      const icsText = fetchResult.body;

      // Parse ICS into structured object
      const calendar = convertIcsCalendar(undefined, icsText);
      // Find the source event (with RRULE, without RECURRENCE-ID)
      // to add the EXDATE to. Don't blindly use events[0] as it might
      // be an override VEVENT when the ICS contains multiple VEVENTs.
      const event = calendar.events?.find((e) => !e.recurrenceId) ?? calendar.events?.[0];
      if (!event) {
        throw new Error("No event found in ICS data");
      }

      // If this EXDATE would leave zero valid occurrences, signal the
      // caller to delete the entire event instead (SabreDAV rejects
      // RRULE + EXDATE combinations that produce zero occurrences).
      if (this.isLastOccurrence(event, exdateToAdd)) {
        return { shouldDeleteEntireEvent: true };
      }

      // Build EXDATE entry matching DTSTART format (DATE vs DATE-TIME, timezone)
      // exdateToAdd is already in "fake UTC" format (UTC components = local timezone
      // time), since it comes from adapter.toIcsEvent() which creates fake UTC dates.
      // Use it directly with the source event's timezone info.
      const exdateFakeUtc = exdateToAdd;
      let exdateLocal: { date: Date; timezone: string; tzoffset: string } | undefined;

      if (event.start.local) {
        exdateLocal = {
          date: exdateFakeUtc,
          timezone: event.start.local.timezone,
          tzoffset: event.start.local.tzoffset,
        };
      }

      const newExdate: IcsDateObject = {
        date: exdateFakeUtc,
        type: event.start.type,
        local: exdateLocal,
      };

      // Append to existing exception dates
      event.exceptionDates = [...(event.exceptionDates ?? []), newExdate];

      // Regenerate ICS with the updated event
      this.validateTimezones(calendar);
      const updatedIcsText = generateIcsCalendar(calendar);

      // PUT the updated event back
      const updateResult = await davRequest({
        url: eventUrl,
        method: "PUT",
        body: updatedIcsText,
        contentType: "text/calendar; charset=utf-8",
        headers: etag ? { "If-Match": etag } : undefined,
      });

      if (!updateResult.success) {
        throw davFailure(updateResult, "Failed to update event");
      }

      const newEtag = updateResult.responseHeaders?.get("ETag") || undefined;

      return { etag: newEtag };
    }, "Failed to add EXDATE to event");
  }

  /**
   * Delete an override instance from a recurring event.
   *
   * Removes the override VEVENT (identified by RECURRENCE-ID) from the ICS
   * and ensures the EXDATE for that occurrence exists on the source event,
   * so SabreDAV won't return the original occurrence either.
   */
  async deleteOverrideInstance(
    eventUrl: string,
    occurrenceDate: Date,
    uid: string,
    etag?: string,
  ): Promise<CalDavResponse<{ etag?: string; shouldDeleteEntireEvent?: boolean }>> {
    return asResult(async () => {
      // Fetch the raw ICS
      const fetchResult = await davRequest({
        url: eventUrl,
        method: "GET",
        headers: { Accept: "text/calendar" },
      });

      if (!fetchResult.success || fetchResult.body === undefined) {
        throw new Error(fetchResult.error ?? `Failed to fetch event: ${fetchResult.status}`);
      }

      const icsText = fetchResult.body;
      const calendar = convertIcsCalendar(undefined, icsText);

      const sourceEvent = calendar.events?.find((e) => e.uid === uid && !e.recurrenceId);
      if (!sourceEvent) {
        throw new Error("Source event not found in ICS data");
      }

      // If adding EXDATE would leave zero occurrences, signal caller to
      // delete the entire event instead (SabreDAV rejects empty series).
      if (this.isLastOccurrence(sourceEvent, occurrenceDate)) {
        return { shouldDeleteEntireEvent: true };
      }

      // occurrenceDate is in fake UTC format. Find and remove the override VEVENT
      // by comparing against both real UTC and fake UTC (local.date) recurrenceId.
      const occurrenceFakeUtc = occurrenceDate;
      calendar.events = calendar.events?.filter((e) => {
        if (e.uid !== uid || !e.recurrenceId) return true;
        return !(
          e.recurrenceId.value.date.getTime() === occurrenceFakeUtc.getTime() ||
          e.recurrenceId.value.local?.date.getTime() === occurrenceFakeUtc.getTime()
        );
      });

      // Ensure EXDATE exists on the source event for this occurrence
      const exdateAlreadyExists = sourceEvent.exceptionDates?.some(
        (exd) =>
          exd.date.getTime() === occurrenceFakeUtc.getTime() ||
          exd.local?.date.getTime() === occurrenceFakeUtc.getTime(),
      );

      if (!exdateAlreadyExists) {
        let occurrenceLocal: { date: Date; timezone: string; tzoffset: string } | undefined;
        if (sourceEvent.start.local) {
          occurrenceLocal = {
            date: occurrenceFakeUtc,
            timezone: sourceEvent.start.local.timezone,
            tzoffset: sourceEvent.start.local.tzoffset,
          };
        }

        const newExdate: IcsDateObject = {
          date: occurrenceFakeUtc,
          type: sourceEvent.start.type,
          local: occurrenceLocal,
        };
        sourceEvent.exceptionDates = [...(sourceEvent.exceptionDates ?? []), newExdate];
      }

      this.validateTimezones(calendar);
      const updatedIcsText = generateIcsCalendar(calendar);

      // PUT the updated ICS
      const updateResult = await davRequest({
        url: eventUrl,
        method: "PUT",
        body: updatedIcsText,
        contentType: "text/calendar; charset=utf-8",
        headers: etag ? { "If-Match": etag } : undefined,
      });

      if (!updateResult.success) {
        throw davFailure(updateResult, "Failed to update event");
      }

      const newEtag = updateResult.responseHeaders?.get("ETag") || undefined;
      return { etag: newEtag };
    }, "Failed to delete override instance");
  }

  /**
   * Truncate a recurring series at a given cutoff date.
   *
   * Sets RRULE UNTIL to the day before cutoffDate, removes override VEVENTs
   * with recurrenceId >= cutoffDate, and removes EXDATE entries >= cutoffDate.
   */
  async truncateRecurringSeries(
    eventUrl: string,
    cutoffDate: Date,
    uid: string,
    etag?: string,
  ): Promise<CalDavResponse<{ etag?: string }>> {
    return asResult(async () => {
      // Fetch the raw ICS
      const fetchResult = await davRequest({
        url: eventUrl,
        method: "GET",
        headers: { Accept: "text/calendar" },
      });

      if (!fetchResult.success || fetchResult.body === undefined) {
        throw new Error(fetchResult.error ?? `Failed to fetch event: ${fetchResult.status}`);
      }

      const icsText = fetchResult.body;
      const calendar = convertIcsCalendar(undefined, icsText);

      const sourceEvent = calendar.events?.find((e) => e.uid === uid && !e.recurrenceId);
      if (!sourceEvent) {
        throw new Error("Source event not found in ICS data");
      }

      if (!sourceEvent.recurrenceRule) {
        throw new Error("Source event has no recurrence rule");
      }

      // Set RRULE UNTIL to day before cutoff
      const untilDate = new Date(cutoffDate);
      untilDate.setDate(untilDate.getDate() - 1);
      untilDate.setHours(23, 59, 59, 999);

      sourceEvent.recurrenceRule = {
        ...sourceEvent.recurrenceRule,
        until: { type: "DATE-TIME" as const, date: untilDate },
        count: undefined,
      };

      // Remove override VEVENTs with recurrenceId >= cutoffDate
      const cutoffMs = cutoffDate.getTime();
      calendar.events = calendar.events?.filter((e) => {
        if (e.uid !== uid || !e.recurrenceId) return true;
        return !(
          e.recurrenceId.value.date.getTime() >= cutoffMs ||
          (e.recurrenceId.value.local?.date.getTime() ?? -1) >= cutoffMs
        );
      });

      // Remove EXDATE entries >= cutoffDate from source event
      if (sourceEvent.exceptionDates?.length) {
        sourceEvent.exceptionDates = sourceEvent.exceptionDates.filter((exd) => {
          return !(exd.date.getTime() >= cutoffMs || (exd.local?.date.getTime() ?? -1) >= cutoffMs);
        });
      }

      this.validateTimezones(calendar);
      const updatedIcsText = generateIcsCalendar(calendar);

      // PUT the updated ICS
      const updateResult = await davRequest({
        url: eventUrl,
        method: "PUT",
        body: updatedIcsText,
        contentType: "text/calendar; charset=utf-8",
        headers: etag ? { "If-Match": etag } : undefined,
      });

      if (!updateResult.success) {
        throw davFailure(updateResult, "Failed to update event");
      }

      const newEtag = updateResult.responseHeaders?.get("ETag") || undefined;
      return { etag: newEtag };
    }, "Failed to truncate recurring series");
  }

  /**
   * Create an override instance for a recurring event.
   *
   * This adds the modified occurrence as a new VEVENT with RECURRENCE-ID
   * inside the same ICS resource, and adds an EXDATE to the parent event
   * to exclude the original occurrence.
   */
  async createOverrideInstance(
    eventUrl: string,
    overrideEvent: IcsEvent,
    occurrenceDate: Date,
    etag?: string,
  ): Promise<CalDavResponse<{ etag?: string }>> {
    return asResult(async () => {
      // Fetch the raw ICS
      const fetchResult = await davRequest({
        url: eventUrl,
        method: "GET",
        headers: { Accept: "text/calendar" },
      });

      if (!fetchResult.success || fetchResult.body === undefined) {
        throw new Error(fetchResult.error ?? `Failed to fetch event: ${fetchResult.status}`);
      }

      const icsText = fetchResult.body;
      const calendar = convertIcsCalendar(undefined, icsText);
      const sourceEvent = calendar.events?.find(
        (e) => e.uid === overrideEvent.uid && !e.recurrenceId,
      );

      if (!sourceEvent) {
        throw new Error("Source event not found in ICS data");
      }

      // occurrenceDate is already in "fake UTC" format (UTC components = local timezone
      // time), since it comes from adapter.toIcsEvent() which creates fake UTC dates.
      // Use it directly with the source event's timezone info.
      const occurrenceFakeUtc = occurrenceDate;
      let occurrenceLocal: { date: Date; timezone: string; tzoffset: string } | undefined;

      if (sourceEvent.start.local) {
        occurrenceLocal = {
          date: occurrenceFakeUtc,
          timezone: sourceEvent.start.local.timezone,
          tzoffset: sourceEvent.start.local.tzoffset,
        };
      }

      // Check if an override for this occurrence already exists (re-drag case)
      // occurrenceFakeUtc is in fake UTC format. Compare against both:
      // - recurrenceId.value.date (real UTC from ts-ics parsing)
      // - recurrenceId.value.local?.date (fake UTC if TZID was present)
      const existingOverrideIdx =
        calendar.events?.findIndex(
          (e) =>
            e.uid === overrideEvent.uid &&
            e.recurrenceId &&
            (e.recurrenceId.value.date.getTime() === occurrenceFakeUtc.getTime() ||
              e.recurrenceId.value.local?.date.getTime() === occurrenceFakeUtc.getTime()),
        ) ?? -1;

      if (existingOverrideIdx >= 0) {
        // Re-drag: update existing override in-place, EXDATE already exists
        const existingOverride = calendar.events![existingOverrideIdx];
        calendar.events![existingOverrideIdx] = {
          ...overrideEvent,
          recurrenceRule: undefined,
          recurrenceId: existingOverride.recurrenceId,
          sequence: (existingOverride.sequence ?? 0) + 1,
        };
      } else {
        // First override: add EXDATE + new override VEVENT
        const newExdate: IcsDateObject = {
          date: occurrenceFakeUtc,
          type: sourceEvent.start.type,
          local: occurrenceLocal,
        };

        sourceEvent.exceptionDates = [...(sourceEvent.exceptionDates ?? []), newExdate];

        const overrideVevent: IcsEvent = {
          ...overrideEvent,
          recurrenceRule: undefined,
          recurrenceId: {
            value: {
              date: occurrenceFakeUtc,
              type: sourceEvent.start.type,
              local: occurrenceLocal,
            },
          },
          sequence: (overrideEvent.sequence ?? 0) + 1,
        };

        calendar.events = [...(calendar.events ?? []), overrideVevent];
      }

      this.validateTimezones(calendar);
      const updatedIcsText = generateIcsCalendar(calendar);

      // PUT the updated ICS
      const updateResult = await davRequest({
        url: eventUrl,
        method: "PUT",
        body: updatedIcsText,
        contentType: "text/calendar; charset=utf-8",
        headers: etag ? { "If-Match": etag } : undefined,
      });

      if (!updateResult.success) {
        throw davFailure(updateResult, "Failed to update event");
      }

      const newEtag = updateResult.responseHeaders?.get("ETag") || undefined;
      return { etag: newEtag };
    }, "Failed to create override instance");
  }

  async fetchEvent(eventUrl: string): Promise<CalDavResponse<CalDavEvent>> {
    return asResult(async () => {
      const result = await davRequest({
        url: eventUrl,
        method: "GET",
        headers: { Accept: "text/calendar" },
      });

      if (!result.success || result.body === undefined) {
        throw new Error(result.error ?? `Event not found: ${result.status}`);
      }

      const calendarUrl = getCalendarUrlFromEventUrl(eventUrl);

      const event: CalDavEvent = {
        url: eventUrl,
        etag: result.responseHeaders?.get("etag") ?? undefined,
        calendarUrl,
        data: convertIcsCalendar(undefined, result.body),
      };

      this._events.set(event.url, event);
      return event;
    }, "Failed to fetch event");
  }

  async createEvent(params: CalDavEventCreate): Promise<CalDavResponse<CalDavEvent>> {
    const calendar = this._calendars.get(params.calendarUrl);
    if (!calendar) {
      return { success: false, error: "Calendar not found" };
    }

    return asResult(async () => {
      const event = { ...params.event };
      if (!event.uid) {
        event.uid = crypto.randomUUID();
      }

      const icsCalendar: IcsCalendar = {
        prodId: "-//CalDavService//NONSGML v1.0//EN",
        version: "2.0",
        events: [event],
      };

      this.validateTimezones(icsCalendar);
      const iCalString = generateIcsCalendar(icsCalendar);

      const eventUrl = `${params.calendarUrl}${event.uid}.ics`;
      const response = await davRequest({
        url: eventUrl,
        method: "PUT",
        body: iCalString,
        contentType: "text/calendar; charset=utf-8",
        headers: { "If-None-Match": "*" },
      });

      if (!response.success) {
        throw davFailure(response, "Failed to create event");
      }

      const createdEvent: CalDavEvent = {
        url: eventUrl,
        etag: response.responseHeaders?.get("etag") ?? undefined,
        calendarUrl: params.calendarUrl,
        data: icsCalendar,
      };

      this._events.set(createdEvent.url, createdEvent);
      return createdEvent;
    }, "Failed to create event");
  }

  async updateEvent(params: CalDavEventUpdate): Promise<CalDavResponse<CalDavEvent>> {
    const cachedEvent = this._events.get(params.eventUrl);
    const calendarUrl = cachedEvent?.calendarUrl ?? getCalendarUrlFromEventUrl(params.eventUrl);
    const calendar = this._calendars.get(calendarUrl);

    if (!calendar) {
      return { success: false, error: "Calendar not found" };
    }

    return asResult(async () => {
      const icsCalendar: IcsCalendar = cachedEvent?.data ?? {
        prodId: "-//CalDavService//NONSGML v1.0//EN",
        version: "2.0",
        events: [],
      };

      const existingIndex =
        icsCalendar.events?.findIndex((e) => {
          if (e.uid !== params.event.uid) return false;
          // Source event update: match by UID + no recurrenceId
          if (!params.event.recurrenceId) return !e.recurrenceId;
          // Override update: match by UID + specific recurrenceId value
          if (!e.recurrenceId) return false;
          const paramRecId = params.event.recurrenceId.value;
          const eRecId = e.recurrenceId.value;
          return (
            eRecId.date.getTime() === paramRecId.date.getTime() ||
            eRecId.local?.date.getTime() === paramRecId.local?.date.getTime()
          );
        }) ?? -1;
      if (existingIndex >= 0 && icsCalendar.events) {
        const oldEvent = icsCalendar.events[existingIndex];
        const updatedEvent = { ...params.event };
        updatedEvent.sequence = (updatedEvent.sequence ?? 0) + 1;

        // On a reschedule (time/RRULE change), clear every attendee's
        // response back to NEEDS-ACTION — except the organizer's own entry.
        // SabreDAV won't do this to the organizer's stored copy, so without
        // it the organizer keeps seeing stale "Accepted" after moving an
        // event. Non-timing edits (title/description) preserve responses.
        if (updatedEvent.attendees?.length && isSignificantReschedule(oldEvent, updatedEvent)) {
          const organizerEmail = updatedEvent.organizer?.email?.toLowerCase();
          updatedEvent.attendees = updatedEvent.attendees.map((att) =>
            att.email.toLowerCase() === organizerEmail ? att : { ...att, partstat: "NEEDS-ACTION" },
          );
        }

        icsCalendar.events = [...icsCalendar.events];
        icsCalendar.events[existingIndex] = updatedEvent;

        // When updating the source of a recurring series with a time change,
        // shift EXDATE entries and override RECURRENCE-IDs to match the new occurrence times.
        if (updatedEvent.recurrenceRule && !updatedEvent.recurrenceId) {
          const oldStartMs = (oldEvent.start.local?.date ?? oldEvent.start.date).getTime();
          const newStartMs = (updatedEvent.start.local?.date ?? updatedEvent.start.date).getTime();

          if (oldStartMs !== newStartMs) {
            const deltaMs = newStartMs - oldStartMs;

            // Shift EXDATE entries on the updated source event
            if (updatedEvent.exceptionDates?.length) {
              updatedEvent.exceptionDates = updatedEvent.exceptionDates.map((exd) => ({
                ...exd,
                date: new Date(exd.date.getTime() + deltaMs),
                local: exd.local
                  ? {
                      ...exd.local,
                      date: new Date(exd.local.date.getTime() + deltaMs),
                    }
                  : undefined,
              }));
              icsCalendar.events[existingIndex] = updatedEvent;
            }

            // Shift override RECURRENCE-IDs
            for (let i = 0; i < icsCalendar.events.length; i++) {
              const evt = icsCalendar.events[i];
              if (evt.uid === params.event.uid && evt.recurrenceId) {
                icsCalendar.events[i] = {
                  ...evt,
                  recurrenceId: {
                    ...evt.recurrenceId,
                    value: {
                      ...evt.recurrenceId.value,
                      date: new Date(evt.recurrenceId.value.date.getTime() + deltaMs),
                      local: evt.recurrenceId.value.local
                        ? {
                            ...evt.recurrenceId.value.local,
                            date: new Date(evt.recurrenceId.value.local.date.getTime() + deltaMs),
                          }
                        : undefined,
                    },
                  },
                };
              }
            }
          }
        }
      } else {
        icsCalendar.events = [params.event];
      }

      this.validateTimezones(icsCalendar);
      const iCalString = generateIcsCalendar(icsCalendar);

      const ifMatchEtag = params.etag ?? cachedEvent?.etag;

      const response = await davRequest({
        url: params.eventUrl,
        method: "PUT",
        body: iCalString,
        contentType: "text/calendar; charset=utf-8",
        headers: ifMatchEtag ? { "If-Match": ifMatchEtag } : undefined,
      });

      if (!response.success) {
        throw davFailure(response, "Failed to update event");
      }

      const updatedEvent: CalDavEvent = {
        url: params.eventUrl,
        etag: response.responseHeaders?.get("etag") ?? undefined,
        calendarUrl,
        data: icsCalendar,
      };

      this._events.set(updatedEvent.url, updatedEvent);
      return updatedEvent;
    }, "Failed to update event");
  }

  /**
   * Relocate an event resource to a different calendar via WebDAV MOVE.
   *
   * SabreDAV's Schedule\Plugin skips iTIP dispatch on MOVE (CalDAV/Schedule/
   * Plugin.php#beforeUnbind), which is the desired behavior when an organizer
   * moves an event between their own calendars: attendees should not receive
   * spurious REQUEST/CANCEL emails. Content edits (which may warrant iTIP)
   * should be applied via a follow-up updateEvent at the returned URL — the
   * `significantChange` filter then decides whether to notify attendees.
   *
   * Returns the new resource URL and ETag. Source ETag, if provided, is sent
   * as If-Match for an optimistic-concurrency precondition.
   */
  async moveEvent(
    params: CalDavEventMove,
  ): Promise<CalDavResponse<{ url: string; etag?: string }>> {
    const targetCalendar = this._calendars.get(params.targetCalendarUrl);
    if (!targetCalendar) {
      return { success: false, error: "Target calendar not found" };
    }

    const cachedSource = this._events.get(params.sourceEventUrl);

    return asResult(async () => {
      // Strip trailing slashes before splitting so a stray collection-shaped
      // URL (ends with `/`) doesn't yield an empty filename that we'd then
      // concatenate onto the target — producing the target collection URL
      // as the destination. Also require the `.ics` suffix so only event
      // resources are moveable through this path; the proxy and SabreDAV
      // would reject a collection-targeted MOVE anyway, but failing here
      // is louder and avoids a misleading server error.
      const filename = params.sourceEventUrl.replace(/\/+$/, "").split("/").pop();
      if (!filename || !filename.endsWith(".ics")) {
        throw new Error("Could not derive event filename from source URL");
      }
      const newEventUrl = `${params.targetCalendarUrl}${filename}`;
      const sourceEtag = params.sourceEtag ?? cachedSource?.etag;

      const response = await davRequest({
        url: params.sourceEventUrl,
        method: "MOVE",
        headers: {
          Destination: newEventUrl,
          Overwrite: "F",
          ...(sourceEtag ? { "If-Match": sourceEtag } : {}),
        },
      });

      if (!response.success) {
        throw davFailure(response, "Failed to move event");
      }

      const newEtag = response.responseHeaders?.get("etag") ?? undefined;

      if (cachedSource) {
        this._events.delete(params.sourceEventUrl);
        this._events.set(newEventUrl, {
          ...cachedSource,
          url: newEventUrl,
          calendarUrl: params.targetCalendarUrl,
          etag: newEtag,
        });
      }

      return { url: newEventUrl, etag: newEtag };
    }, "Failed to move event");
  }

  /** Idempotent delete with one ETag retry.
   *
   * - 204: success.
   * - 404: success (already gone — the caller's intent is fulfilled).
   * - 412: our ETag drifted. Refetch and retry once. If the refetch is also
   *   404, the resource is gone (SabreDAV emits 412 when If-Match cannot
   *   match a missing resource, so the original status alone doesn't tell
   *   us whether to retry or treat as success — the GET disambiguates).
   * - anything else: propagate as an error. */
  async deleteEvent(eventUrl: string, etag?: string): Promise<CalDavResponse> {
    const cachedEvent = this._events.get(eventUrl);

    return asResult(async () => {
      const tryDelete = (e: string | undefined) =>
        davRequest({
          url: eventUrl,
          method: "DELETE",
          headers: e ? { "If-Match": e } : undefined,
        });

      let response = await tryDelete(etag ?? cachedEvent?.etag);

      if (response.status === 404) {
        this._events.delete(eventUrl);
        return undefined;
      }

      if (response.status === 412) {
        const fresh = await davRequest({
          url: eventUrl,
          method: "GET",
          headers: { Accept: "text/calendar" },
        });
        if (fresh.status === 404) {
          this._events.delete(eventUrl);
          return undefined;
        }
        const freshEtag = fresh.responseHeaders?.get("etag");
        if (fresh.success && freshEtag) {
          response = await tryDelete(freshEtag);
          if (response.status === 404) {
            this._events.delete(eventUrl);
            return undefined;
          }
        }
      }

      if (!response.success) {
        throw davFailure(response, "Failed to delete event");
      }

      this._events.delete(eventUrl);
      return undefined;
    }, "Failed to delete event");
  }

  // ============================================================================
  // Calendar Sharing (CalDAV Sharing Extension)
  // ============================================================================

  async shareCalendar(params: CalDavShareInvite): Promise<CalDavResponse<CalDavShareResponse>> {
    const calendar = this._calendars.get(params.calendarUrl);
    if (!calendar) {
      return { success: false, error: "Calendar not found" };
    }

    const shareeParams: ShareeXmlParams[] = params.sharees.map((s) => ({
      href: s.href,
      displayName: s.displayName,
      privilege: s.privilege,
    }));

    const body = buildShareRequestXml(shareeParams);

    const result = await davRequest({
      url: params.calendarUrl,
      method: "POST",
      body,
    });

    if (!result.success) {
      return { success: false, error: result.error, status: result.status };
    }

    return {
      success: true,
      data: {
        success: true,
        sharees: params.sharees.map((s) => ({
          ...s,
          status: "pending" as const,
        })),
      },
    };
  }

  async unshareCalendar(calendarUrl: string, shareeHref: string): Promise<CalDavResponse> {
    const body = buildUnshareRequestXml(shareeHref);

    const result = await davRequest({
      url: calendarUrl,
      method: "POST",
      body,
    });

    return result.success
      ? { success: true }
      : { success: false, error: result.error, status: result.status };
  }

  // ============================================================================
  // Scheduling (iTIP - RFC 5546)
  // ============================================================================

  async respondToMeeting(
    eventUrl: string,
    event: IcsEvent,
    attendeeEmail: string,
    status: CalDavAttendee["partstat"],
    etag?: string,
  ): Promise<CalDavResponse<SchedulingResponse>> {
    const attendee = event.attendees?.find(
      (a) => a.email.toLowerCase() === attendeeEmail.toLowerCase(),
    );

    if (!attendee) {
      return { success: false, error: "Attendee not found in event" };
    }

    // Update the event with the new participation status
    // Sabre/DAV will automatically detect the change and send a REPLY to the organizer
    const updatedEvent = {
      ...event,
      attendees: event.attendees?.map((att) =>
        att.email.toLowerCase() === attendeeEmail.toLowerCase()
          ? { ...att, partstat: status }
          : att,
      ),
    };

    const result = await this.updateEvent({
      eventUrl,
      event: updatedEvent,
      etag,
    });

    if (!result.success) {
      // Propagate the HTTP status (notably 412) so the caller's
      // refetch-and-retry-on-stale-ETag path can fire. Dropping it here
      // made a second RSVP in the same modal session fail silently.
      return {
        success: false,
        status: result.status,
        error: result.error || "Failed to update event",
      };
    }

    return {
      success: true,
      data: {
        success: true,
        responses: [
          {
            recipient: event.organizer?.email || "",
            status: "delivered" as const,
          },
        ],
      },
    };
  }

  // ============================================================================
  // Free/Busy Queries
  // ============================================================================

  async queryFreeBusy(request: FreeBusyRequest): Promise<CalDavResponse<FreeBusyResponse[]>> {
    if (!this._account) {
      return { success: false, error: "Not connected" };
    }

    return asResult(async () => {
      const outboxUrl = await this.findSchedulingOutbox();
      if (!outboxUrl) {
        throw new Error("Scheduling outbox not found");
      }

      const fbRequest = buildFreeBusyRequestIcs(request);

      // Construct full URL - outboxUrl from PROPFIND is an absolute path (e.g. /caldav/calendars/...)
      // so we only need to prepend the origin, not the full serverUrl (which already has /caldav/)
      const fullOutboxUrl = outboxUrl.startsWith("http")
        ? outboxUrl
        : `${new URL(this._account!.serverUrl).origin}${outboxUrl}`;

      const response = await davRequest({
        url: fullOutboxUrl,
        method: "POST",
        body: fbRequest,
        contentType: "text/calendar; charset=utf-8",
      });

      if (!response.success || response.body === undefined) {
        throw new Error(response.error ?? `Failed to query free/busy: ${response.status}`);
      }

      return parseScheduleFreeBusyResponse(response.body);
    }, "Failed to query free/busy");
  }

  // ============================================================================
  // Availability (Working Hours)
  // ============================================================================

  /**
   * Get the user's calendar availability (working hours).
   * Reads the {urn:ietf:params:xml:ns:caldav}calendar-availability property
   * from the calendar home via PROPFIND.
   */
  async getAvailability(): Promise<CalDavResponse<string | null>> {
    if (!this._account?.homeUrl) {
      return { success: false, error: "Not connected" };
    }

    return asResult(async () => {
      const result = await davRequest({
        url: this._account!.homeUrl!,
        method: "PROPFIND",
        props: {
          [`${NS.CALDAV}:calendar-availability`]: {},
        },
        depth: "0",
      });
      if (!result.success || !result.responses) {
        throw new Error(result.error ?? "Failed to get availability");
      }

      return result.responses[0]?.props?.["calendarAvailability"] ?? null;
    }, "Failed to get availability");
  }

  /**
   * Set the user's calendar availability (working hours).
   * Stores a VCALENDAR with VAVAILABILITY/AVAILABLE components
   * on the calendar home via PROPPATCH.
   */
  async setAvailability(vcalendarText: string): Promise<CalDavResponse> {
    if (!this._account?.homeUrl) {
      return { success: false, error: "Not connected" };
    }

    const body = `<?xml version="1.0" encoding="utf-8"?>
<D:propertyupdate xmlns:D="DAV:" xmlns:C="urn:ietf:params:xml:ns:caldav">
  <D:set>
    <D:prop>
      <C:calendar-availability>${escapeXml(vcalendarText)}</C:calendar-availability>
    </D:prop>
  </D:set>
</D:propertyupdate>`;

    const result = await davRequest({
      url: this._account.homeUrl,
      method: "PROPPATCH",
      body,
    });
    return result.success
      ? { success: true }
      : { success: false, error: result.error, status: result.status };
  }

  // ============================================================================
  // Utility Methods
  // ============================================================================

  clearCache(): void {
    this._calendars.clear();
    this._events.clear();
  }

  disconnect(): void {
    this._account = null;
    this.clearCache();
  }

  // ============================================================================
  // Private Helper Methods
  // ============================================================================

  private validateTimezones(calendarData: IcsCalendar): void {
    const usedTimezones =
      calendarData.events?.flatMap((e) => [e.start.local?.timezone, e.end?.local?.timezone]) ?? [];
    const wantedTzIds = new Set(usedTimezones.filter((s): s is string => s !== undefined));

    calendarData.timezones ??= [];
    calendarData.timezones = calendarData.timezones.filter((tz) => wantedTzIds.has(tz.id));

    wantedTzIds.forEach((tzid) => {
      if (calendarData.timezones!.findIndex((t) => t.id === tzid) === -1) {
        const tzBlock = getIcalTimezoneBlock(tzid)[0];
        if (tzBlock) {
          calendarData.timezones!.push(convertIcsTimezone(undefined, tzBlock));
        }
      }
    });
  }

  private async findSchedulingOutbox(): Promise<string | null> {
    if (!this._account?.principalUrl) return null;

    try {
      const result = await davRequest({
        url: this._account.principalUrl,
        method: "PROPFIND",
        props: { [`${NS.CALDAV}:schedule-outbox-URL`]: {} },
        depth: "0",
      });

      // Note: tsdav converts XML property names to camelCase
      return result.responses?.[0]?.props?.["scheduleOutboxURL"]?.href ?? null;
    } catch {
      return null;
    }
  }

  /**
   * Get scheduling capabilities of the server
   * Useful for diagnosing if the server supports email notifications (IMip)
   */
  async getSchedulingCapabilities(): Promise<
    CalDavResponse<{
      hasSchedulingSupport: boolean;
      scheduleOutboxUrl: string | null;
      scheduleInboxUrl: string | null;
      calendarUserAddressSet: string[];
      rawResponse?: unknown;
    }>
  > {
    if (!this._account?.principalUrl) {
      return {
        success: false,
        error: "Not connected or principal URL not found",
      };
    }

    return asResult(async () => {
      const result = await davRequest({
        url: this._account!.principalUrl!,
        method: "PROPFIND",
        props: {
          [`${NS.CALDAV}:schedule-outbox-URL`]: {},
          [`${NS.CALDAV}:schedule-inbox-URL`]: {},
          [`${NS.CALDAV}:calendar-user-address-set`]: {},
        },
        depth: "0",
      });
      if (!result.success || !result.responses) {
        throw new Error(result.error ?? "Failed to get scheduling capabilities");
      }

      const props = result.responses[0]?.props ?? {};

      // Note: tsdav converts XML property names to camelCase
      // schedule-outbox-URL becomes scheduleOutboxURL
      // schedule-inbox-URL becomes scheduleInboxURL
      // calendar-user-address-set becomes calendarUserAddressSet
      const scheduleOutboxUrl = props["scheduleOutboxURL"]?.href ?? null;
      const scheduleInboxUrl = props["scheduleInboxURL"]?.href ?? null;

      // calendar-user-address-set contains email addresses used for scheduling
      const addressSet = props["calendarUserAddressSet"];
      const calendarUserAddressSet: string[] = [];

      if (addressSet && typeof addressSet === "object" && "href" in addressSet) {
        // Can be single href or array of hrefs
        const hrefs = Array.isArray(addressSet.href) ? addressSet.href : [addressSet.href];
        hrefs.forEach((href: string) => {
          if (href && typeof href === "string") {
            calendarUserAddressSet.push(href);
          }
        });
      }

      return {
        hasSchedulingSupport: !!(scheduleOutboxUrl && scheduleInboxUrl),
        scheduleOutboxUrl,
        scheduleInboxUrl,
        calendarUserAddressSet,
        rawResponse: result.responses,
      };
    }, "Failed to get scheduling capabilities");
  }
}

export function createCalDavService(): CalDavService {
  return new CalDavService();
}

// ============================================================================
// FreeBusy Response Parsing
// ============================================================================

/**
 * Parse a CalDAV schedule-response XML containing VFREEBUSY data.
 * Response format defined in RFC 6638.
 */
function parseScheduleFreeBusyResponse(xmlText: string): FreeBusyResponse[] {
  const parser = new DOMParser();
  const doc = parser.parseFromString(xmlText, "application/xml");

  const results: FreeBusyResponse[] = [];
  const CAL_NS = "urn:ietf:params:xml:ns:caldav";
  const DAV_NS = "DAV:";

  const responseElements = doc.getElementsByTagNameNS(CAL_NS, "response");

  for (let i = 0; i < responseElements.length; i++) {
    const responseEl = responseElements[i];

    // Check request-status — skip unknown users (3.x = error)
    const statusEl = responseEl.getElementsByTagNameNS(CAL_NS, "request-status")[0];
    const status = statusEl?.textContent ?? "";
    if (status.startsWith("3.")) continue;

    // Extract recipient email
    const recipientEl = responseEl.getElementsByTagNameNS(CAL_NS, "recipient")[0];
    const hrefEl = recipientEl?.getElementsByTagNameNS(DAV_NS, "href")[0];
    const href = hrefEl?.textContent ?? "";
    const email = href.replace(/^mailto:/i, "").toLowerCase();

    // Extract calendar-data (ICS text containing VFREEBUSY)
    const calDataEl = responseEl.getElementsByTagNameNS(CAL_NS, "calendar-data")[0];
    const icsText = calDataEl?.textContent ?? "";

    const periods = parseFreeBusyPeriods(icsText);
    results.push({ attendee: email, periods });
  }

  return results;
}

/**
 * Parse FREEBUSY lines from a VFREEBUSY ICS component.
 * Format: FREEBUSY;FBTYPE=BUSY:20260310T090000Z/20260310T100000Z
 */
function parseFreeBusyPeriods(icsText: string): FreeBusyResponse["periods"] {
  const periods: FreeBusyResponse["periods"] = [];
  const lines = icsText.split(/\r?\n/);

  for (const line of lines) {
    if (!line.startsWith("FREEBUSY")) continue;

    // Split into params and value: FREEBUSY;FBTYPE=BUSY:start/end
    const colonIdx = line.indexOf(":");
    if (colonIdx === -1) continue;

    const params = line.substring(0, colonIdx);
    const value = line.substring(colonIdx + 1);

    // Parse FBTYPE (default BUSY)
    let fbType: "BUSY" | "BUSY-UNAVAILABLE" | "BUSY-TENTATIVE" | "FREE" = "BUSY";
    const typeMatch = params.match(/FBTYPE=([A-Z-]+)/i);
    if (typeMatch) {
      fbType = typeMatch[1].toUpperCase() as typeof fbType;
    }

    // Parse comma-separated periods
    const periodStrs = value.split(",");
    for (const periodStr of periodStrs) {
      const [startStr, endStr] = periodStr.split("/");
      if (!startStr || !endStr) continue;

      const start = parseIcsDateTime(startStr);
      if (!start) continue;

      let end: Date | null;
      if (endStr.startsWith("P")) {
        // Duration format (e.g., PT1H)
        end = addIsoDuration(start, endStr);
      } else {
        end = parseIcsDateTime(endStr);
      }
      if (!end) continue;

      periods.push({ start, end, type: fbType });
    }
  }

  return periods;
}

/** Parse an ICS datetime string like 20260310T090000Z into a Date. */
function parseIcsDateTime(str: string): Date | null {
  const m = str.match(/^(\d{4})(\d{2})(\d{2})T(\d{2})(\d{2})(\d{2})Z?$/);
  if (!m) return null;
  return new Date(
    Date.UTC(
      parseInt(m[1]),
      parseInt(m[2]) - 1,
      parseInt(m[3]),
      parseInt(m[4]),
      parseInt(m[5]),
      parseInt(m[6]),
    ),
  );
}

/** Add an ISO 8601 duration (e.g., PT1H30M) to a Date. */
function addIsoDuration(date: Date, duration: string): Date {
  const m = duration.match(/P(?:(\d+)D)?T?(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?/);
  if (!m) return date;
  const ms =
    (parseInt(m[1] || "0") * 86400 +
      parseInt(m[2] || "0") * 3600 +
      parseInt(m[3] || "0") * 60 +
      parseInt(m[4] || "0")) *
    1000;
  return new Date(date.getTime() + ms);
}
