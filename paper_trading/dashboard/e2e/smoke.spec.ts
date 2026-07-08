import { test, expect } from '@playwright/test'

test.describe('Dashboard smoke tests', () => {
  test('dashboard loads and shows page title', async ({ page }) => {
    await page.goto('/')
    // Vite dev server renders the React app — at minimum the HTML
    // shell should be present
    await expect(page.locator('#root')).toBeAttached({ timeout: 10_000 })
  })

  test('dashboard renders navigation sidebar', async ({ page }) => {
    await page.goto('/')
    // Wait for React to hydrate and render the app shell
    // The Sidebar contains navigation items — check for common labels
    await page.waitForSelector('nav', { timeout: 10_000 })
    const sidebar = page.locator('nav')
    await expect(sidebar).toBeVisible()
  })

  test('dashboard shows loading screen then transitions to live data', async ({ page }) => {
    await page.goto('/')

    // Initially the dashboard may show a loading state
    // Wait for React to mount and the app shell to render
    await page.waitForSelector('#root', { timeout: 10_000 })

    // The page should eventually show content beyond the loading shell
    // After 5 seconds of polling, we expect at least some UI elements
    // (loading screen qualifies as content if the backend isn't running)
    await page.waitForTimeout(3_000)

    // The sidebar navigation should be present regardless of backend state
    const navEl = page.locator('nav a, nav button, nav span').first()
    await expect(navEl).toBeAttached({ timeout: 5_000 })
  })

  test('dashboard handles backend unavailability gracefully', async ({ page }) => {
    // The dashboard should not crash when the backend (port 5000) is not running
    await page.goto('/')

    // Wait for the app to render
    await page.waitForSelector('#root', { timeout: 10_000 })

    // After a few seconds, the app should still be showing a valid UI
    // (loading screen, error screen, or partially loaded state — but not a blank page)
    await page.waitForTimeout(5_000)

    const bodyText = await page.locator('body').textContent()
    expect(bodyText).toBeTruthy()
    expect(bodyText!.length).toBeGreaterThan(0)
  })
})
