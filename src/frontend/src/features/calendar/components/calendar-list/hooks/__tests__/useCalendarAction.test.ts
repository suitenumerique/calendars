import { act } from "react";

import type { CalDavCalendar } from "../../../../services/dav/types/caldav-service";
import { useCalendarAction } from "../useCalendarAction";
import { renderHook } from "./render-hook";

const calendar = {
  url: "http://localhost/caldav/calendars/users/u@example.com/team/",
} as CalDavCalendar;

describe("useCalendarAction", () => {
  beforeEach(() => {
    vi.spyOn(console, "error").mockImplementation(() => {});
  });

  it("reports a request that throws before it returns a promise", async () => {
    const run = vi.fn(() => {
      throw new Error("no service");
    });
    const onError = vi.fn();
    const hook = renderHook(() => useCalendarAction({ run, errorMessage: "Failed:", onError }));

    act(() => hook.current.open(calendar));
    await act(() => hook.current.confirm());

    expect(onError).toHaveBeenCalledOnce();
    expect(hook.current.isLoading).toBe(false);
    expect(hook.current.calendar).toBeNull();
  });

  it("drops the selection when the calendar lacks the data for the request", async () => {
    const onError = vi.fn();
    const hook = renderHook(() =>
      useCalendarAction({ run: () => null, errorMessage: "Failed:", onError }),
    );

    act(() => hook.current.open(calendar));
    await act(() => hook.current.confirm());

    expect(onError).not.toHaveBeenCalled();
    expect(hook.current.calendar).toBeNull();
  });
});
