import { test, expect } from '@playwright/test'

test.describe('Mobile viewport (375px)', () => {
  test.use({ viewport: { width: 375, height: 812 } })

  test('renders sidebar hamburger and tab bar', async ({ page }) => {
    await page.goto('/')
    await page.waitForLoadState('networkidle')

    // Hamburger menu visible on mobile
    const menuBtn = page.locator('button[aria-label="Open navigation"]')
    await expect(menuBtn).toBeVisible()

    // Tab bar visible below top bar
    const tabBar = page.locator('[aria-label="Mobile navigation"]')
    await expect(tabBar).toBeVisible()

    // Ticker tokens should show critical ones (engine, halt, mt5)
    const engineToken = page.locator('text=engine')
    await expect(engineToken).toBeVisible()
  })

  test('sidebar opens and closes via hamburger', async ({ page }) => {
    await page.goto('/')
    await page.waitForLoadState('networkidle')

    const menuBtn = page.locator('button[aria-label="Open navigation"]')

    // Open sidebar
    await menuBtn.click()
    const sidebar = page.locator('[aria-label="Main navigation"]')
    await expect(sidebar).toBeVisible({ timeout: 1000 })

    // Close via backdrop
    const backdrop = page.locator('.fixed.inset-0.bg-black\\/60')
    await backdrop.click()
    await expect(sidebar).not.toBeVisible({ timeout: 1000 })
  })

  test('page navigation via tab bar works', async ({ page }) => {
    await page.goto('/')
    await page.waitForLoadState('networkidle')

    // Click Trading tab in mobile tab bar
    const tradingTab = page.locator('[aria-label="Mobile navigation"] a', { hasText: 'Trading' })
    await expect(tradingTab).toBeVisible()
    await tradingTab.click()

    await expect(page).toHaveURL(/\/trading/)
  })

  test('command palette works on mobile', async ({ page }) => {
    await page.goto('/')
    await page.waitForLoadState('networkidle')

    await page.keyboard.press('Control+k')
    const palette = page.locator('input[placeholder*="Search"]')
    await expect(palette).toBeVisible({ timeout: 1000 })

    await palette.fill('Dashboard')
    await page.keyboard.press('Enter')
    await expect(page).toHaveURL('/')
  })
})
