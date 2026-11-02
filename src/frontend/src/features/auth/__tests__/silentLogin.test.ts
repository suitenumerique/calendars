import { attemptSilentLogin, clearPendingSilentLogin } from "../silentLogin";

vi.mock("@/features/api/utils", () => ({
  baseApiUrl: () => "http://api.test/api/v1.0/",
}));

describe("attemptSilentLogin", () => {
  const replace = vi.fn();

  beforeEach(() => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-01-01T00:00:00Z"));
    localStorage.clear();
    sessionStorage.clear();
    replace.mockReset();
    vi.stubGlobal("location", { href: "http://app.test/", search: "", replace });
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.unstubAllGlobals();
  });

  it("redirects to the silent authenticate endpoint", () => {
    expect(attemptSilentLogin()).toBe(true);

    const url = new URL(replace.mock.calls[0][0] as string);
    expect(url.pathname).toBe("/api/v1.0/authenticate/");
    expect(url.searchParams.get("silent")).toBe("true");
    expect(url.searchParams.get("returnTo")).toBe("http://app.test/");
  });

  it("does not retry during the cooldown", () => {
    attemptSilentLogin();
    clearPendingSilentLogin();
    vi.advanceTimersByTime(29 * 1000);

    expect(attemptSilentLogin()).toBe(false);
    expect(replace).toHaveBeenCalledTimes(1);
  });

  it("does not retry after a round trip slower than the cooldown", () => {
    attemptSilentLogin();
    vi.advanceTimersByTime(31 * 1000);

    expect(attemptSilentLogin()).toBe(false);
    expect(replace).toHaveBeenCalledTimes(1);

    vi.advanceTimersByTime(29 * 1000);
    expect(attemptSilentLogin()).toBe(false);

    vi.advanceTimersByTime(2 * 1000);
    expect(attemptSilentLogin()).toBe(true);
  });

  it("retries after the cooldown once the attempt is cleared", () => {
    attemptSilentLogin();
    clearPendingSilentLogin();
    vi.advanceTimersByTime(31 * 1000);

    expect(attemptSilentLogin()).toBe(true);
  });

  it("does not redirect when the app refused the user", () => {
    vi.stubGlobal("location", {
      href: "http://app.test/?auth_error=x",
      search: "?auth_error=x",
      replace,
    });

    expect(attemptSilentLogin()).toBe(false);
    expect(replace).not.toHaveBeenCalled();
  });
});
