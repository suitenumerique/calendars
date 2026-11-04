import { act } from "react";

import type { CalDavCalendar } from "../../../../services/dav/types/caldav-service";
import { useCalendarModal } from "../useCalendarModal";
import { renderHook } from "./render-hook";

type Props = Parameters<typeof useCalendarModal>[0];

const calendar = {
  url: "http://localhost/caldav/calendars/users/u@example.com/work/",
  displayName: "Work",
  color: "#ff0000",
  includeInAvailability: true,
} as CalDavCalendar;

const render = (props: Props) => renderHook(() => useCalendarModal(props));

const setup = () => {
  const createCalendar = vi.fn().mockResolvedValue({ success: true });
  const updateCalendar = vi.fn().mockResolvedValue({ success: true });
  return { createCalendar, updateCalendar, hook: render({ createCalendar, updateCalendar }) };
};

describe("useCalendarModal", () => {
  it("sends only the changed properties on edit", async () => {
    const { hook, updateCalendar } = setup();

    act(() => hook.current.handleOpenEditModal(calendar));
    await act(() => hook.current.handleSaveCalendar("Work", "#00ff00", true));

    expect(updateCalendar).toHaveBeenCalledWith(calendar.url, { color: "#00ff00" });
  });

  it("sends nothing when nothing changes", async () => {
    const { hook, updateCalendar } = setup();

    act(() => hook.current.handleOpenEditModal(calendar));
    await act(() => hook.current.handleSaveCalendar("Work", "#ff0000", true));

    expect(updateCalendar).not.toHaveBeenCalled();
  });

  it("creates a calendar in create mode", async () => {
    const { hook, createCalendar } = setup();

    act(() => hook.current.handleOpenCreateModal());
    await act(() => hook.current.handleSaveCalendar("New", "#0000ff"));

    expect(createCalendar).toHaveBeenCalledWith({
      displayName: "New",
      color: "#0000ff",
      components: ["VEVENT"],
    });
  });

  it("throws when the update fails, so the dialog shows the error", async () => {
    const { hook, updateCalendar } = setup();
    updateCalendar.mockResolvedValue({ success: false, error: "forbidden" });

    act(() => hook.current.handleOpenEditModal(calendar));

    await expect(hook.current.handleSaveCalendar("Renamed", "#ff0000")).rejects.toThrow(
      "forbidden",
    );
  });
});
