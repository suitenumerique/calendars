import { getPickerLanguage, getPickerLanguages, toCunninghamLocale } from "../utils";

describe("toCunninghamLocale", () => {
  it.each([
    ["fr", "fr-FR"],
    ["fr-fr", "fr-FR"],
    ["fr-BE", "fr-FR"],
    ["FR-ca", "fr-FR"],
    ["en", "en-US"],
    ["en-GB", "en-US"],
    ["nl", "nl-NL"],
    ["nl-be", "nl-NL"],
    ["de-de", "de-DE"],
  ])("maps %s to %s", (language, expected) => {
    expect(toCunninghamLocale(language)).toBe(expected);
  });
});

const VALUES = ["fr-fr", "en-us", "nl-nl", "de-de"];

describe("getPickerLanguage", () => {
  it("returns the user language when it is set", () => {
    expect(getPickerLanguage("nl-nl", "en", VALUES)).toBe("nl-nl");
  });

  it.each([
    ["en", "en-us"],
    ["en-GB", "en-us"],
    ["EN-us", "en-us"],
    ["fr", "fr-fr"],
    ["fr-BE", "fr-fr"],
    ["nl", "nl-nl"],
    ["de-DE", "de-de"],
  ])("maps the UI language %s to %s when the user has no language", (ui, expected) => {
    expect(getPickerLanguage(null, ui, VALUES)).toBe(expected);
  });

  it("ignores a user language that the picker does not offer", () => {
    expect(getPickerLanguage("es-es", "fr", VALUES)).toBe("fr-fr");
  });

  it("returns undefined when no value matches the UI language", () => {
    expect(getPickerLanguage(undefined, "es", VALUES)).toBeUndefined();
  });
});

describe("getPickerLanguages", () => {
  const CONFIGURED: [string, string][] = [
    ["en-us", "English"],
    ["fr-fr", "French"],
    ["de-de", "German"],
    ["nl-nl", "Dutch"],
  ];

  it("keeps the configured languages that have translations, in order", () => {
    expect(getPickerLanguages(CONFIGURED, ["en", "fr", "nl"])).toEqual([
      { value: "en-us", label: "English", shortLabel: "EN" },
      { value: "fr-fr", label: "Français", shortLabel: "FR" },
      { value: "nl-nl", label: "Nederlands", shortLabel: "NL" },
    ]);
  });

  it("returns no entry when no language has translations", () => {
    expect(getPickerLanguages(CONFIGURED, [])).toEqual([]);
  });
});
