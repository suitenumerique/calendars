import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { CunninghamProvider } from "@gouvfr-lasuite/ui-components";
import { createInstance } from "i18next";
import { I18nextProvider } from "react-i18next";

import type { ApiConfig } from "@/features/api/types";
import { fetchAPI } from "@/features/api/fetchApi";
import { AuthContext } from "@/features/auth/Auth";
import type { User } from "@/features/auth/types";
import { ConfigContext } from "@/features/config/ConfigProvider";
import { LanguagePickerUserMenu } from "../Header";

vi.mock("@/features/api/fetchApi", () => ({ fetchAPI: vi.fn().mockResolvedValue(undefined) }));

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

// jsdom does not have these APIs. The open menu of the UI kit needs them.
vi.stubGlobal(
  "ResizeObserver",
  class {
    observe() {}
    unobserve() {}
    disconnect() {}
  },
);
vi.stubGlobal("CSS", { escape: (value: string) => value });

const ENGLISH: [string, string] = ["en-us", "English"];
const FRENCH: [string, string] = ["fr-fr", "French"];
const GERMAN: [string, string] = ["de-de", "German"];

const translation = { key: "value" };
const resources = { en: { translation }, fr: { translation }, nl: { translation } };

type Setup = {
  configured?: [string, string][];
  uiLanguage: string;
  userLanguage: string | null;
};

let root: Root;
let container: HTMLElement;

/**
 * Renders the menu with the picker of the UI kit, not a mock.
 * The UI has translations for English, French and Dutch.
 */
const renderMenu = async ({ configured, uiLanguage, userLanguage }: Setup) => {
  const i18n = createInstance();
  await i18n.init({ lng: uiLanguage, fallbackLng: "en", resources });
  const user = { id: "user-id", language: userLanguage } as User;
  await act(async () =>
    root.render(
      <I18nextProvider i18n={i18n}>
        <CunninghamProvider>
          <ConfigContext.Provider value={{ config: { LANGUAGES: configured } as ApiConfig }}>
            <AuthContext.Provider value={{ user }}>
              <LanguagePickerUserMenu />
            </AuthContext.Provider>
          </ConfigContext.Provider>
        </CunninghamProvider>
      </I18nextProvider>,
    ),
  );
  return i18n;
};

const picker = () => container.querySelector<HTMLElement>(".c__language-picker");

const shownLanguage = () => picker()?.querySelector(".c__language-picker__label")?.textContent;

const selectOption = async (label: string) => {
  await act(async () => picker()?.click());
  const option = [...document.querySelectorAll<HTMLElement>('[role="menuitem"]')].find(
    (item) => item.getAttribute("aria-label") === label,
  );
  if (!option) throw new Error(`No "${label}" option in the picker`);
  await act(async () => option.click());
};

describe("LanguagePickerUserMenu", () => {
  beforeEach(() => {
    container = document.createElement("div");
    document.body.append(container);
    root = createRoot(container);
  });

  afterEach(() => {
    act(() => root.unmount());
    container.remove();
    vi.clearAllMocks();
  });

  it("shows the saved language of the user", async () => {
    await renderMenu({ configured: [ENGLISH, FRENCH], uiLanguage: "en", userLanguage: "fr-fr" });

    expect(shownLanguage()).toBe("FR");
  });

  it.each([
    ["the config has no language", undefined],
    ["no configured language has translations", [GERMAN]],
  ])("shows no picker when %s", async (_, configured) => {
    await renderMenu({ configured, uiLanguage: "en", userLanguage: null });

    expect(picker()).toBeNull();
  });

  it("shows the browser language when the config does not offer it", async () => {
    await renderMenu({ configured: [FRENCH], uiLanguage: "en", userLanguage: null });

    expect(shownLanguage()).toBe("EN");
  });

  it("shows the saved language when the config does not offer it", async () => {
    await renderMenu({ configured: [ENGLISH, FRENCH], uiLanguage: "en", userLanguage: "nl-nl" });

    expect(shownLanguage()).toBe("NL");
  });

  it("does not save a language that the config does not offer", async () => {
    const i18n = await renderMenu({ configured: [FRENCH], uiLanguage: "en", userLanguage: null });

    await selectOption("English");

    expect(fetchAPI).not.toHaveBeenCalled();
    expect(i18n.language).toBe("en");
  });

  it("saves an offered language and shows it", async () => {
    await renderMenu({ configured: [FRENCH], uiLanguage: "en", userLanguage: null });

    await selectOption("Français");

    expect(fetchAPI).toHaveBeenCalledWith("users/user-id/", {
      method: "PATCH",
      body: JSON.stringify({ language: "fr-fr" }),
    });
    expect(shownLanguage()).toBe("FR");
  });
});
