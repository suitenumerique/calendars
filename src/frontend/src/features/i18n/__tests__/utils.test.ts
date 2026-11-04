import { getPickerLanguage, toCunninghamLocale } from "../utils";

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

  it("returns undefined when no value matches the UI language", () => {
    expect(getPickerLanguage(undefined, "es", VALUES)).toBeUndefined();
  });
});
