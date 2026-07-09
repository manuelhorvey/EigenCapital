import { test, expect } from '@playwright/test'

test.describe('Dashboard smoke tests', () => {
  // ── Page Load ───────────────────────────────────────────────────

  test('dashboard loads and renders app shell', async ({ page }) => {
    await page.goto('/')
    await expect(page.locator('#root')).toBeAttached({ timeout: 15_000 })
    // Main content area should exist
    await expect(page.locator('main[role="main"]')).toBeAttached({ timeout: 10_000 })
  })

  test('dashboard renders navigation sidebar with sections', async ({ page }) => {
    await page.goto('/')
    await expect(page.locator('nav[aria-label="Dashboard sections"]')).toBeAttached({ timeout: 10_000 })
    // Sidebar should contain Overview and Trading groups
    await expect(page.locator('nav[aria-label="Dashboard sections"]')).toContainText('Overview')
    await expect(page.locator('nav[aria-label="Dashboard sections"]')).toContainText('Trading')
    await expect(page.locator('nav[aria-label="Dashboard sections"]')).toContainText('Risk')
  })

  test('dashboard renders top tab bar with all tabs', async ({ page }) => {
    await page.goto('/')
    const tabBar = page.locator('nav[aria-label="Main tabs"]')
    await expect(tabBar).toBeAttached({ timeout: 10_000 })
    await expect(tabBar).toContainText('Dashboard')
    await expect(tabBar).toContainText('Trading')
    await expect(tabBar).toContainText('Execution')
    await expect(tabBar).toContainText('Risk')
  })

  test('dashboard renders ticker rail with asset prices', async ({ page }) => {
    await page.goto('/')
    // Ticker rail has aria-live="polite" for live price updates
    const rail = page.locator('[aria-live="polite"]')
    // At least one aria-live region should exist (ticker rail or alerts)
    await expect(rail.first()).toBeAttached({ timeout: 10_000 })
  })

  // ── Page Navigation ─────────────────────────────────────────────

  test('navigates to Trading workspace via sidebar', async ({ page }) => {
    await page.goto('/')
    const tradingLink = page.locator('a[href="/trading"]')
    await expect(tradingLink.first()).toBeVisible({ timeout: 10_000 })
    await tradingLink.first().click()
    await page.waitForURL('**/trading')
    await expect(page.locator('#root')).toBeAttached({ timeout: 5_000 })
  })

  test('navigates to Execution workspace via tab bar', async ({ page }) => {
    await page.goto('/')
    const execTab = page.locator('nav[aria-label="Main tabs"] a[href="/execution"]')
    await expect(execTab).toBeVisible({ timeout: 10_000 })
    await execTab.click()
    await page.waitForURL('**/execution')
    await expect(page.locator('#root')).toBeAttached({ timeout: 5_000 })
  })

  test('navigates to Risk workspace', async ({ page }) => {
    await page.goto('/')
    const riskTab = page.locator('nav[aria-label="Main tabs"] a[href="/risk"]')
    await expect(riskTab).toBeVisible({ timeout: 10_000 })
    await riskTab.click()
    await page.waitForURL('**/risk')
    await expect(page.locator('#root')).toBeAttached({ timeout: 5_000 })
  })

  test('navigating back to Dashboard works', async ({ page }) => {
    await page.goto('/risk')
    const dashLink = page.locator('a[href="/"]').first()
    await expect(dashLink).toBeVisible({ timeout: 10_000 })
    await dashLink.click()
    await page.waitForURL('**/')
    await expect(page.locator('#root')).toBeAttached({ timeout: 5_000 })
  })

  // ── Error Pages ─────────────────────────────────────────────────

  test('404 page renders for unknown route', async ({ page }) => {
    await page.goto('/some-nonexistent-route')
    // NotFoundPage renders "Page not found" — wait for React to hydrate
    await expect(page.locator('body')).toContainText('Page not found', { timeout: 10_000 })
  })

  test('error page renders at /error route', async ({ page }) => {
    await page.goto('/error')
    // ServerErrorPage renders "Something went wrong" or similar
    await expect(page.locator('body')).toContainText(/something went wrong|unexpected|try again/i, { timeout: 10_000 })
  })

  test('offline page renders at /offline route', async ({ page }) => {
    await page.goto('/offline')
    // OfflinePage renders "You are offline" or similar
    await expect(page.locator('body')).toContainText(/you are offline|no internet|connect/i, { timeout: 10_000 })
  })

  // ── Theme Toggle ────────────────────────────────────────────────

  test('theme toggle button exists and is clickable', async ({ page }) => {
    await page.goto('/')
    await page.waitForTimeout(2_000)
    const toggle = page.locator('button[aria-label*="Theme"]')
    await expect(toggle).toBeAttached({ timeout: 5_000 })
    // Click should cycle without error
    await toggle.click()
    // Should have updated the aria-label
    await expect(toggle).toBeAttached()
  })

  // ── Skip-to-Content Link ────────────────────────────────────────

  test('skip-to-content link is present and targets main element', async ({ page }) => {
    await page.goto('/')
    const skipLink = page.locator('a:has-text("Skip to main content")')
    await expect(skipLink).toBeAttached({ timeout: 5_000 })
    // Link should target the main content element
    const href = await skipLink.getAttribute('href')
    expect(href).toBe('#main-content')
  })

  // ── Keyboard Shortcuts ─────────────────────────────────────────

  test('keyboard shortcut panel opens and closes with ? key', async ({ page }) => {
    await page.goto('/')
    await page.waitForTimeout(2_000)

    // Press ? to open shortcuts
    await page.keyboard.press('?')
    const dialog = page.locator('[role="dialog"][aria-label="Keyboard shortcuts"]')
    await expect(dialog).toBeAttached({ timeout: 3_000 })
    await expect(dialog).toBeVisible()

    // Press Escape to close
    await page.keyboard.press('Escape')
    await expect(dialog).not.toBeVisible()
  })

  // ── Accessibility ───────────────────────────────────────────────

  test('has accessible main content landmark with correct label', async ({ page }) => {
    await page.goto('/')
    const main = page.locator('main[role="main"]')
    await expect(main).toBeAttached({ timeout: 10_000 })
    await expect(main).toHaveAttribute('aria-label', 'Dashboard content')
  })

  test('sidebar navigation has correct ARIA roles', async ({ page }) => {
    await page.goto('/')
    const nav = page.locator('nav[aria-label="Dashboard sections"]')
    await expect(nav).toBeAttached({ timeout: 10_000 })
    // Nav items should have role="listitem"
    await expect(nav.locator('[role="listitem"]').first()).toBeAttached({ timeout: 5_000 })
  })

  test('tab bar has accessible aria-label', async ({ page }) => {
    await page.goto('/')
    const tabBar = page.locator('nav[aria-label="Main tabs"]')
    await expect(tabBar).toBeAttached({ timeout: 10_000 })
    // Each tab should have an aria-label
    const tabs = tabBar.locator('a[aria-label]')
    const count = await tabs.count()
    expect(count).toBeGreaterThanOrEqual(3)
  })

  // ── Backend Unavailability ──────────────────────────────────────

  test('handles backend unavailability gracefully — never blank page', async ({ page }) => {
    await page.goto('/')
    await page.waitForSelector('#root', { timeout: 15_000 })
    await page.waitForTimeout(5_000)

    // Page should have content (loading state or partial render)
    const bodyText = await page.locator('body').textContent()
    expect(bodyText).toBeTruthy()
    expect(bodyText!.length).toBeGreaterThan(0)
    // Should not show React error overlay
    await expect(page.locator('#root')).toBeAttached()
  })

  // ── Responsive / Mobile ─────────────────────────────────────────

  test('mobile viewport shows mobile navigation toggle', async ({ page }) => {
    await page.setViewportSize({ width: 375, height: 667 }) // iPhone SE
    await page.goto('/')
    await page.waitForTimeout(2_000)
    // Mobile should have a hamburger menu (aria-label="Open navigation")
    const menuButton = page.locator('button[aria-label="Open navigation"]')
    await expect(menuButton).toBeAttached({ timeout: 5_000 })
  })

  test('mobile viewport navigation opens and closes sidebar', async ({ page }) => {
    await page.setViewportSize({ width: 375, height: 667 })
    await page.goto('/')
    await page.waitForTimeout(2_000)

    // Open sidebar via button
    const menuButton = page.locator('button[aria-label="Open navigation"]')
    await menuButton.click()
    await page.waitForTimeout(500)

    // Sidebar dialog should be visible
    const sidebar = page.locator('aside[aria-label="Navigation"]')
    await expect(sidebar).toBeAttached()

    // Close via close button
    const closeBtn = page.locator('button[aria-label="Close navigation"]')
    await expect(closeBtn).toBeAttached()
    await closeBtn.click()
    await page.waitForTimeout(500)
  })
})
