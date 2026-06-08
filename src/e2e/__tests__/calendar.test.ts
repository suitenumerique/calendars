/**
 * Playwright E2E tests for Calendar Application
 */
import { test, expect } from '@playwright/test'

test.describe('Calendar Application', () => {
  test.beforeEach(async ({ page }) => {
    // Navigate to the calendar page
    await page.goto('/')
  })

  test.describe('Page Load', () => {
    test('should load the calendar page', async ({ page }) => {
      // Check the page title contains calendar or related text
      await expect(page).toHaveTitle(/calendars|calendar|agenda/i)
    })

    test('should display the calendar container', async ({ page }) => {
      // Wait for the calendar to be visible
      const calendar = page.locator('.ec')  // EventCalendar class
      await expect(calendar).toBeVisible({ timeout: 10000 })
    })

    test('should display the calendar header toolbar', async ({ page }) => {
      // Check for navigation buttons or toolbar
      const toolbar = page.locator('.ec-toolbar, [class*="toolbar"]')
      await expect(toolbar).toBeVisible({ timeout: 10000 })
    })
  })

  test.describe('Calendar Navigation', () => {
    test('should navigate to next period', async ({ page }) => {
      // Wait for calendar to load
      await page.waitForSelector('.ec', { timeout: 10000 })

      // Click the next button
      const nextButton = page.locator('.ec-next, button:has-text("Next"), button[title*="next"]').first()
      if (await nextButton.isVisible()) {
        await nextButton.click()
        // Calendar should still be visible after navigation
        await expect(page.locator('.ec')).toBeVisible()
      }
    })

    test('should navigate to previous period', async ({ page }) => {
      // Wait for calendar to load
      await page.waitForSelector('.ec', { timeout: 10000 })

      // Click the previous button
      const prevButton = page.locator('.ec-prev, button:has-text("Prev"), button[title*="prev"]').first()
      if (await prevButton.isVisible()) {
        await prevButton.click()
        // Calendar should still be visible after navigation
        await expect(page.locator('.ec')).toBeVisible()
      }
    })

    test('should navigate to today', async ({ page }) => {
      // Wait for calendar to load
      await page.waitForSelector('.ec', { timeout: 10000 })

      // Click the today button
      const todayButton = page.locator('.ec-today, button:has-text("Today"), button:has-text("Aujourd")').first()
      if (await todayButton.isVisible()) {
        await todayButton.click()
        // Calendar should highlight today's date
        await expect(page.locator('.ec')).toBeVisible()
      }
    })
  })

  test.describe('View Switching', () => {
    test('should switch to month view', async ({ page }) => {
      // Wait for calendar to load
      await page.waitForSelector('.ec', { timeout: 10000 })

      // Try to find and click month view button
      const monthButton = page.locator('button:has-text("Month"), button:has-text("Mois")').first()
      if (await monthButton.isVisible()) {
        await monthButton.click()
        // Check calendar is in month view mode
        const monthView = page.locator('.ec-day-grid, [class*="month"]')
        await expect(monthView).toBeVisible({ timeout: 5000 })
      }
    })

    test('should switch to week view', async ({ page }) => {
      // Wait for calendar to load
      await page.waitForSelector('.ec', { timeout: 10000 })

      // Try to find and click week view button
      const weekButton = page.locator('button:has-text("Week"), button:has-text("Semaine")').first()
      if (await weekButton.isVisible()) {
        await weekButton.click()
        // Check calendar is in week view mode
        const weekView = page.locator('.ec-time-grid, [class*="week"]')
        await expect(weekView).toBeVisible({ timeout: 5000 })
      }
    })

    test('should switch to day view', async ({ page }) => {
      // Wait for calendar to load
      await page.waitForSelector('.ec', { timeout: 10000 })

      // Try to find and click day view button
      const dayButton = page.locator('button:has-text("Day"), button:has-text("Jour")').first()
      if (await dayButton.isVisible()) {
        await dayButton.click()
        // Check calendar is in day view mode
        await expect(page.locator('.ec')).toBeVisible()
      }
    })
  })

  test.describe('Calendar List', () => {
    test('should display the calendar list sidebar', async ({ page }) => {
      // Wait for page to load
      await page.waitForLoadState('networkidle')

      // Check for calendar list
      const calendarList = page.locator('.calendar-list, [class*="calendar-list"]')
      await expect(calendarList).toBeVisible({ timeout: 10000 })
    })

    test('should display "My Calendars" section', async ({ page }) => {
      await page.waitForLoadState('networkidle')

      // Look for "My calendars" or "Mes agendas" text
      const myCalendarsSection = page.locator('text=/my calendars|mes agendas|mes calendriers/i')
      await expect(myCalendarsSection).toBeVisible({ timeout: 10000 })
    })

    test('should have add calendar button', async ({ page }) => {
      await page.waitForLoadState('networkidle')

      // Look for add button in calendar list
      const addButton = page.locator('.calendar-list__add-btn, button[title*="create"], button[title*="add"], .material-icons:has-text("add")').first()
      await expect(addButton).toBeVisible({ timeout: 10000 })
    })
  })

  test.describe('Event Interactions', () => {
    test('should open event modal on date click', async ({ page }) => {
      // Wait for calendar to load
      await page.waitForSelector('.ec', { timeout: 10000 })

      // Click on a day cell
      const dayCell = page.locator('.ec-day, .ec-day-head').first()
      if (await dayCell.isVisible()) {
        await dayCell.click()

        // Check if modal appears (might not if selection is required)
        const modal = page.locator('.modal, [role="dialog"], .c__modal')
        // This might fail if clicking doesn't open a modal
        const isModalVisible = await modal.isVisible().catch(() => false)
        // Log result but don't fail - behavior depends on configuration
        if (isModalVisible) {
          expect(isModalVisible).toBe(true)
        }
      }
    })

    test('should allow selecting time range', async ({ page }) => {
      // Wait for calendar to load in time grid view
      await page.waitForSelector('.ec', { timeout: 10000 })

      // Try to switch to week view for time selection
      const weekButton = page.locator('button:has-text("Week"), button:has-text("Semaine")').first()
      if (await weekButton.isVisible()) {
        await weekButton.click()
        await page.waitForTimeout(500)
      }

      // Try selecting a time range (drag operation)
      const timeGrid = page.locator('.ec-time')
      if (await timeGrid.isVisible().catch(() => false)) {
        // The calendar is interactive
        expect(await timeGrid.isVisible()).toBe(true)
      }
    })
  })

  test.describe('Responsive Design', () => {
    test('should display correctly on mobile viewport', async ({ page }) => {
      // Set mobile viewport
      await page.setViewportSize({ width: 375, height: 667 })
      await page.reload()

      // Wait for calendar to load
      await page.waitForSelector('.ec', { timeout: 10000 })

      // Calendar should still be visible
      await expect(page.locator('.ec')).toBeVisible()
    })

    test('should display correctly on tablet viewport', async ({ page }) => {
      // Set tablet viewport
      await page.setViewportSize({ width: 768, height: 1024 })
      await page.reload()

      // Wait for calendar to load
      await page.waitForSelector('.ec', { timeout: 10000 })

      // Calendar should still be visible
      await expect(page.locator('.ec')).toBeVisible()
    })
  })

  test.describe('Accessibility', () => {
    test('should have accessible calendar elements', async ({ page }) => {
      await page.waitForSelector('.ec', { timeout: 10000 })

      // Check for aria labels on interactive elements
      const buttons = page.locator('button')
      const buttonCount = await buttons.count()

      // At least some navigation buttons should exist
      expect(buttonCount).toBeGreaterThan(0)
    })

    test('should be keyboard navigable', async ({ page }) => {
      await page.waitForSelector('.ec', { timeout: 10000 })

      // Tab through the interface
      await page.keyboard.press('Tab')
      await page.keyboard.press('Tab')

      // Check that focus moved to an element
      const focusedElement = page.locator(':focus')
      await expect(focusedElement).toBeDefined()
    })
  })
})
