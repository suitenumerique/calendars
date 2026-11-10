import { act } from "react";

import type { CalDavCalendar } from "../../../../services/dav/types/caldav-service";
import { useCalendarDelete } from "../useCalendarDelete";
import { renderHook } from "./render-hook";

const calendar = {
  url: "http://localhost/caldav/calendars/users/u@example.com/team/",
} as CalDavCalendar;

const deferred = <T>() => {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((r) => {
    resolve = r;
  });
  return { promise, resolve };
};

describe("useCalendarDelete", () => {
  beforeEach(() => {
    vi.spyOn(console, "error").mockImplementation(() => {});
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("deletes the selected calendar", async () => {
    const deleteCalendar = vi.fn().mockResolvedValue({ success: true });
    const onError = vi.fn();
    const hook = renderHook(() => useCalendarDelete({ deleteCalendar, onError }));

    act(() => hook.current.open(calendar));
    expect(hook.current.calendar).toBe(calendar);

    await act(() => hook.current.confirm());

    expect(deleteCalendar).toHaveBeenCalledWith(calendar.url);
    expect(hook.current.calendar).toBeNull();
    expect(hook.current.isLoading).toBe(false);
    expect(onError).not.toHaveBeenCalled();
  });

  it("stops loading and reports a failed delete", async () => {
    const deleteCalendar = vi.fn().mockResolvedValue({ success: false, error: "boom" });
    const onError = vi.fn();
    const hook = renderHook(() => useCalendarDelete({ deleteCalendar, onError }));

    act(() => hook.current.open(calendar));
    await act(() => hook.current.confirm());

    expect(hook.current.isLoading).toBe(false);
    expect(hook.current.calendar).toBeNull();
    expect(onError).toHaveBeenCalledOnce();
  });

  it("stops loading and reports a rejected delete", async () => {
    const deleteCalendar = vi.fn().mockRejectedValue(new Error("network"));
    const onError = vi.fn();
    const hook = renderHook(() => useCalendarDelete({ deleteCalendar, onError }));

    act(() => hook.current.open(calendar));
    await act(() => hook.current.confirm());

    expect(hook.current.isLoading).toBe(false);
    expect(onError).toHaveBeenCalledOnce();
  });

  it("ignores a close while the delete is pending", async () => {
    const pending = deferred<{ success: boolean }>();
    const deleteCalendar = vi.fn().mockReturnValue(pending.promise);
    const hook = renderHook(() => useCalendarDelete({ deleteCalendar, onError: vi.fn() }));

    act(() => hook.current.open(calendar));
    let confirmed!: Promise<void>;
    act(() => {
      confirmed = hook.current.confirm();
    });
    act(() => hook.current.close());

    expect(hook.current.isLoading).toBe(true);
    expect(hook.current.calendar).toBe(calendar);

    await act(async () => {
      pending.resolve({ success: true });
      await confirmed;
    });
    expect(hook.current.isLoading).toBe(false);
    expect(hook.current.calendar).toBeNull();
  });

  it("closes without a request when nothing is pending", () => {
    const deleteCalendar = vi.fn();
    const hook = renderHook(() => useCalendarDelete({ deleteCalendar, onError: vi.fn() }));

    act(() => hook.current.open(calendar));
    act(() => hook.current.close());

    expect(hook.current.calendar).toBeNull();
    expect(deleteCalendar).not.toHaveBeenCalled();
  });
});
