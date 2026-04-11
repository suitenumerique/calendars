/**
 * Calendar feature configuration.
 * Values can be overridden via NEXT_PUBLIC_ environment variables.
 */

const parsePositiveInt = (
  value: string | undefined,
  fallback: number,
): number => {
  const parsed = Number(value);
  return Number.isFinite(parsed) && parsed > 0 ? Math.floor(parsed) : fallback;
};

/** Polling interval for subscription status refresh (milliseconds). Default: 60s. */
export const SYNC_POLL_INTERVAL = parsePositiveInt(
  process.env.NEXT_PUBLIC_SYNC_POLL_INTERVAL,
  60_000,
);

/** Maximum number of subscription channels per user. */
export const MAX_SUBSCRIPTIONS_PER_USER = parsePositiveInt(
  process.env.NEXT_PUBLIC_MAX_SUBSCRIPTIONS_PER_USER,
  20,
);
