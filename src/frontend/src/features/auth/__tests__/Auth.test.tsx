import { act } from "react";
import { createRoot, type Root } from "react-dom/client";

import type { ApiConfig } from "@/features/api/types";
import { fetchAPI } from "@/features/api/fetchApi";
import { ConfigContext } from "@/features/config/ConfigProvider";
import i18n from "@/features/i18n/initI18n";
import { Auth, useAuth } from "../Auth";

vi.mock("@/features/api/fetchApi", () => ({ fetchAPI: vi.fn() }));

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

let root: Root;
let refreshUser: (() => Promise<void>) | undefined;

const RefreshHandle = () => {
  refreshUser = useAuth().refreshUser;
  return null;
};

const respondWithLanguage = (language: string) => {
  vi.mocked(fetchAPI).mockResolvedValue({
    json: () => Promise.resolve({ id: "user-id", language }),
  } as Response);
};

const renderAuth = async () => {
  await act(async () =>
    root.render(
      <ConfigContext.Provider value={{ config: {} as ApiConfig }}>
        <Auth>
          <RefreshHandle />
        </Auth>
      </ConfigContext.Provider>,
    ),
  );
};

describe("Auth", () => {
  beforeEach(() => {
    root = createRoot(document.createElement("div"));
  });

  afterEach(() => {
    act(() => root.unmount());
    vi.restoreAllMocks();
  });

  it("sets the saved language when the user loads", async () => {
    await i18n.changeLanguage("en-us");
    respondWithLanguage("fr-fr");

    await renderAuth();

    expect(i18n.language.toLowerCase()).toBe("fr-fr");
  });

  // A language change makes the calendar reload all its events.
  it("does not change the language when the UI already uses the saved one", async () => {
    await i18n.changeLanguage("nl-nl");
    respondWithLanguage("nl-nl");
    const changeLanguage = vi.spyOn(i18n, "changeLanguage");

    await renderAuth();

    expect(changeLanguage).not.toHaveBeenCalled();
  });

  it("sets the new saved language when the user refreshes", async () => {
    await i18n.changeLanguage("en-us");
    respondWithLanguage("en-us");
    await renderAuth();

    respondWithLanguage("fr-fr");
    await act(async () => refreshUser?.());

    expect(i18n.language.toLowerCase()).toBe("fr-fr");
  });
});
