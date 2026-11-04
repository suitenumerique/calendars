import { act } from "react";

import type { CalDavCalendar } from "../../../../services/dav/types/caldav-service";
import { useCalendarHiding } from "../useCalendarHiding";
import { renderHook } from "./render-hook";

type Props = Parameters<typeof useCalendarHiding>[0];

const calendar = {
  url: "http://localhost/caldav/calendars/users/u@example.com/team/",
} as CalDavCalendar;

const render = (props: Props) => renderHook(() => useCalendarHiding(props));

describe("useCalendarHiding", () => {
  beforeEach(() => {
    vi.spyOn(console, "error").mockImplementation(() => {});
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("hides and shows the calendar, and resolves to true", async () => {
    const setCalendarHidden = vi.fn().mockResolvedValue({ success: true });
    const onError = vi.fn();
    const hook = render({ setCalendarHidden, onError });

    const results: boolean[] = [];
    await act(async () => {
      results.push(await hook.current.hide(calendar));
      results.push(await hook.current.show(calendar));
    });

    expect(setCalendarHidden.mock.calls).toEqual([
      [calendar.url, true],
      [calendar.url, false],
    ]);
    expect(results).toEqual([true, true]);
    expect(onError).not.toHaveBeenCalled();
  });

  it("reports a failure with the asked value, and resolves to false", async () => {
    const setCalendarHidden = vi.fn().mockResolvedValue({ success: false, error: "403" });
    const onError = vi.fn();
    const hook = render({ setCalendarHidden, onError });

    let result = true;
    await act(async () => {
      result = await hook.current.setHidden(calendar, false);
    });

    expect(result).toBe(false);
    expect(onError).toHaveBeenCalledWith(false);
  });
});
