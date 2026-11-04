import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { loadLastView, saveLastView } from "../lastView";

const LAST_VIEW_KEY = "calendar-last-view";

describe("loadLastView", () => {
  beforeEach(() => {
    localStorage.clear();
  });

  it("returns the week view when nothing is stored", () => {
    expect(loadLastView()).toBe("timeGridWeek");
  });

  it("returns the week view when the stored value is not a toolbar view", () => {
    localStorage.setItem(LAST_VIEW_KEY, "resourceTimeline");
    expect(loadLastView()).toBe("timeGridWeek");
  });

  it("returns the view saved with saveLastView", () => {
    saveLastView("dayGridMonth");
    expect(loadLastView()).toBe("dayGridMonth");
  });

  it("round-trips every toolbar view", () => {
    for (const view of ["timeGridDay", "timeGridWorkWeek", "dayGridMonth", "listWeek"]) {
      saveLastView(view);
      expect(loadLastView()).toBe(view);
    }
  });
});

describe("storage errors", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("returns the week view when storage is not available", () => {
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
      throw new Error("blocked");
    });
    expect(loadLastView()).toBe("timeGridWeek");
  });

  it("does not throw when the save fails", () => {
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new Error("quota");
    });
    expect(() => saveLastView("dayGridMonth")).not.toThrow();
  });
});
