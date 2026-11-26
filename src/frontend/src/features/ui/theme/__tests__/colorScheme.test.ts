import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { COLOR_SCHEME_KEY, loadColorScheme, resolveVariant, saveColorScheme } from "../colorScheme";

describe("loadColorScheme", () => {
  beforeEach(() => {
    localStorage.clear();
  });

  it("returns system when nothing is stored", () => {
    expect(loadColorScheme()).toBe("system");
  });

  it("returns system when the stored value is unknown", () => {
    localStorage.setItem(COLOR_SCHEME_KEY, "sepia");
    expect(loadColorScheme()).toBe("system");
  });

  it("returns the scheme saved with saveColorScheme", () => {
    for (const scheme of ["light", "dark", "system"] as const) {
      saveColorScheme(scheme);
      expect(loadColorScheme()).toBe(scheme);
    }
  });
});

describe("storage errors", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("returns system when storage is not available", () => {
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
      throw new Error("blocked");
    });
    expect(loadColorScheme()).toBe("system");
  });

  it("does not throw when the save fails", () => {
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new Error("quota");
    });
    expect(() => saveColorScheme("dark")).not.toThrow();
  });
});

describe("resolveVariant", () => {
  it("follows the system setting for the system scheme", () => {
    expect(resolveVariant("system", true)).toBe("dark");
    expect(resolveVariant("system", false)).toBe("light");
  });

  it("ignores the system setting for an explicit scheme", () => {
    expect(resolveVariant("light", true)).toBe("light");
    expect(resolveVariant("dark", false)).toBe("dark");
  });
});
