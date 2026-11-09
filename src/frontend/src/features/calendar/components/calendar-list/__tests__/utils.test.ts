import { APIError } from "@/features/api/APIError";

import { getCalendarSaveErrorKey, getShareErrorKey, getShareeEmails } from "../utils";

describe("getCalendarSaveErrorKey", () => {
  it("maps the mailbox role error code", () => {
    const error = new APIError(400, {
      error: "User needs 'sender' or 'admin' role to create a mailbox calendar",
      code: "mailbox_role_required",
    });
    expect(getCalendarSaveErrorKey(error, "create")).toBe(
      "calendar.createCalendar.errorMailboxRole",
    );
  });

  it("ignores the backend text of other API errors", () => {
    const error = new APIError(400, { error: "name is required" });
    expect(getCalendarSaveErrorKey(error, "create")).toBe("calendar.createCalendar.error");
  });

  it("uses the generic error when the creation fails", () => {
    expect(getCalendarSaveErrorKey(new Error("boom"), "create")).toBe(
      "calendar.createCalendar.error",
    );
  });

  it("uses the unexpected error when the edit fails", () => {
    expect(getCalendarSaveErrorKey(new Error("boom"), "edit")).toBe("api.error.unexpected");
  });
});

const FALLBACK = "calendar.shareCalendar.error";

describe("getShareErrorKey", () => {
  it("maps the sync-managed sharee error", () => {
    const error =
      "This sharee is managed by Messages and can only be changed there. " +
      "Update the mailbox permissions in Messages instead.";
    expect(getShareErrorKey({ error, status: 403 }, FALLBACK)).toBe(
      "calendar.shareCalendar.errorSyncManaged",
    );
  });

  it("maps the mailbox read-only error", () => {
    const error =
      "Mailbox calendars can only be shared with read-only access. " +
      "To grant write access, update the mailbox permissions in Messages.";
    expect(getShareErrorKey({ error, status: 403 }, FALLBACK)).toBe(
      "calendar.shareCalendar.errorMailboxReadOnly",
    );
  });

  it("maps other forbidden errors", () => {
    const error = "User did not have the required privileges ({DAV:}share) for path";
    expect(getShareErrorKey({ error, status: 403 }, FALLBACK)).toBe(
      "calendar.shareCalendar.errorForbidden",
    );
  });

  it("returns the fallback key for other errors", () => {
    expect(getShareErrorKey({ error: "Internal server error", status: 500 }, FALLBACK)).toBe(
      FALLBACK,
    );
    expect(getShareErrorKey({}, FALLBACK)).toBe(FALLBACK);
  });
});

describe("getShareeEmails", () => {
  const users = (...emails: string[]) => emails.map((email) => ({ email }));

  it("keeps every email in order", () => {
    expect(getShareeEmails(users("alice@x.org", "bob@x.org"), "owner@x.org")).toEqual([
      "alice@x.org",
      "bob@x.org",
    ]);
  });

  it("skips the owner, whatever the letter case", () => {
    expect(getShareeEmails(users("Owner@x.org", "bob@x.org"), "owner@x.org")).toEqual([
      "bob@x.org",
    ]);
  });

  it("keeps the first spelling of a duplicate email", () => {
    expect(
      getShareeEmails(users("alice@x.org", "Alice@x.org", "bob@x.org"), "owner@x.org"),
    ).toEqual(["alice@x.org", "bob@x.org"]);
  });

  it("keeps every email when the owner is unknown", () => {
    expect(getShareeEmails(users("alice@x.org"), undefined)).toEqual(["alice@x.org"]);
  });
});
