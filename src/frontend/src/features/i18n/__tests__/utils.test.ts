import {
  getPickerLanguage,
  getPickerLanguages,
  getPickerOptions,
  toCunninghamLocale,
} from "../utils";

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

  it("matches a value with an uppercase language subtag", () => {
    expect(getPickerLanguage(null, "fr", ["EN-us", "FR-fr"])).toBe("FR-fr");
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

  it("keeps a configured language with an uppercase language subtag", () => {
    expect(getPickerLanguages([["FR-fr", "French"]], ["en", "fr", "nl"])).toEqual([
      { value: "FR-fr", label: "Français", shortLabel: "FR" },
    ]);
  });

  it("uses the configured name when Intl has no native name", () => {
    expect(getPickerLanguages([["xx-xx", "Test language"]], ["xx"])).toEqual([
      { value: "xx-xx", label: "Test language", shortLabel: "XX" },
    ]);
  });

  it("returns no entry when no language has translations", () => {
    expect(getPickerLanguages(CONFIGURED, [])).toEqual([]);
  });
});

describe("getPickerOptions", () => {
  const FRENCH = { value: "fr-fr", label: "Français", shortLabel: "FR" };
  const DUTCH = { value: "nl-nl", label: "Nederlands", shortLabel: "NL" };

  it("checks the offered language of the UI", () => {
    expect(getPickerOptions([FRENCH, DUTCH], null, "nl")).toEqual([
      { ...FRENCH, isChecked: false },
      { ...DUTCH, isChecked: true },
    ]);
  });

  it.each([
    ["the user has no language", null],
    ["the user language is not offered", "en-us"],
  ])("adds a checked option for a UI language that is not offered, when %s", (_, userLanguage) => {
    expect(getPickerOptions([FRENCH, DUTCH], userLanguage, "en")).toEqual([
      { value: "en", label: "English", shortLabel: "EN", isChecked: true },
      { ...FRENCH, isChecked: false },
      { ...DUTCH, isChecked: false },
    ]);
  });
});
