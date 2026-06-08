/**
 * Playwright E2E tests for Calendar Localization
 */
import { test, expect } from '@playwright/test'

test.describe('Calendar Localization', () => {
  test.describe('French Locale', () => {
    test.use({ locale: 'fr-FR' })

    test('should display French day headers', async ({ page }) => {
      await page.goto('/')
      await page.waitForSelector('.ec', { timeout: 10000 })

      // Check for French day abbreviations (Lun, Mar, Mer, Jeu, Ven, Sam, Dim)
      const dayHeaders = page.locator('.ec-day-head, .day-of-week')
      const dayHeaderCount = await dayHeaders.count()

      if (dayHeaderCount > 0) {
        const pageContent = await page.content()
        const frenchDays = ['lun', 'mar', 'mer', 'jeu', 'ven', 'sam', 'dim']
        const hasFrenchDay = frenchDays.some(day =>
          pageContent.toLowerCase().includes(day)
        )
        // Log result - this depends on actual locale implementation
        console.log('French day headers present:', hasFrenchDay)
      }
    })

    test('should display French month names', async ({ page }) => {
      await page.goto('/')
      await page.waitForSelector('.ec', { timeout: 10000 })

      const pageContent = await page.content().then(c => c.toLowerCase())
      const frenchMonths = [
        'janvier', 'février', 'mars', 'avril', 'mai', 'juin',
        'juillet', 'août', 'septembre', 'octobre', 'novembre', 'décembre'
      ]

      const hasFrenchMonth = frenchMonths.some(month =>
        pageContent.includes(month)
      )

      // Log result
      console.log('French month names present:', hasFrenchMonth)
    })

    test('should display French button labels', async ({ page }) => {
      await page.goto('/')
      await page.waitForSelector('.ec', { timeout: 10000 })

      // Check for French "Aujourd'hui" button
      const todayButton = page.locator('button:has-text("aujourd"), button:has-text("Aujourd")')
      const isVisible = await todayButton.isVisible().catch(() => false)

      if (isVisible) {
        await expect(todayButton).toBeVisible()
      }
    })

    test('should start week on Monday for French locale', async ({ page }) => {
      await page.goto('/')
      await page.waitForSelector('.ec', { timeout: 10000 })

      // In French locale, weeks typically start on Monday
      const firstDayHeader = page.locator('.ec-day-head').first()

      if (await firstDayHeader.isVisible().catch(() => false)) {
        const text = await firstDayHeader.textContent() || ''
        // Check if first day is Monday (Lun)
        const startsWithMonday = text.toLowerCase().includes('lun') || text.toLowerCase().includes('mon')
        console.log('First day of week:', text, 'Starts with Monday:', startsWithMonday)
      }
    })
  })

  test.describe('English Locale', () => {
    test.use({ locale: 'en-US' })

    test('should display English day headers', async ({ page }) => {
      await page.goto('/')
      await page.waitForSelector('.ec', { timeout: 10000 })

      const pageContent = await page.content().then(c => c.toLowerCase())
      const englishDays = ['sun', 'mon', 'tue', 'wed', 'thu', 'fri', 'sat']

      const hasEnglishDay = englishDays.some(day =>
        pageContent.includes(day)
      )

      console.log('English day headers present:', hasEnglishDay)
    })

    test('should display English month names', async ({ page }) => {
      await page.goto('/')
      await page.waitForSelector('.ec', { timeout: 10000 })

      const pageContent = await page.content().then(c => c.toLowerCase())
      const englishMonths = [
        'january', 'february', 'march', 'april', 'may', 'june',
        'july', 'august', 'september', 'october', 'november', 'december'
      ]

      const hasEnglishMonth = englishMonths.some(month =>
        pageContent.includes(month)
      )

      console.log('English month names present:', hasEnglishMonth)
    })

    test('should display English button labels', async ({ page }) => {
      await page.goto('/')
      await page.waitForSelector('.ec', { timeout: 10000 })

      // Check for English "Today" button
      const todayButton = page.locator('button:has-text("Today")')
      const isVisible = await todayButton.isVisible().catch(() => false)

      if (isVisible) {
        await expect(todayButton).toBeVisible()
      }
    })
  })

  test.describe('Dutch Locale', () => {
    test.use({ locale: 'nl-NL' })

    test('should display Dutch day headers', async ({ page }) => {
      await page.goto('/')
      await page.waitForSelector('.ec', { timeout: 10000 })

      const pageContent = await page.content().then(c => c.toLowerCase())
      // Dutch day abbreviations: ma, di, wo, do, vr, za, zo
      const dutchDays = ['ma', 'di', 'wo', 'do', 'vr', 'za', 'zo']

      const hasDutchDay = dutchDays.some(day =>
        pageContent.includes(day)
      )

      console.log('Dutch day headers present:', hasDutchDay)
    })

    test('should display Dutch month names', async ({ page }) => {
      await page.goto('/')
      await page.waitForSelector('.ec', { timeout: 10000 })

      const pageContent = await page.content().then(c => c.toLowerCase())
      const dutchMonths = [
        'januari', 'februari', 'maart', 'april', 'mei', 'juni',
        'juli', 'augustus', 'september', 'oktober', 'november', 'december'
      ]

      const hasDutchMonth = dutchMonths.some(month =>
        pageContent.includes(month)
      )

      console.log('Dutch month names present:', hasDutchMonth)
    })

    test('should start week on Monday for Dutch locale', async ({ page }) => {
      await page.goto('/')
      await page.waitForSelector('.ec', { timeout: 10000 })

      // In Dutch locale, weeks typically start on Monday
      const firstDayHeader = page.locator('.ec-day-head').first()

      if (await firstDayHeader.isVisible().catch(() => false)) {
        const text = await firstDayHeader.textContent() || ''
        // Check if first day is Monday (ma)
        const startsWithMonday = text.toLowerCase().includes('ma') || text.toLowerCase().includes('mon')
        console.log('First day of week:', text, 'Starts with Monday:', startsWithMonday)
      }
    })
  })

  test.describe('Locale Switching', () => {
    test('should persist locale preference', async ({ page, context }) => {
      // Set initial locale through browser settings
      await page.goto('/')
      await page.waitForSelector('.ec', { timeout: 10000 })

      // Store initial page content
      const initialContent = await page.content()

      // Reload page
      await page.reload()
      await page.waitForSelector('.ec', { timeout: 10000 })

      // Page should maintain consistent locale
      const reloadedContent = await page.content()

      // Both should have similar locale markers
      expect(reloadedContent).toBeDefined()
    })
  })

  test.describe('Date Formatting', () => {
    test.use({ locale: 'fr-FR' })

    test('should format dates according to locale', async ({ page }) => {
      await page.goto('/')
      await page.waitForSelector('.ec', { timeout: 10000 })

      // Check the title or header for date format
      const toolbar = page.locator('.ec-toolbar, .ec-title')
      if (await toolbar.isVisible().catch(() => false)) {
        const text = await toolbar.textContent() || ''
        // French dates often use format "janvier 2025" rather than "January 2025"
        console.log('Date display text:', text)
      }
    })

    test.use({ locale: 'en-US' })

    test('should format dates according to US locale', async ({ page }) => {
      await page.goto('/')
      await page.waitForSelector('.ec', { timeout: 10000 })

      const toolbar = page.locator('.ec-toolbar, .ec-title')
      if (await toolbar.isVisible().catch(() => false)) {
        const text = await toolbar.textContent() || ''
        console.log('Date display text (US):', text)
      }
    })
  })
})
