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
  type IcsEvent,
} from 'ts-ics'
import {
  createAccount,
  fetchCalendars as davFetchCalendars,
  fetchCalendarObjects as davFetchCalendarObjects,
  createCalendarObject as davCreateCalendarObject,
  updateCalendarObject as davUpdateCalendarObject,
  deleteCalendarObject as davDeleteCalendarObject,
  makeCalendar as davMakeCalendar,
  propfind,
  DAVNamespaceShort,
  type DAVCalendarObject,
  davRequest,
} from 'tsdav'
import type {
  CalDavCredentials,
  CalDavAccount,
  CalDavCalendar,
  CalDavCalendarCreate,
  CalDavCalendarUpdate,
  CalDavEvent,
  CalDavEventCreate,
  CalDavEventUpdate,
  EventFilter,
  CalDavShareInvite,
  CalDavShareResponse,
  CalDavSharee,
  CalDavInvitation,
  CalDavResponse,
  SyncReport,
  SyncOptions,
  FreeBusyRequest,
  FreeBusyResponse,
  CalendarAcl,
  CalDavPrincipal,
  SchedulingRequest,
  SchedulingResponse,
  CalDavAttendee,
} from './types/caldav-service'
import {
  buildProppatchXml,
  buildShareRequestXml,
  buildUnshareRequestXml,
  buildInviteReplyXml,
  buildSyncCollectionXml,
  buildPrincipalSearchXml,
  executeDavRequest,
  CALENDAR_PROPS,
  parseCalendarComponents,
  parseSharePrivilege,
  parseShareStatus,
  getCalendarUrlFromEventUrl,
  withErrorHandling,
  type ShareeXmlParams,
} from './caldav-helpers'
import { getIcalTimezoneBlock } from './helpers/ical-timezones'

export class CalDavService {
  private _account: CalDavAccount | null = null
  private _calendars: Map<string, CalDavCalendar> = new Map()
  private _events: Map<string, CalDavEvent> = new Map()

  // ============================================================================
  // Connection & Authentication
  // ============================================================================

  async connect(credentials: CalDavCredentials): Promise<CalDavResponse<CalDavAccount>> {
    return withErrorHandling(async () => {
      const account = await createAccount({
        account: {
          serverUrl: credentials.serverUrl,
          accountType: 'caldav',
        },
        headers: credentials.headers,
        fetchOptions: credentials.fetchOptions,
      })

      this._account = {
        serverUrl: credentials.serverUrl,
        rootUrl: account.rootUrl,
        principalUrl: account.principalUrl,
        homeUrl: account.homeUrl,
        headers: credentials.headers,
        fetchOptions: credentials.fetchOptions,
      }

      return this._account
    }, 'Failed to connect')
  }

  getAccount(): CalDavAccount | null {
    return this._account
  }

  isConnected(): boolean {
    return this._account !== null
  }

  // ============================================================================
  // Calendar CRUD Operations
  // ============================================================================

  async fetchCalendars(): Promise<CalDavResponse<CalDavCalendar[]>> {
    if (!this._account) {
      return { success: false, error: 'Not connected to server' }
    }

    return withErrorHandling(async () => {
      const davCalendars = await davFetchCalendars({
        account: {
          serverUrl: this._account!.serverUrl,
          rootUrl: this._account!.rootUrl,
          principalUrl: this._account!.principalUrl,
          homeUrl: this._account!.homeUrl,
          accountType: 'caldav',
        },
        headers: this._account!.headers,
        fetchOptions: this._account!.fetchOptions,
      })

      const calendars: CalDavCalendar[] = davCalendars.map((dav) => ({
        url: dav.url,
        displayName: typeof dav.displayName === 'string' ? dav.displayName : '',
        description: typeof dav.description === 'string' ? dav.description : undefined,
        color: dav.calendarColor,
        ctag: dav.ctag,
        syncToken: dav.syncToken,
        timezone: typeof dav.timezone === 'string' ? dav.timezone : undefined,
        components: dav.components,
        resourcetype: dav.resourcetype ? Object.keys(dav.resourcetype) : undefined,
        headers: this._account!.headers,
        fetchOptions: this._account!.fetchOptions,
      }))

      this._calendars.clear()
      calendars.forEach((cal) => this._calendars.set(cal.url, cal))

      return calendars
    }, 'Failed to fetch calendars')
  }

  async fetchCalendar(calendarUrl: string): Promise<CalDavResponse<CalDavCalendar>> {
    return withErrorHandling(async () => {
      const response = await propfind({
        url: calendarUrl,
        props: CALENDAR_PROPS,
        headers: this._account?.headers,
        fetchOptions: this._account?.fetchOptions,
      })

      const rs = response[0]
      if (!rs.ok) {
        throw new Error(`Calendar not found: ${rs.status}`)
      }

      const calendar: CalDavCalendar = {
        url: calendarUrl,
        displayName: rs.props?.displayname?._cdata ?? rs.props?.displayname ?? '',
        description: rs.props?.calendarDescription,
        color: rs.props?.calendarColor,
        ctag: rs.props?.getctag,
        syncToken: rs.props?.syncToken,
        timezone: rs.props?.calendarTimezone,
        components: parseCalendarComponents(rs.props?.supportedCalendarComponentSet),
        resourcetype: rs.props?.resourcetype ? Object.keys(rs.props.resourcetype) : undefined,
        headers: this._account?.headers,
        fetchOptions: this._account?.fetchOptions,
      }

      this._calendars.set(calendar.url, calendar)
      return calendar
    }, 'Failed to fetch calendar')
  }

  async createCalendar(params: CalDavCalendarCreate): Promise<CalDavResponse<CalDavCalendar>> {
    if (!this._account?.homeUrl) {
      return { success: false, error: 'Not connected or home URL not available' }
    }

    return withErrorHandling(async () => {
      const calendarUrl = `${this._account!.homeUrl}${crypto.randomUUID()}/`

      // Build props for makeCalendar
      const props: Record<string, unknown> = {
        displayname: params.displayName,
      }

      if (params.description) {
        props[`${DAVNamespaceShort.CALDAV}:calendar-description`] = params.description
      }

      if (params.color) {
        props[`${DAVNamespaceShort.CALDAV_APPLE}:calendar-color`] = params.color
      }

      if (params.timezone) {
        props[`${DAVNamespaceShort.CALDAV}:calendar-timezone`] = params.timezone
      }

      // Use tsdav's makeCalendar
      const responses = await davMakeCalendar({
        url: calendarUrl,
        props,
        headers: this._account!.headers,
        fetchOptions: this._account!.fetchOptions,
      })

      // Check response
      const response = responses[0]
      if (response && !response.ok && response.status && response.status >= 400) {
        throw new Error(`Failed to create calendar: ${response.status}`)
      }

      // Fetch the created calendar to get all properties
      const calendarResult = await this.fetchCalendar(calendarUrl)
      if (!calendarResult.success || !calendarResult.data) {
        throw new Error(calendarResult.error || 'Failed to fetch created calendar')
      }

      return calendarResult.data
    }, 'Failed to create calendar')
  }

  async updateCalendar(
    calendarUrl: string,
    params: CalDavCalendarUpdate
  ): Promise<CalDavResponse<CalDavCalendar>> {
    if (!params.displayName && !params.description && !params.color) {
      return { success: false, error: 'No properties to update' }
    }

    const body = buildProppatchXml(params)

    const result = await executeDavRequest({
      url: calendarUrl,
      method: 'PROPPATCH',
      body,
      headers: this._account?.headers,
      fetchOptions: this._account?.fetchOptions,
    })

    if (!result.success) {
      return { success: false, error: result.error, status: result.status }
    }

    return this.fetchCalendar(calendarUrl)
  }

  async deleteCalendar(calendarUrl: string): Promise<CalDavResponse> {
    const result = await executeDavRequest({
      url: calendarUrl,
      method: 'DELETE',
      body: '',
      headers: this._account?.headers,
      fetchOptions: this._account?.fetchOptions,
    })

    if (result.success) {
      this._calendars.delete(calendarUrl)
    }

    return result
  }

  getCalendar(calendarUrl: string): CalDavCalendar | undefined {
    return this._calendars.get(calendarUrl)
  }

  getCalendars(): CalDavCalendar[] {
    return Array.from(this._calendars.values())
  }

  // ============================================================================
  // Event CRUD Operations
  // ============================================================================

  async fetchEvents(calendarUrl: string, filter?: EventFilter): Promise<CalDavResponse<CalDavEvent[]>> {
    const calendar = this._calendars.get(calendarUrl)
    if (!calendar) {
      return { success: false, error: 'Calendar not found in cache. Fetch calendars first.' }
    }

    return withErrorHandling(async () => {
      const timeRange = filter?.timeRange
        ? {
            start:
              typeof filter.timeRange.start === 'string'
                ? filter.timeRange.start
                : filter.timeRange.start.toISOString(),
            end:
              typeof filter.timeRange.end === 'string'
                ? filter.timeRange.end
                : filter.timeRange.end.toISOString(),
          }
        : undefined

      const davObjects = await davFetchCalendarObjects({
        calendar: {
          url: calendar.url,
          ctag: calendar.ctag,
          syncToken: calendar.syncToken,
        },
        timeRange,
        expand: filter?.expand ?? false,
        headers: calendar.headers,
        fetchOptions: calendar.fetchOptions,
      })

      const events: CalDavEvent[] = davObjects.map((obj) => ({
        url: obj.url,
        etag: obj.etag,
        calendarUrl,
        data: convertIcsCalendar(undefined, obj.data),
      }))

      events.forEach((evt) => this._events.set(evt.url, evt))
      return events
    }, 'Failed to fetch events')
  }

  /**
   * Add EXDATE to a recurring event to exclude specific occurrences
   */
  async addExdateToEvent(
    eventUrl: string,
    exdateToAdd: Date,
    etag?: string
  ): Promise<CalDavResponse<{ etag?: string }>> {
    return withErrorHandling(async () => {
      // Fetch the raw ICS file
      const fetchResponse = await fetch(eventUrl, {
        method: 'GET',
        headers: {
          Accept: 'text/calendar',
          ...this._account?.headers,
        },
        ...this._account?.fetchOptions,
      })

      if (!fetchResponse.ok) {
        throw new Error(`Failed to fetch event: ${fetchResponse.status}`)
      }

      let icsText = await fetchResponse.text()

      // Extract DTSTART format from the VEVENT block (not VTIMEZONE)
      // Match DTSTART that comes after BEGIN:VEVENT
      const veventMatch = icsText.match(/BEGIN:VEVENT[\s\S]*?DTSTART(;[^\r\n]*)?:([^\r\n]+)/)
      let exdateLine = ''

      if (veventMatch) {
        const dtstartParams = veventMatch[1] || ''
        const dtstartValue = veventMatch[2]

        // Check if it's a DATE-only value (YYYYMMDD format, 8 chars)
        const isDateOnly = dtstartValue.trim().length === 8

        // Format the EXDATE to match DTSTART format
        const pad = (n: number) => n.toString().padStart(2, '0')

        if (isDateOnly) {
          // DATE format: YYYYMMDD
          const year = exdateToAdd.getFullYear()
          const month = pad(exdateToAdd.getMonth() + 1)
          const day = pad(exdateToAdd.getDate())
          const formattedDate = `${year}${month}${day}`
          exdateLine = `EXDATE${dtstartParams}:${formattedDate}`
        } else {
          // DATE-TIME format
          const pad = (n: number) => n.toString().padStart(2, '0')

          // Extract time from DTSTART value (format: YYYYMMDDTHHMMSS or YYYYMMDDTHHMMSSZ)
          const timeMatch = dtstartValue.match(/T(\d{2})(\d{2})(\d{2})/)
          const originalHours = timeMatch ? timeMatch[1] : '00'
          const originalMinutes = timeMatch ? timeMatch[2] : '00'
          const originalSeconds = timeMatch ? timeMatch[3] : '00'

          // If DTSTART has TZID, use local time in that timezone
          // Otherwise use UTC with Z suffix
          if (dtstartParams.includes('TZID')) {
            // Use the DATE from exdateToAdd but TIME from original DTSTART
            const year = exdateToAdd.getFullYear()
            const month = pad(exdateToAdd.getMonth() + 1)
            const day = pad(exdateToAdd.getDate())
            const formattedDate = `${year}${month}${day}T${originalHours}${originalMinutes}${originalSeconds}`
            exdateLine = `EXDATE${dtstartParams}:${formattedDate}`
          } else {
            // Use UTC time with Z suffix
            const year = exdateToAdd.getUTCFullYear()
            const month = pad(exdateToAdd.getUTCMonth() + 1)
            const day = pad(exdateToAdd.getUTCDate())
            const formattedDate = `${year}${month}${day}T${originalHours}${originalMinutes}${originalSeconds}Z`
            exdateLine = `EXDATE${dtstartParams}:${formattedDate}`
          }
        }
      } else {
        // Fallback if DTSTART not found - use UTC DATE-TIME format
        const pad = (n: number) => n.toString().padStart(2, '0')
        const year = exdateToAdd.getUTCFullYear()
        const month = pad(exdateToAdd.getUTCMonth() + 1)
        const day = pad(exdateToAdd.getUTCDate())
        const hours = pad(exdateToAdd.getUTCHours())
        const minutes = pad(exdateToAdd.getUTCMinutes())
        const seconds = pad(exdateToAdd.getUTCSeconds())
        const formattedDate = `${year}${month}${day}T${hours}${minutes}${seconds}Z`
        exdateLine = `EXDATE:${formattedDate}`
      }

      // Find the RRULE line in the VEVENT block and add EXDATE after it
      const lines = icsText.split('\n')
      const newLines: string[] = []
      let exdateAdded = false
      let inVEvent = false

      // Extract just the date value from our exdateLine for appending
      const exdateValueMatch = exdateLine.match(/:([^\r\n]+)$/)
      const exdateValue = exdateValueMatch ? exdateValueMatch[1] : ''

      for (let i = 0; i < lines.length; i++) {
        const line = lines[i].trim()

        // Track if we're inside a VEVENT block
        if (line === 'BEGIN:VEVENT') {
          inVEvent = true
          newLines.push(lines[i])
        } else if (line === 'END:VEVENT') {
          inVEvent = false
          newLines.push(lines[i])
        }
        // If EXDATE already exists in VEVENT, append to it
        else if (inVEvent && !exdateAdded && (line.startsWith('EXDATE:') || line.startsWith('EXDATE;'))) {
          newLines.push(`${lines[i]},${exdateValue}`)
          exdateAdded = true
        }
        // Only add EXDATE after RRULE if we're inside VEVENT and no EXDATE exists yet
        else if (inVEvent && !exdateAdded && line.startsWith('RRULE:')) {
          newLines.push(lines[i])
          newLines.push(exdateLine)
          exdateAdded = true
        }
        else {
          newLines.push(lines[i])
        }
      }

      icsText = newLines.join('\n')

      // Update the event with modified ICS
      const updateResponse = await fetch(eventUrl, {
        method: 'PUT',
        headers: {
          'Content-Type': 'text/calendar; charset=utf-8',
          ...(etag ? { 'If-Match': etag } : {}),
          ...this._account?.headers,
        },
        body: icsText,
        ...this._account?.fetchOptions,
      })

      if (!updateResponse.ok) {
        throw new Error(`Failed to update event: ${updateResponse.status}`)
      }

      const newEtag = updateResponse.headers.get('ETag') || undefined

      return { etag: newEtag }
    }, 'Failed to add EXDATE to event')
  }

  async fetchEvent(eventUrl: string): Promise<CalDavResponse<CalDavEvent>> {
    return withErrorHandling(async () => {
      const fetchResponse = await fetch(eventUrl, {
        method: 'GET',
        headers: {
          Accept: 'text/calendar',
          ...this._account?.headers,
        },
        ...this._account?.fetchOptions,
      })

      if (!fetchResponse.ok) {
        throw new Error(`Event not found: ${fetchResponse.status}`)
      }

      const icsData = await fetchResponse.text()
      const calendarUrl = getCalendarUrlFromEventUrl(eventUrl)

      const event: CalDavEvent = {
        url: eventUrl,
        etag: fetchResponse.headers.get('etag') ?? undefined,
        calendarUrl,
        data: convertIcsCalendar(undefined, icsData),
      }

      this._events.set(event.url, event)
      return event
    }, 'Failed to fetch event')
  }

  async createEvent(params: CalDavEventCreate): Promise<CalDavResponse<CalDavEvent>> {
    const calendar = this._calendars.get(params.calendarUrl)
    if (!calendar) {
      return { success: false, error: 'Calendar not found' }
    }

    return withErrorHandling(async () => {
      const event = { ...params.event }
      if (!event.uid) {
        event.uid = crypto.randomUUID()
      }

      const icsCalendar: IcsCalendar = {
        prodId: '-//CalDavService//NONSGML v1.0//EN',
        version: '2.0',
        events: [event],
      }

      this.validateTimezones(icsCalendar)
      const iCalString = generateIcsCalendar(icsCalendar)

      const response = await davCreateCalendarObject({
        calendar: {
          url: calendar.url,
          ctag: calendar.ctag,
          syncToken: calendar.syncToken,
        },
        iCalString,
        filename: `${event.uid}.ics`,
        headers: calendar.headers,
        fetchOptions: calendar.fetchOptions,
      })

      if (!response.ok) {
        throw new Error(`Failed to create event: ${response.status}`)
      }

      const eventUrl = `${params.calendarUrl}${event.uid}.ics`
      const createdEvent: CalDavEvent = {
        url: eventUrl,
        etag: response.headers.get('etag') ?? undefined,
        calendarUrl: params.calendarUrl,
        data: icsCalendar,
      }

      this._events.set(createdEvent.url, createdEvent)
      return createdEvent
    }, 'Failed to create event')
  }

  async updateEvent(params: CalDavEventUpdate): Promise<CalDavResponse<CalDavEvent>> {
    const cachedEvent = this._events.get(params.eventUrl)
    const calendarUrl = cachedEvent?.calendarUrl ?? getCalendarUrlFromEventUrl(params.eventUrl)
    const calendar = this._calendars.get(calendarUrl)

    if (!calendar) {
      return { success: false, error: 'Calendar not found' }
    }

    return withErrorHandling(async () => {
      const icsCalendar: IcsCalendar = cachedEvent?.data ?? {
        prodId: '-//CalDavService//NONSGML v1.0//EN',
        version: '2.0',
        events: [],
      }

      const existingIndex = icsCalendar.events?.findIndex((e) => e.uid === params.event.uid) ?? -1
      if (existingIndex >= 0 && icsCalendar.events) {
        const updatedEvent = { ...params.event }
        updatedEvent.sequence = (updatedEvent.sequence ?? 0) + 1
        icsCalendar.events[existingIndex] = updatedEvent
      } else {
        icsCalendar.events = [params.event]
      }

      this.validateTimezones(icsCalendar)
      const iCalString = generateIcsCalendar(icsCalendar)

      const davObject: DAVCalendarObject = {
        url: params.eventUrl,
        etag: params.etag ?? cachedEvent?.etag,
        data: iCalString,
      }

      const response = await davUpdateCalendarObject({
        calendarObject: davObject,
        headers: calendar.headers,
        fetchOptions: calendar.fetchOptions,
      })

      if (!response.ok) {
        throw new Error(`Failed to update event: ${response.status}`)
      }

      const updatedEvent: CalDavEvent = {
        url: params.eventUrl,
        etag: response.headers.get('etag') ?? undefined,
        calendarUrl,
        data: icsCalendar,
      }

      this._events.set(updatedEvent.url, updatedEvent)
      return updatedEvent
    }, 'Failed to update event')
  }

  async deleteEvent(eventUrl: string): Promise<CalDavResponse> {
    const cachedEvent = this._events.get(eventUrl)
    const calendarUrl = cachedEvent?.calendarUrl ?? getCalendarUrlFromEventUrl(eventUrl)
    const calendar = this._calendars.get(calendarUrl)

    return withErrorHandling(async () => {
      const davObject: DAVCalendarObject = {
        url: eventUrl,
        etag: cachedEvent?.etag,
        data: cachedEvent?.data ? generateIcsCalendar(cachedEvent.data) : '',
      }

      const response = await davDeleteCalendarObject({
        calendarObject: davObject,
        headers: calendar?.headers,
        fetchOptions: calendar?.fetchOptions,
      })

      if (!response.ok && response.status !== 204) {
        throw new Error(`Failed to delete event: ${response.status}`)
      }

      this._events.delete(eventUrl)
      return undefined
    }, 'Failed to delete event')
  }

  getEvent(eventUrl: string): CalDavEvent | undefined {
    return this._events.get(eventUrl)
  }

  getEventsForCalendar(calendarUrl: string): CalDavEvent[] {
    return Array.from(this._events.values()).filter((e) => e.calendarUrl === calendarUrl)
  }

  // ============================================================================
  // Calendar Sharing (CalDAV Sharing Extension)
  // ============================================================================

  async shareCalendar(params: CalDavShareInvite): Promise<CalDavResponse<CalDavShareResponse>> {
    const calendar = this._calendars.get(params.calendarUrl)
    if (!calendar) {
      return { success: false, error: 'Calendar not found' }
    }

    const shareeParams: ShareeXmlParams[] = params.sharees.map((s) => ({
      href: s.href,
      displayName: s.displayName,
      privilege: s.privilege,
      summary: params.summary,
    }))

    const body = buildShareRequestXml(shareeParams)

    const result = await executeDavRequest({
      url: params.calendarUrl,
      method: 'POST',
      body,
      headers: this._account?.headers,
      fetchOptions: this._account?.fetchOptions,
    })

    if (!result.success) {
      return { success: false, error: result.error, status: result.status }
    }

    return {
      success: true,
      data: {
        success: true,
        sharees: params.sharees.map((s) => ({ ...s, status: 'pending' as const })),
      },
    }
  }

  async unshareCalendar(calendarUrl: string, shareeHref: string): Promise<CalDavResponse> {
    const body = buildUnshareRequestXml(shareeHref)

    return executeDavRequest({
      url: calendarUrl,
      method: 'POST',
      body,
      headers: this._account?.headers,
      fetchOptions: this._account?.fetchOptions,
    })
  }

  async getShareInvitations(): Promise<CalDavResponse<CalDavInvitation[]>> {
    if (!this._account?.homeUrl) {
      return { success: false, error: 'Not connected' }
    }

    return withErrorHandling(async () => {
      const response = await propfind({
        url: this._account!.homeUrl!,
        props: { [`${DAVNamespaceShort.CALENDAR_SERVER}:notification-URL`]: {} },
        headers: this._account!.headers,
        fetchOptions: this._account!.fetchOptions,
        depth: '0',
      })

      const notificationUrl = response[0]?.props?.['notification-URL']?.href
      if (!notificationUrl) {
        return []
      }

      const notificationsResponse = await propfind({
        url: notificationUrl,
        props: { [`${DAVNamespaceShort.CALENDAR_SERVER}:notification`]: {} },
        headers: this._account!.headers,
        fetchOptions: this._account!.fetchOptions,
        depth: '1',
      })

      const invitations: CalDavInvitation[] = []
      for (const item of notificationsResponse) {
        const notification = item.props?.notification
        if (notification?.['invite-notification']) {
          const invite = notification['invite-notification']
          invitations.push({
            uid: invite.uid || crypto.randomUUID(),
            calendarUrl: invite['hosturl']?.href || '',
            ownerHref: invite['organizer']?.href || '',
            ownerDisplayName: invite['organizer']?.['common-name'],
            summary: invite.summary,
            privilege: parseSharePrivilege(invite['access']),
            status: 'pending',
          })
        }
      }

      return invitations
    }, 'Failed to get invitations')
  }

  async acceptShareInvitation(
    invitationUid: string,
    inReplyTo: string
  ): Promise<CalDavResponse<CalDavCalendar>> {
    return this.respondToShareInvitation(invitationUid, inReplyTo, true)
  }

  async declineShareInvitation(invitationUid: string, inReplyTo: string): Promise<CalDavResponse> {
    const result = await this.respondToShareInvitation(invitationUid, inReplyTo, false)
    return { success: result.success, error: result.error, status: result.status }
  }

  private async respondToShareInvitation(
    _invitationUid: string,
    inReplyTo: string,
    accept: boolean
  ): Promise<CalDavResponse<CalDavCalendar>> {
    if (!this._account?.homeUrl) {
      return { success: false, error: 'Not connected' }
    }

    const body = buildInviteReplyXml(inReplyTo, accept)

    const result = await executeDavRequest({
      url: this._account.homeUrl,
      method: 'POST',
      body,
      headers: this._account.headers,
      fetchOptions: this._account.fetchOptions,
    })

    if (!result.success) {
      return { success: false, error: result.error, status: result.status }
    }

    if (accept) {
      await this.fetchCalendars()
    }

    return { success: true }
  }

  async getCalendarSharees(calendarUrl: string): Promise<CalDavResponse<CalDavSharee[]>> {
    return withErrorHandling(async () => {
      const response = await propfind({
        url: calendarUrl,
        props: { [`${DAVNamespaceShort.CALENDAR_SERVER}:invite`]: {} },
        headers: this._account?.headers,
        fetchOptions: this._account?.fetchOptions,
        depth: '0',
      })

      const invite = response[0]?.props?.invite
      if (!invite?.user) {
        return []
      }

      const users = Array.isArray(invite.user) ? invite.user : [invite.user]
      return users.map((user: Record<string, unknown>) => ({
        href: (user.href as string) || '',
        displayName: user['common-name'] as string | undefined,
        privilege: parseSharePrivilege(user.access),
        status: parseShareStatus(user['invite-accepted'], user['invite-noresponse']),
      }))
    }, 'Failed to get sharees')
  }

  // ============================================================================
  // Scheduling (iTIP - RFC 5546)
  // ============================================================================

  async sendSchedulingRequest(request: SchedulingRequest): Promise<CalDavResponse<SchedulingResponse>> {
    if (!this._account) {
      return { success: false, error: 'Not connected' }
    }

    return withErrorHandling(async () => {
      const event = { ...request.event }
      event.organizer = {
        email: request.organizer.email,
        name: request.organizer.name,
      }
      event.attendees = request.attendees.map((att) => ({
        email: att.email,
        name: att.name,
        role: att.role,
        partstat: att.partstat ?? 'NEEDS-ACTION',
        rsvp: att.rsvp,
      }))

      const icsCalendar: IcsCalendar = {
        prodId: '-//CalDavService//NONSGML v1.0//EN',
        version: '2.0',
        method: request.method,
        events: [event],
      }

      this.validateTimezones(icsCalendar)
      const iCalString = generateIcsCalendar(icsCalendar)

      const outboxUrl = await this.findSchedulingOutbox()
      if (!outboxUrl) {
        throw new Error('Scheduling outbox not found')
      }

      // Construct full URL - outboxUrl is relative to serverUrl
      const fullOutboxUrl = outboxUrl.startsWith('http')
        ? outboxUrl
        : `${this._account!.serverUrl}${outboxUrl.startsWith('/') ? outboxUrl.slice(1) : outboxUrl}`

      // Use fetch directly to avoid davRequest URL construction issues in dev mode
      const response = await fetch(fullOutboxUrl, {
        method: 'POST',
        headers: {
          'Content-Type': 'text/calendar; charset=utf-8; method=' + request.method,
          ...this._account!.headers,
        },
        body: iCalString,
        ...this._account!.fetchOptions,
      })

      if (!response.ok) {
        const errorText = await response.text()
        throw new Error(`Failed to send scheduling request: ${response.status} - ${errorText}`)
      }

      return {
        success: true,
        responses: request.attendees.map((att) => ({
          recipient: att.email,
          status: 'delivered' as const,
        })),
      }
    }, 'Failed to send scheduling request')
  }

  async respondToMeeting(
    eventUrl: string,
    event: IcsEvent,
    attendeeEmail: string,
    status: CalDavAttendee['partstat'],
    etag?: string
  ): Promise<CalDavResponse<SchedulingResponse>> {
    const attendee = event.attendees?.find(
      (a) => a.email.toLowerCase() === attendeeEmail.toLowerCase()
    )

    if (!attendee) {
      return { success: false, error: 'Attendee not found in event' }
    }

    // Update the event with the new participation status
    // Sabre/DAV will automatically detect the change and send a REPLY to the organizer
    const updatedEvent = {
      ...event,
      attendees: event.attendees?.map(att =>
        att.email.toLowerCase() === attendeeEmail.toLowerCase()
          ? { ...att, partstat: status }
          : att
      ),
    }

    const result = await this.updateEvent({
      eventUrl,
      event: updatedEvent,
      etag,
    })

    if (!result.success) {
      return { success: false, error: result.error || 'Failed to update event' }
    }

    return {
      success: true,
      data: {
        success: true,
        responses: [{
          recipient: event.organizer?.email || '',
          status: 'delivered' as const,
        }],
      },
    }
  }

  // ============================================================================
  // Free/Busy Queries
  // ============================================================================

  async queryFreeBusy(request: FreeBusyRequest): Promise<CalDavResponse<FreeBusyResponse[]>> {
    if (!this._account) {
      return { success: false, error: 'Not connected' }
    }

    return withErrorHandling(async () => {
      const outboxUrl = await this.findSchedulingOutbox()
      if (!outboxUrl) {
        throw new Error('Scheduling outbox not found')
      }

      const startStr =
        typeof request.timeRange.start === 'string'
          ? request.timeRange.start
          : request.timeRange.start.toISOString()
      const endStr =
        typeof request.timeRange.end === 'string'
          ? request.timeRange.end
          : request.timeRange.end.toISOString()

      const attendeeLines = request.attendees.map((email) => `ATTENDEE:mailto:${email}`).join('\n')

      const fbRequest = `BEGIN:VCALENDAR
VERSION:2.0
PRODID:-//CalDavService//NONSGML v1.0//EN
METHOD:REQUEST
BEGIN:VFREEBUSY
DTSTART:${startStr.replace(/[-:]/g, '').split('.')[0]}Z
DTEND:${endStr.replace(/[-:]/g, '').split('.')[0]}Z
${request.organizer ? `ORGANIZER:mailto:${request.organizer.email}` : ''}
${attendeeLines}
END:VFREEBUSY
END:VCALENDAR`

      const responses = await davRequest({
        url: outboxUrl,
        init: {
          method: 'POST',
          headers: {
            'Content-Type': 'text/calendar; charset=utf-8',
            ...this._account!.headers,
          },
          body: fbRequest,
        },
        fetchOptions: this._account!.fetchOptions,
      })

      const response = responses[0]
      if (!response?.ok) {
        throw new Error(`Failed to query free/busy: ${response?.status}`)
      }

      return request.attendees.map((email) => ({
        attendee: email,
        periods: [],
      }))
    }, 'Failed to query free/busy')
  }

  // ============================================================================
  // Sync Operations
  // ============================================================================

  async syncCalendar(calendarUrl: string, options?: SyncOptions): Promise<CalDavResponse<SyncReport>> {
    const calendar = this._calendars.get(calendarUrl)
    if (!calendar) {
      return { success: false, error: 'Calendar not found' }
    }

    return withErrorHandling(async () => {
      const syncToken = options?.syncToken ?? calendar.syncToken ?? ''
      const body = buildSyncCollectionXml({ syncToken, syncLevel: options?.syncLevel })

      const responses = await davRequest({
        url: calendarUrl,
        init: {
          method: 'REPORT',
          headers: {
            'Content-Type': 'application/xml; charset=utf-8',
            Depth: '1',
            ...calendar.headers,
          },
          body,
        },
        fetchOptions: calendar.fetchOptions,
      })

      const response = responses[0]
      if (!response?.ok) {
        throw new Error(`Failed to sync calendar: ${response?.status}`)
      }

      const newSyncToken = (response.props?.['sync-token'] as string) ?? ''

      return {
        syncToken: newSyncToken,
        changed: [],
        deleted: [],
      }
    }, 'Failed to sync calendar')
  }

  // ============================================================================
  // ACL Operations
  // ============================================================================

  async getCalendarAcl(calendarUrl: string): Promise<CalDavResponse<CalendarAcl>> {
    return withErrorHandling(async () => {
      const response = await propfind({
        url: calendarUrl,
        props: {
          [`${DAVNamespaceShort.DAV}:acl`]: {},
          [`${DAVNamespaceShort.DAV}:owner`]: {},
        },
        headers: this._account?.headers,
        fetchOptions: this._account?.fetchOptions,
        depth: '0',
      })

      const rs = response[0]
      if (!rs.ok) {
        throw new Error(`Failed to get ACL: ${rs.status}`)
      }

      return {
        calendarUrl,
        entries: [],
        ownerHref: rs.props?.owner?.href,
      }
    }, 'Failed to get ACL')
  }

  // ============================================================================
  // Principal Operations
  // ============================================================================

  async getPrincipal(principalUrl?: string): Promise<CalDavResponse<CalDavPrincipal>> {
    const url = principalUrl ?? this._account?.principalUrl
    if (!url) {
      return { success: false, error: 'Principal URL not available' }
    }

    return withErrorHandling(async () => {
      const response = await propfind({
        url,
        props: {
          [`${DAVNamespaceShort.DAV}:displayname`]: {},
          [`${DAVNamespaceShort.CALDAV}:calendar-home-set`]: {},
          [`${DAVNamespaceShort.CARDDAV}:addressbook-home-set`]: {},
          [`${DAVNamespaceShort.CALENDAR_SERVER}:email-address-set`]: {},
        },
        headers: this._account?.headers,
        fetchOptions: this._account?.fetchOptions,
        depth: '0',
      })

      const rs = response[0]
      if (!rs.ok) {
        throw new Error(`Failed to get principal: ${rs.status}`)
      }

      return {
        url,
        displayName: rs.props?.displayname?._cdata ?? rs.props?.displayname,
        email: rs.props?.['email-address-set']?.['email-address'],
        calendarHomeSet: rs.props?.['calendar-home-set']?.href,
        addressBookHomeSet: rs.props?.['addressbook-home-set']?.href,
      }
    }, 'Failed to get principal')
  }

  async searchPrincipals(query: string): Promise<CalDavResponse<CalDavPrincipal[]>> {
    if (!this._account?.principalUrl) {
      return { success: false, error: 'Not connected' }
    }

    const body = buildPrincipalSearchXml(query)

    const result = await executeDavRequest({
      url: this._account.principalUrl,
      method: 'REPORT',
      body,
      headers: { Depth: '0', ...this._account.headers },
      fetchOptions: this._account.fetchOptions,
    })

    if (!result.success) {
      return { success: false, error: result.error, status: result.status }
    }

    return { success: true, data: [] }
  }

  // ============================================================================
  // Utility Methods
  // ============================================================================

  clearCache(): void {
    this._calendars.clear()
    this._events.clear()
  }

  disconnect(): void {
    this._account = null
    this.clearCache()
  }

  // ============================================================================
  // Private Helper Methods
  // ============================================================================

  private validateTimezones(calendarData: IcsCalendar): void {
    const usedTimezones =
      calendarData.events?.flatMap((e) => [e.start.local?.timezone, e.end?.local?.timezone]) ?? []
    const wantedTzIds = new Set(usedTimezones.filter((s): s is string => s !== undefined))

    calendarData.timezones ??= []
    calendarData.timezones = calendarData.timezones.filter((tz) => wantedTzIds.has(tz.id))

    wantedTzIds.forEach((tzid) => {
      if (calendarData.timezones!.findIndex((t) => t.id === tzid) === -1) {
        const tzBlock = getIcalTimezoneBlock(tzid)[0]
        if (tzBlock) {
          calendarData.timezones!.push(convertIcsTimezone(undefined, tzBlock))
        }
      }
    })
  }

  private async findSchedulingOutbox(): Promise<string | null> {
    if (!this._account?.principalUrl) return null

    try {
      const response = await propfind({
        url: this._account.principalUrl,
        props: { [`${DAVNamespaceShort.CALDAV}:schedule-outbox-URL`]: {} },
        headers: this._account.headers,
        fetchOptions: this._account.fetchOptions,
        depth: '0',
      })

      // Note: tsdav converts XML property names to camelCase
      return response[0]?.props?.['scheduleOutboxURL']?.href ?? null
    } catch {
      return null
    }
  }

  /**
   * Get scheduling capabilities of the server
   * Useful for diagnosing if the server supports email notifications (IMip)
   */
  async getSchedulingCapabilities(): Promise<CalDavResponse<{
    hasSchedulingSupport: boolean
    scheduleOutboxUrl: string | null
    scheduleInboxUrl: string | null
    calendarUserAddressSet: string[]
    rawResponse?: any
  }>> {
    if (!this._account?.principalUrl) {
      return { success: false, error: 'Not connected or principal URL not found' }
    }

    return withErrorHandling(async () => {
      const response = await propfind({
        url: this._account!.principalUrl!,
        props: {
          [`${DAVNamespaceShort.CALDAV}:schedule-outbox-URL`]: {},
          [`${DAVNamespaceShort.CALDAV}:schedule-inbox-URL`]: {},
          [`${DAVNamespaceShort.CALDAV}:calendar-user-address-set`]: {},
        },
        headers: this._account!.headers,
        fetchOptions: this._account!.fetchOptions,
        depth: '0',
      })

      const props = response[0]?.props ?? {}

      // Note: tsdav converts XML property names to camelCase
      // schedule-outbox-URL becomes scheduleOutboxURL
      // schedule-inbox-URL becomes scheduleInboxURL
      // calendar-user-address-set becomes calendarUserAddressSet
      const scheduleOutboxUrl = props['scheduleOutboxURL']?.href ?? null
      const scheduleInboxUrl = props['scheduleInboxURL']?.href ?? null

      // calendar-user-address-set contains email addresses used for scheduling
      const addressSet = props['calendarUserAddressSet']
      const calendarUserAddressSet: string[] = []

      if (addressSet && typeof addressSet === 'object' && 'href' in addressSet) {
        // Can be single href or array of hrefs
        const hrefs = Array.isArray(addressSet.href) ? addressSet.href : [addressSet.href]
        hrefs.forEach((href: string) => {
          if (href && typeof href === 'string') {
            calendarUserAddressSet.push(href)
          }
        })
      }

      return {
        hasSchedulingSupport: !!(scheduleOutboxUrl && scheduleInboxUrl),
        scheduleOutboxUrl,
        scheduleInboxUrl,
        calendarUserAddressSet,
        rawResponse: response,
      }
    }, 'Failed to get scheduling capabilities')
  }
}

export function createCalDavService(): CalDavService {
  return new CalDavService()
}
