import { act, createElement } from "react";
import { createRoot } from "react-dom/client";

import type { CalDavCalendar } from "../../../../services/dav/types/caldav-service";
import { useMailboxCalendarDelete } from "../useMailboxCalendarDelete";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

type Hook = ReturnType<typeof useMailboxCalendarDelete>;
type Props = Parameters<typeof useMailboxCalendarDelete>[0];

const calendar = {
  url: "http://localhost/caldav/calendars/users/u@example.com/team/",
  mailboxEmail: "contact@example.com",
} as CalDavCalendar;

const render = (props: Props) => {
  const result = { current: null as unknown as Hook };
  const Probe = () => {
    result.current = useMailboxCalendarDelete(props);
    return null;
  };
  act(() => createRoot(document.createElement("div")).render(createElement(Probe)));
  return result;
};

const deferred = <T>() => {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((r) => {
    resolve = r;
  });
  return { promise, resolve };
};

describe("useMailboxCalendarDelete", () => {
  beforeEach(() => {
    vi.spyOn(console, "error").mockImplementation(() => {});
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("deletes the selected calendar of the mailbox", async () => {
    const deleteMailboxCalendar = vi.fn().mockResolvedValue({ success: true });
    const onError = vi.fn();
    const hook = render({ deleteMailboxCalendar, onError });

    act(() => hook.current.open(calendar));
    await act(() => hook.current.confirm());

    expect(deleteMailboxCalendar).toHaveBeenCalledWith(calendar.url, "contact@example.com");
    expect(hook.current.calendar).toBeNull();
    expect(hook.current.isLoading).toBe(false);
    expect(onError).not.toHaveBeenCalled();
  });

  it("stops loading and reports a failed delete", async () => {
    const deleteMailboxCalendar = vi.fn().mockResolvedValue({ success: false, error: "boom" });
    const onError = vi.fn();
    const hook = render({ deleteMailboxCalendar, onError });

    act(() => hook.current.open(calendar));
    await act(() => hook.current.confirm());

    expect(hook.current.isLoading).toBe(false);
    expect(hook.current.calendar).toBeNull();
    expect(onError).toHaveBeenCalledOnce();
  });

  it("stops loading and reports a rejected delete", async () => {
    const deleteMailboxCalendar = vi.fn().mockRejectedValue(new Error("network"));
    const onError = vi.fn();
    const hook = render({ deleteMailboxCalendar, onError });

    act(() => hook.current.open(calendar));
    await act(() => hook.current.confirm());

    expect(hook.current.isLoading).toBe(false);
    expect(onError).toHaveBeenCalledOnce();
  });

  it("ignores a close while the delete is pending", async () => {
    const pending = deferred<{ success: boolean }>();
    const deleteMailboxCalendar = vi.fn().mockReturnValue(pending.promise);
    const hook = render({ deleteMailboxCalendar, onError: vi.fn() });

    act(() => hook.current.open(calendar));
    let confirmed!: Promise<void>;
    act(() => {
      confirmed = hook.current.confirm();
    });
    act(() => hook.current.close());

    expect(hook.current.isLoading).toBe(true);
    expect(hook.current.calendar).toBe(calendar);

    await act(async () => {
      pending.resolve({ success: true });
      await confirmed;
    });
    expect(hook.current.isLoading).toBe(false);
    expect(hook.current.calendar).toBeNull();
  });
});
