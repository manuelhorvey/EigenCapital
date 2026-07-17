import { test, expect } from '@playwright/test'

test.describe('AssetDetailPanel keyboard tab navigation', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/trading')
    // Wait for signal table to render with at least one data row
    await page.waitForSelector('table tbody tr', { timeout: 15_000 })
    // Click first asset row to open the slide-over detail panel
    await page.locator('table tbody tr').first().click()
    // Wait for the tablist to appear inside the panel
    await page.waitForSelector('div[role="tablist"]', { timeout: 5_000 })
  })

  test('panel opens and tabs are present', async ({ page }) => {
    const tabs = page.locator('div[role="tablist"] button[role="tab"]')
    await expect(tabs.first()).toBeAttached()

    const tabCount = await tabs.count()
    expect(tabCount).toBeGreaterThanOrEqual(4)

    // First tab should be selected by default
    const firstTab = tabs.nth(0)
    await expect(firstTab).toHaveAttribute('aria-selected', 'true')
    await expect(firstTab).toHaveAttribute('tabindex', '0')
  })

  test('ArrowRight activates the next tab', async ({ page }) => {
    const tabs = page.locator('div[role="tablist"] button[role="tab"]')
    const first = tabs.nth(0)
    const second = tabs.nth(1)

    // Focus the first tab
    await first.focus()
    await expect(first).toBeFocused()

    // Press ArrowRight — should activate second tab
    await page.keyboard.press('ArrowRight')
    await expect(second).toHaveAttribute('aria-selected', 'true')
    await expect(first).toHaveAttribute('aria-selected', 'false')
  })

  test('ArrowLeft activates the previous tab', async ({ page }) => {
    const tabs = page.locator('div[role="tablist"] button[role="tab"]')
    const first = tabs.nth(0)
    const second = tabs.nth(1)

    // Navigate to second tab first
    await first.focus()
    await page.keyboard.press('ArrowRight')
    await expect(second).toHaveAttribute('aria-selected', 'true')

    // Press ArrowLeft — should go back to first
    await page.keyboard.press('ArrowLeft')
    await expect(first).toHaveAttribute('aria-selected', 'true')
    await expect(second).toHaveAttribute('aria-selected', 'false')
  })

  test('ArrowRight wraps to first tab from last tab', async ({ page }) => {
    const tabs = page.locator('div[role="tablist"] button[role="tab"]')
    const count = await tabs.count()
    const last = tabs.nth(count - 1)
    const first = tabs.nth(0)

    // Navigate to last tab
    await first.focus()
    for (let i = 1; i < count; i++) {
      await page.keyboard.press('ArrowRight')
    }
    await expect(last).toHaveAttribute('aria-selected', 'true')

    // One more ArrowRight should wrap to first
    await page.keyboard.press('ArrowRight')
    await expect(first).toHaveAttribute('aria-selected', 'true')
  })

  test('ArrowLeft wraps to last tab from first tab', async ({ page }) => {
    const tabs = page.locator('div[role="tablist"] button[role="tab"]')
    const count = await tabs.count()
    const first = tabs.nth(0)
    const last = tabs.nth(count - 1)

    // Focus first tab, press ArrowLeft — wraps to last
    await first.focus()
    await page.keyboard.press('ArrowLeft')
    await expect(last).toHaveAttribute('aria-selected', 'true')
  })

  test('Home key activates the first tab', async ({ page }) => {
    const tabs = page.locator('div[role="tablist"] button[role="tab"]')
    const first = tabs.nth(0)
    const last = tabs.nth(await tabs.count() - 1)

    // Navigate to last tab
    await first.focus()
    for (let i = 1; i < await tabs.count(); i++) {
      await page.keyboard.press('ArrowRight')
    }
    await expect(last).toHaveAttribute('aria-selected', 'true')

    // Press Home — should go to first tab
    await page.keyboard.press('Home')
    await expect(first).toHaveAttribute('aria-selected', 'true')
  })

  test('End key activates the last tab', async ({ page }) => {
    const tabs = page.locator('div[role="tablist"] button[role="tab"]')
    const first = tabs.nth(0)
    const last = tabs.nth(await tabs.count() - 1)

    // Focus first tab, press End — should go to last
    await first.focus()
    await page.keyboard.press('End')
    await expect(last).toHaveAttribute('aria-selected', 'true')
  })

  test('tabIndex roves correctly: only active tab has tabIndex=0', async ({ page }) => {
    const tabs = page.locator('div[role="tablist"] button[role="tab"]')

    // Initially only first tab has tabIndex=0
    await expect(tabs.nth(0)).toHaveAttribute('tabindex', '0')
    for (let i = 1; i < await tabs.count(); i++) {
      await expect(tabs.nth(i)).toHaveAttribute('tabindex', '-1')
    }

    // Navigate to second tab
    await tabs.nth(0).focus()
    await page.keyboard.press('ArrowRight')

    // Now only second tab has tabIndex=0
    await expect(tabs.nth(1)).toHaveAttribute('tabindex', '0')
    await expect(tabs.nth(0)).toHaveAttribute('tabindex', '-1')
  })

  test('Tab key moves focus from tablist to tabpanel content', async ({ page }) => {
    const tabs = page.locator('div[role="tablist"] button[role="tab"]')
    await tabs.nth(0).focus()

    // Press Tab to move out of the tablist into the tabpanel
    await page.keyboard.press('Tab')

    // The active tabpanel should receive focus
    const activePanel = page.locator('div[role="tabpanel"]')
    await expect(activePanel).toBeAttached()
  })

  test('panel content changes when switching tabs', async ({ page }) => {
    const tabs = page.locator('div[role="tablist"] button[role="tab"]')
    const tabPanels = page.locator('div[role="tabpanel"]')

    // First tab panel should be visible (Overview)
    const firstTabText = await tabPanels.nth(0).textContent()

    // Navigate to second tab
    await tabs.nth(0).focus()
    await page.keyboard.press('ArrowRight')

    // Second tab panel should have different content (different tab visible)
    const secondTabVisible = page.locator('div[role="tabpanel"]')
    const secondTabText = await secondTabVisible.textContent()
    expect(secondTabText).not.toBe(firstTabText)
  })

  test('screen reader attributes are correct on each tab', async ({ page }) => {
    const tabs = page.locator('div[role="tablist"] button[role="tab"]')
    const count = await tabs.count()
    for (let i = 0; i < count; i++) {
      const tab = tabs.nth(i)
      // Each tab needs:
      // - role="tab"
      await expect(tab).toHaveAttribute('role', 'tab')
      // - aria-selected is present
      await expect(tab).toHaveAttribute('aria-selected')
      // - aria-controls referencing a panel id
      const controls = await tab.getAttribute('aria-controls')
      expect(controls).toBeTruthy()
      expect(controls).toMatch(/^ec-tab-panel-/)
    }
  })

  test('tabpanel has correct ARIA attributes', async ({ page }) => {
    // Focus and activate the first tab, then Tab into the panel
    const tabs = page.locator('div[role="tablist"] button[role="tab"]')
    await tabs.nth(0).focus()
    await page.keyboard.press('Tab')

    const panel = page.locator('div[role="tabpanel"]')
    // Must be a live tabpanel
    await expect(panel).toHaveAttribute('role', 'tabpanel')
    // Must reference its tab via aria-labelledby
    const labelledBy = await panel.getAttribute('aria-labelledby')
    expect(labelledBy).toBeTruthy()
    expect(labelledBy).toMatch(/^ec-tab-/)
  })
})
