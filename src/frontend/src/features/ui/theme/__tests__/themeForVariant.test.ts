import { describe, expect, it } from "vitest";

import { themeForVariant } from "../themeForVariant";

describe("themeForVariant", () => {
  it("keeps the base theme in the light variant", () => {
    expect(themeForVariant("default", "light")).toBe("default");
    expect(themeForVariant("anct", "light")).toBe("anct");
  });

  it("returns the light counterpart of a dark base theme", () => {
    expect(themeForVariant("dark", "light")).toBe("default");
    expect(themeForVariant("anct-dark", "light")).toBe("anct");
    expect(themeForVariant("dsfr-dark", "light")).toBe("dsfr-light");
  });

  it("keeps a dark base theme in the dark variant", () => {
    expect(themeForVariant("dark", "dark")).toBe("dark");
    expect(themeForVariant("anct-dark", "dark")).toBe("anct-dark");
  });

  it("returns the dark theme for the default theme", () => {
    expect(themeForVariant("default", "dark")).toBe("dark");
  });

  it("returns the dark counterpart of a named theme", () => {
    expect(themeForVariant("anct", "dark")).toBe("anct-dark");
    expect(themeForVariant("dsfr-light", "dark")).toBe("dsfr-dark");
  });

  it("keeps a theme that has no dark counterpart", () => {
    expect(themeForVariant("custom", "dark")).toBe("custom");
  });
});
