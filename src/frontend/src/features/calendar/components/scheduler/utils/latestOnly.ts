/**
 * Wrap an async event source. A result goes to the success callback only if
 * no newer call started. Without this wrapper, a slow old fetch can replace
 * the events of a newer fetch.
 * An old result or a rejected fetch goes to the failure callback. The calendar
 * then decreases its loading counter and does not show stale events.
 */
export const latestOnly = <A, R>(fetchEvents: (arg: A) => Promise<R>) => {
  let latest = 0;
  return (arg: A, success: (result: R) => void, failure: (error?: unknown) => void): void => {
    const call = ++latest;
    fetchEvents(arg).then((result) => (call === latest ? success(result) : failure()), failure);
  };
};
