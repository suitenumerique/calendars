/** The date and time of an instant in an IANA timezone. */
export type DateComponents = {
  year: number;
  month: number; // 1-12 (not 0-11 like JS Date)
  day: number;
  hours: number;
  minutes: number;
  seconds: number;
};

const FORMATTER_CACHE_MAX_SIZE = 50;

const utcDateComponents = (date: Date): DateComponents => ({
  year: date.getUTCFullYear(),
  month: date.getUTCMonth() + 1,
  day: date.getUTCDate(),
  hours: date.getUTCHours(),
  minutes: date.getUTCMinutes(),
  seconds: date.getUTCSeconds(),
});

/**
 * Converts UTC instants to date components in IANA timezones.
 *
 * Each instance keeps a cache of Intl formatters, and the timezones that
 * Intl rejected. For a rejected timezone, the converter gives UTC
 * components at once. It does not call Intl again, and it logs no new
 * warning.
 */
export class TimezoneConverter {
  private readonly formatters = new Map<string, Intl.DateTimeFormat>();
  private readonly failed = new Set<string>();

  /** Tell if Intl rejected the timezone. */
  hasFailed(timezone: string): boolean {
    return this.failed.has(timezone);
  }

  /**
   * Extract date/time components from a UTC instant in a specific timezone.
   *
   * Uses Intl.DateTimeFormat to correctly handle DST transitions and
   * non-standard offsets (e.g., UTC+5:30 for India, UTC+5:45 for Nepal).
   *
   * If Intl rejects the timezone, returns the UTC components of the date
   * and logs a warning.
   */
  getDateComponents(date: Date, timezone: string): DateComponents {
    if (this.failed.has(timezone)) {
      return utcDateComponents(date);
    }
    let formatter = this.formatters.get(timezone);
    if (!formatter) {
      if (this.formatters.size >= FORMATTER_CACHE_MAX_SIZE) {
        const firstKey = this.formatters.keys().next().value;
        this.formatters.delete(firstKey as string);
      }
      try {
        formatter = new Intl.DateTimeFormat("en-US", {
          timeZone: timezone,
          year: "numeric",
          month: "2-digit",
          day: "2-digit",
          hour: "2-digit",
          minute: "2-digit",
          second: "2-digit",
          hour12: false,
        });
      } catch (error) {
        // Intl throws a RangeError for a timezone that it does not know.
        // Without this fallback, the conversion throws. UTC components can
        // be wrong by the timezone offset.
        this.failed.add(timezone);
        console.warn(
          `[TimezoneConverter] getDateComponents failed for timezone "${timezone}"; falling back to UTC components:`,
          error,
        );
        return utcDateComponents(date);
      }
      this.formatters.set(timezone, formatter);
    }
    // Only the constructor checks the timezone. Thus, an invalid date
    // throws here and does not mark the timezone as failed.
    const parts = formatter.formatToParts(date);

    const get = (type: Intl.DateTimeFormatPartTypes): number => {
      const part = parts.find((p) => p.type === type);
      return part ? parseInt(part.value, 10) : 0;
    };

    return {
      year: get("year"),
      month: get("month"),
      day: get("day"),
      hours: get("hour") === 24 ? 0 : get("hour"), // Intl may return 24 for midnight
      minutes: get("minute"),
      seconds: get("second"),
    };
  }
}

const shared = new TimezoneConverter();

/** Tell if Intl knows the timezone. */
export const isKnownTimezone = (timezone: string): boolean => {
  try {
    new Intl.DateTimeFormat("en-US", { timeZone: timezone });
    return true;
  } catch {
    return false;
  }
};

/**
 * Give the wall-clock time of `date` in `timezone`. The result stores
 * that time in UTC fields ("fake UTC"), so 10:00 in Paris becomes 10:00Z.
 *
 * The result has no milliseconds. For a timezone that Intl does not
 * know, the result is the UTC time of `date`.
 */
export const toWallClock = (date: Date, timezone: string): Date => {
  const c = shared.getDateComponents(date, timezone);
  return new Date(Date.UTC(c.year, c.month - 1, c.day, c.hours, c.minutes, c.seconds));
};
