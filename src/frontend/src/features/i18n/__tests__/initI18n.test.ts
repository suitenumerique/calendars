import i18n from "../initI18n";

describe("initI18n", () => {
  // The backend saves languages in lowercase, such as "nl-nl". When the UI
  // language is written another way, the app sets the language again.
  it("keeps a language code in lowercase", async () => {
    await i18n.changeLanguage("nl-nl");

    expect(i18n.language).toBe("nl-nl");
  });
});
