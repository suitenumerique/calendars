import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { CunninghamProvider } from "@gouvfr-lasuite/ui-components";
import { createInstance } from "i18next";
import { I18nextProvider } from "react-i18next";

import type { CalDavCalendar } from "@/features/calendar/services/dav/types/caldav-service";
import type { EventModalProps } from "../../scheduler/types";
import { LeftPanel } from "../LeftPanel";

const readOnly = {
  url: "http://localhost/caldav/calendars/users/me/shared/",
  displayName: "Shared",
  readOnly: true,
} as CalDavCalendar;
const own = {
  url: "http://localhost/caldav/calendars/users/me/own/",
  displayName: "Own",
} as CalDavCalendar;

let modalProps: EventModalProps | null = null;

vi.mock("../../scheduler/EventModal", () => ({
  EventModal: (props: EventModalProps) => {
    modalProps = props;
    return null;
  },
}));
vi.mock("../../calendar-list", () => ({ CalendarList: () => null }));
vi.mock("../MiniCalendar", () => ({ MiniCalendar: () => null }));
vi.mock("../../../contexts", () => ({
  useCalendarContext: () => ({
    selectedDate: new Date(),
    setSelectedDate: vi.fn(),
    orderedCalendars: [readOnly, own],
    caldavService: {},
    adapter: { getTimezoneOffset: () => 0 },
    calendarRef: { current: null },
  }),
}));
vi.mock("@/features/auth/Auth", () => ({ useAuth: () => ({ user: null }) }));
vi.mock("@/hooks/useFeatureFlag", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/hooks/useFeatureFlag")>()),
  useFeatureFlag: () => false,
}));
vi.mock("@/features/layouts/contexts/LeftPanelContext", () => ({
  useLeftPanel: () => ({ setIsLeftPanelOpen: vi.fn() }),
}));
vi.mock("@tanstack/react-router", () => ({ useNavigate: () => vi.fn() }));

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

let root: Root;
let container: HTMLElement;

beforeEach(() => {
  modalProps = null;
  container = document.createElement("div");
  document.body.append(container);
  root = createRoot(container);
});

afterEach(() => {
  act(() => root.unmount());
  container.remove();
});

describe("LeftPanel", () => {
  it("opens a new event in the first calendar that the user can write to", async () => {
    const i18n = createInstance();
    await i18n.init({ lng: "en", resources: {} });
    await act(async () =>
      root.render(
        <I18nextProvider i18n={i18n}>
          <CunninghamProvider>
            <LeftPanel />
          </CunninghamProvider>
        </I18nextProvider>,
      ),
    );

    const button = container.querySelector<HTMLElement>(".calendar-left-panel__create button");
    await act(async () => button?.click());

    expect(modalProps?.isOpen).toBe(true);
    expect(modalProps?.calendarUrl).toBe(own.url);
  });
});
