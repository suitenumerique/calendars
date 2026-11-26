/**
 * Wrap an async event source so that only its latest call gives a result.
 * The calendar applies each result when its fetch ends. Without this wrapper,
 * a slow old fetch can replace the events of a newer fetch.
 * An old call reports a failure, so the calendar stops its loading state.
 */
export const latestOnly = <A, R>(fetchEvents: (arg: A) => Promise<R>) => {
  let latest = 0;
  return (arg: A, success: (result: R) => void, failure: (error?: unknown) => void): void => {
    const call = ++latest;
    fetchEvents(arg).then((result) => (call === latest ? success(result) : failure()), failure);
  };
};
