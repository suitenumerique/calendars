/**
 * E2E test helpers for calendar recurrence tests.
 *
 * Provides utility functions for authentication, event creation,
 * event interaction, and common calendar operations.
 */

import { type Page, type Locator, expect } from "@playwright/test";

const API_BASE_URL = "http://localhost:8931";

/**
 * Login via the E2E backend endpoint, then navigate to the app.
 * Uses the E2E user-auth endpoint which creates a user and logs them in
 * via Django session (bypasses Keycloak).
 */
export async function login(page: Page, email = "user1@example.local") {
  // First set the session cookie by calling the E2E auth endpoint in the browser
  // This ensures the cookie is set on localhost domain
  await page.goto(
    `${API_BASE_URL}/api/v1.0/e2e/user-auth/`,
  );

  // Use evaluate to POST since goto is GET-only
  const response = await page.evaluate(
    async ({ url, email }) => {
      const res = await fetch(url, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email }),
        credentials: "include",
      });
      return { status: res.status, data: await res.json() };
    },
    { url: `${API_BASE_URL}/api/v1.0/e2e/user-auth/`, email },
  );

  if (response.status !== 200) {
    throw new Error(`E2E auth failed: ${JSON.stringify(response)}`);
  }

  // Navigate to the frontend
  await page.goto("/");
}

/**
 * Login via Keycloak form (fallback method).
 * Handles the OIDC redirect flow through Keycloak login page.
 */
export async function loginViaKeycloak(
  page: Page,
  username = "user1",
  password = "user1",
) {
  await page.goto("/");

  // Wait for either Keycloak login or the calendar to appear
  await Promise.race([
    page.waitForSelector("#username", { timeout: 15000 }),
    page.waitForSelector(".ec", { timeout: 15000 }),
  ]);

  // If redirected to Keycloak, fill in credentials
  if (page.url().includes("realms") || page.url().includes("keycloak")) {
    await page.fill("#username", username);
    await page.fill("#password", password);
    await page.click("#kc-login");
  }

  await waitForCalendarReady(page);
}

/**
 * Wait for the calendar to be fully loaded and interactive.
 */
export async function waitForCalendarReady(page: Page, timeout = 30000) {
  await page.waitForSelector(".ec", { timeout });
  // Wait for events to finish loading (network idle)
  await page.waitForLoadState("networkidle", { timeout });
  // Small wait for calendar rendering
  await page.waitForTimeout(500);
}

/**
 * Switch to week view.
 */
export async function switchToWeekView(page: Page) {
  const weekBtn = page.locator('button:has-text("Week")').first();
  if (await weekBtn.isVisible()) {
    await weekBtn.click();
    await page.waitForTimeout(500);
  }
}

/**
 * Switch to day view.
 */
export async function switchToDayView(page: Page) {
  const dayBtn = page.locator('button:has-text("Day")').first();
  if (await dayBtn.isVisible()) {
    await dayBtn.click();
    await page.waitForTimeout(500);
  }
}

/**
 * Switch to month view.
 */
export async function switchToMonthView(page: Page) {
  const monthBtn = page.locator('button:has-text("Month")').first();
  if (await monthBtn.isVisible()) {
    await monthBtn.click();
    await page.waitForTimeout(500);
  }
}

/**
 * Navigate to the next period in the calendar.
 */
export async function navigateNext(page: Page, times = 1) {
  for (let i = 0; i < times; i++) {
    await page.locator(".ec-next").first().click();
    await page.waitForTimeout(300);
  }
}

/**
 * Navigate to the previous period in the calendar.
 */
export async function navigatePrev(page: Page, times = 1) {
  for (let i = 0; i < times; i++) {
    await page.locator(".ec-prev").first().click();
    await page.waitForTimeout(300);
  }
}

/**
 * Navigate to today.
 */
export async function navigateToday(page: Page) {
  await page.locator(".ec-today").first().click();
  await page.waitForTimeout(300);
}

/**
 * Click on a time slot in the calendar to open the create event modal.
 * Clicks at a specific time (hour) on a given day column.
 */
export async function clickTimeSlot(
  page: Page,
  hour: number,
  dayOffset = 0,
) {
  const timeGrid = page.locator(".ec-time-grid .ec-body");
  await expect(timeGrid).toBeVisible();

  const box = await timeGrid.boundingBox();
  if (!box) throw new Error("Time grid not visible");

  // Each hour is roughly box.height / 24
  const hourHeight = box.height / 24;
  const y = box.y + hour * hourHeight + hourHeight / 2;

  // Day columns: calculate x based on dayOffset
  const days = page.locator(".ec-time-grid .ec-body .ec-day");
  const dayCount = await days.count();
  if (dayOffset >= dayCount)
    throw new Error(`Day offset ${dayOffset} >= ${dayCount}`);

  const dayBox = await days.nth(dayOffset).boundingBox();
  if (!dayBox) throw new Error("Day column not visible");
  const x = dayBox.x + dayBox.width / 2;

  await page.mouse.click(x, y);
  await page.waitForTimeout(500);
}

/**
 * Create an event by selecting a time range in the time grid.
 * This triggers the select handler which opens the modal with the time range.
 */
export async function selectTimeRange(
  page: Page,
  startHour: number,
  endHour: number,
  dayOffset = 0,
) {
  const days = page.locator(".ec-time-grid .ec-body .ec-day");
  const dayBox = await days.nth(dayOffset).boundingBox();
  if (!dayBox) throw new Error("Day column not visible");

  const timeGrid = page.locator(".ec-time-grid .ec-body");
  const box = await timeGrid.boundingBox();
  if (!box) throw new Error("Time grid not visible");

  const hourHeight = box.height / 24;
  const x = dayBox.x + dayBox.width / 2;
  const startY = box.y + startHour * hourHeight;
  const endY = box.y + endHour * hourHeight;

  await page.mouse.move(x, startY);
  await page.mouse.down();
  await page.mouse.move(x, endY, { steps: 5 });
  await page.mouse.up();
  await page.waitForTimeout(500);
}

/**
 * Wait for and interact with the event creation/edit modal.
 */
export async function waitForEventModal(page: Page) {
  const modal = page.locator(".c__modal");
  await expect(modal).toBeVisible({ timeout: 5000 });
  return modal;
}

/**
 * Fill in the event title in the modal.
 */
export async function fillEventTitle(page: Page, title: string) {
  const titleInput = page.locator(
    '.event-modal__content input[type="text"]',
  ).first();
  await titleInput.clear();
  await titleInput.fill(title);
}

/**
 * Set event start date/time in the modal.
 */
export async function setEventStart(page: Page, datetime: string) {
  const startInput = page.locator(
    '.datetime-section__inputs input[type="datetime-local"]',
  ).first();
  await startInput.fill(datetime);
}

/**
 * Set event end date/time in the modal.
 */
export async function setEventEnd(page: Page, datetime: string) {
  const endInput = page.locator(
    '.datetime-section__inputs input[type="datetime-local"]',
  ).last();
  await endInput.fill(datetime);
}

/**
 * Toggle the all-day checkbox.
 */
export async function toggleAllDay(page: Page) {
  const checkbox = page.locator('.datetime-section__allday input[type="checkbox"]');
  await checkbox.click();
}

/**
 * Open the recurrence section in the event modal by clicking the pill.
 */
export async function openRecurrenceSection(page: Page) {
  // Click the "Repeat" pill button
  const pill = page.locator('button:has-text("Repeat")');
  if (await pill.isVisible()) {
    await pill.click();
    await page.waitForTimeout(300);
  }
}

/**
 * Set recurrence frequency (simple mode).
 * @param frequency - One of: "Does not repeat", "Daily", "Weekly", "Monthly", "Yearly", "Custom..."
 */
export async function setRecurrenceFrequency(
  page: Page,
  frequency: string,
) {
  const recurrenceSelect = page.locator(".recurrence-editor .c__select");
  await recurrenceSelect.click();

  const option = page.locator(`.c__select__menu .c__select__menu__item:has-text("${frequency}")`);
  await option.click();
  await page.waitForTimeout(300);
}

/**
 * Set the end condition for recurrence to "After N occurrences".
 */
export async function setRecurrenceCount(page: Page, count: number) {
  // Click "After..." button
  const afterBtn = page.locator(
    '.recurrence-editor__end-btn:has-text("After")',
  );
  await afterBtn.click();
  await page.waitForTimeout(200);

  // Fill in count
  const countInput = page.locator(
    '.recurrence-editor__end-input input[type="number"]',
  );
  await countInput.clear();
  await countInput.fill(String(count));
}

/**
 * Set the end condition for recurrence to "On date".
 */
export async function setRecurrenceUntil(page: Page, date: string) {
  // Click "On..." button
  const onBtn = page.locator('.recurrence-editor__end-btn:has-text("On")');
  await onBtn.click();
  await page.waitForTimeout(200);

  // Fill in date
  const dateInput = page.locator(
    '.recurrence-editor__end-input input[type="date"]',
  );
  await dateInput.fill(date);
}

/**
 * Toggle a weekday in custom recurrence.
 */
export async function toggleRecurrenceWeekday(page: Page, day: string) {
  const dayBtn = page.locator(
    `.recurrence-editor__weekday-button:has-text("${day}")`,
  );
  await dayBtn.click();
}

/**
 * Set custom recurrence interval.
 */
export async function setRecurrenceInterval(page: Page, interval: number) {
  const intervalInput = page.locator(
    '.recurrence-editor__interval input[type="number"]',
  );
  await intervalInput.clear();
  await intervalInput.fill(String(interval));
}

/**
 * Set custom recurrence frequency type (in custom mode).
 */
export async function setRecurrenceCustomFrequency(
  page: Page,
  frequency: string,
) {
  const freqSelect = page.locator(
    ".recurrence-editor__interval .c__select",
  );
  await freqSelect.click();

  const option = page.locator(`.c__select__menu .c__select__menu__item:has-text("${frequency}")`);
  await option.click();
}

/**
 * Click the Save button in the event modal.
 */
export async function saveEvent(page: Page) {
  const saveBtn = page
    .locator('.c__modal button:has-text("Save")')
    .first();
  await saveBtn.click();
  await page.waitForTimeout(1000);
}

/**
 * Click the Delete button in the event modal.
 */
export async function clickDeleteButton(page: Page) {
  const deleteBtn = page
    .locator('.c__modal button:has-text("Delete")')
    .first();
  await deleteBtn.click();
  await page.waitForTimeout(500);
}

/**
 * Select a recurring edit/delete option in the modal.
 * @param option - "this" | "future" | "all"
 * @param action - "edit" or "delete" (determines which radio group to use)
 */
export async function selectRecurringOption(
  page: Page,
  option: "this" | "future" | "all",
  action: "edit" | "delete" = "edit",
) {
  const radioName = action === "edit" ? "edit-option" : "delete-option";
  const radio = page.locator(`input[name="${radioName}"][value="${option}"]`);
  await radio.click();
  await page.waitForTimeout(200);
}

/**
 * Confirm the recurring edit/delete modal.
 */
export async function confirmRecurringAction(
  page: Page,
  action: "edit" | "delete" = "edit",
) {
  // The confirm button is Save for edit, Delete for delete
  const btnText = action === "edit" ? "Save" : "Delete";
  // Get the last visible modal (the recurring options modal is on top)
  const modals = page.locator(".c__modal");
  const lastModal = modals.last();
  const confirmBtn = lastModal.locator(`button:has-text("${btnText}")`);
  await confirmBtn.click();
  await page.waitForTimeout(1000);
}

/**
 * Cancel the recurring edit/delete modal.
 */
export async function cancelRecurringAction(page: Page) {
  const modals = page.locator(".c__modal");
  const lastModal = modals.last();
  const cancelBtn = lastModal.locator('button:has-text("Cancel")');
  await cancelBtn.click();
  await page.waitForTimeout(500);
}

/**
 * Click on an event in the calendar by its title.
 */
export async function clickEvent(page: Page, title: string) {
  const event = page.locator(`.ec-event:has-text("${title}")`).first();
  await expect(event).toBeVisible({ timeout: 5000 });
  await event.click();
  await page.waitForTimeout(500);
}

/**
 * Click on a specific occurrence (nth) of an event.
 */
export async function clickEventOccurrence(
  page: Page,
  title: string,
  index: number,
) {
  const events = page.locator(`.ec-event:has-text("${title}")`);
  await expect(events.nth(index)).toBeVisible({ timeout: 5000 });
  await events.nth(index).click();
  await page.waitForTimeout(500);
}

/**
 * Count visible events matching a title.
 */
export async function countEvents(page: Page, title: string): Promise<number> {
  await page.waitForTimeout(500);
  return page.locator(`.ec-event:has-text("${title}")`).count();
}

/**
 * Count all visible events.
 */
export async function countAllEvents(page: Page): Promise<number> {
  return page.locator(".ec-event").count();
}

/**
 * Drag an event to a new position.
 */
export async function dragEvent(
  page: Page,
  title: string,
  deltaX: number,
  deltaY: number,
  occurrenceIndex = 0,
) {
  const event = page.locator(`.ec-event:has-text("${title}")`).nth(occurrenceIndex);
  await expect(event).toBeVisible();

  const box = await event.boundingBox();
  if (!box) throw new Error(`Event "${title}" not visible`);

  const startX = box.x + box.width / 2;
  const startY = box.y + 5; // Near the top to avoid resize handle

  await page.mouse.move(startX, startY);
  await page.mouse.down();
  // Move in steps for smooth drag
  await page.mouse.move(startX + deltaX, startY + deltaY, { steps: 10 });
  await page.mouse.up();
  await page.waitForTimeout(500);
}

/**
 * Resize an event by dragging its bottom edge.
 */
export async function resizeEvent(
  page: Page,
  title: string,
  deltaY: number,
  occurrenceIndex = 0,
) {
  const event = page.locator(`.ec-event:has-text("${title}")`).nth(occurrenceIndex);
  await expect(event).toBeVisible();

  const box = await event.boundingBox();
  if (!box) throw new Error(`Event "${title}" not visible`);

  // Click near the bottom edge (resize handle)
  const startX = box.x + box.width / 2;
  const startY = box.y + box.height - 3;

  await page.mouse.move(startX, startY);
  await page.mouse.down();
  await page.mouse.move(startX, startY + deltaY, { steps: 10 });
  await page.mouse.up();
  await page.waitForTimeout(500);
}

/**
 * Wait for events to be refreshed after an action.
 */
export async function waitForEventsRefresh(page: Page) {
  await page.waitForLoadState("networkidle", { timeout: 10000 });
  await page.waitForTimeout(1000);
}

/**
 * Create a simple recurring event via the UI.
 * Opens modal by clicking a time slot, fills title, sets recurrence, saves.
 */
export async function createRecurringEvent(
  page: Page,
  options: {
    title: string;
    frequency: string;
    hour?: number;
    dayOffset?: number;
    count?: number;
    untilDate?: string;
    allDay?: boolean;
  },
) {
  const { title, frequency, hour = 10, dayOffset = 0, count, untilDate, allDay } = options;

  // Click on a time slot to open create modal
  await selectTimeRange(page, hour, hour + 1, dayOffset);

  // Wait for modal
  await waitForEventModal(page);

  // Fill title
  await fillEventTitle(page, title);

  // Toggle all-day if needed
  if (allDay) {
    await toggleAllDay(page);
  }

  // Open recurrence section
  await openRecurrenceSection(page);
  await page.waitForTimeout(300);

  // Set frequency
  await setRecurrenceFrequency(page, frequency);

  // Set count or until if specified
  if (count) {
    await setRecurrenceCount(page, count);
  }
  if (untilDate) {
    await setRecurrenceUntil(page, untilDate);
  }

  // Save
  await saveEvent(page);
  await waitForEventsRefresh(page);
}

/**
 * Edit an existing event occurrence.
 * Clicks on the event, modifies it, and handles the recurring modal.
 */
export async function editEventOccurrence(
  page: Page,
  options: {
    title: string;
    occurrenceIndex?: number;
    newTitle?: string;
    newStart?: string;
    newEnd?: string;
    recurringOption: "this" | "future" | "all";
  },
) {
  const { title, occurrenceIndex = 0, newTitle, newStart, newEnd, recurringOption } = options;

  // Click event
  await clickEventOccurrence(page, title, occurrenceIndex);
  await waitForEventModal(page);

  // Make changes
  if (newTitle) await fillEventTitle(page, newTitle);
  if (newStart) await setEventStart(page, newStart);
  if (newEnd) await setEventEnd(page, newEnd);

  // Save
  await saveEvent(page);

  // Handle recurring modal
  await selectRecurringOption(page, recurringOption, "edit");
  await confirmRecurringAction(page, "edit");
  await waitForEventsRefresh(page);
}

/**
 * Delete an event occurrence with recurring options.
 */
export async function deleteEventOccurrence(
  page: Page,
  options: {
    title: string;
    occurrenceIndex?: number;
    recurringOption?: "this" | "future" | "all";
  },
) {
  const { title, occurrenceIndex = 0, recurringOption } = options;

  // Click event
  await clickEventOccurrence(page, title, occurrenceIndex);
  await waitForEventModal(page);

  // Click delete
  await clickDeleteButton(page);

  // Handle recurring delete modal
  if (recurringOption) {
    await selectRecurringOption(page, recurringOption, "delete");
  }
  await confirmRecurringAction(page, "delete");
  await waitForEventsRefresh(page);
}

/**
 * Generate a unique event title to avoid test collisions.
 */
export function uniqueTitle(prefix: string): string {
  const suffix = Date.now().toString(36).slice(-4);
  return `${prefix}-${suffix}`;
}
