import { setCalendarHiddenAndRefresh } from "../set-calendar-hidden";

const URL = "http://localhost/caldav/calendars/users/u@example.com/team/";

describe("setCalendarHiddenAndRefresh", () => {
  beforeEach(() => {
    vi.spyOn(console, "error").mockImplementation(() => {});
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("writes the value, then refreshes the calendars", async () => {
    const setCalendarHidden = vi.fn().mockResolvedValue({ success: true });
    const refresh = vi.fn().mockResolvedValue(undefined);

    const result = await setCalendarHiddenAndRefresh({ setCalendarHidden }, refresh, URL, true);

    expect(setCalendarHidden).toHaveBeenCalledWith(URL, true);
    expect(refresh).toHaveBeenCalledOnce();
    expect(result).toEqual({ success: true });
  });

  it("does not refresh when the write fails", async () => {
    const setCalendarHidden = vi.fn().mockResolvedValue({ success: false, error: "403" });
    const refresh = vi.fn();

    const result = await setCalendarHiddenAndRefresh({ setCalendarHidden }, refresh, URL, true);

    expect(refresh).not.toHaveBeenCalled();
    expect(result).toEqual({ success: false, error: "403" });
  });

  it("reports success when the write succeeds and the refresh fails", async () => {
    const setCalendarHidden = vi.fn().mockResolvedValue({ success: true });
    // Like refreshCalendars: it reports a failed fetch itself and resolves.
    const refresh = vi.fn(async () => {
      console.error("Error fetching calendars");
    });

    const result = await setCalendarHiddenAndRefresh({ setCalendarHidden }, refresh, URL, false);

    expect(refresh).toHaveBeenCalledOnce();
    expect(result).toEqual({ success: true });
  });

  it("reports a failure when the write throws", async () => {
    const setCalendarHidden = vi.fn().mockRejectedValue(new Error("network"));
    const refresh = vi.fn();

    const result = await setCalendarHiddenAndRefresh({ setCalendarHidden }, refresh, URL, true);

    expect(refresh).not.toHaveBeenCalled();
    expect(result).toEqual({ success: false, error: "network" });
  });
});
