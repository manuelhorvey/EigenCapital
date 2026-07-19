import { test, expect } from '@playwright/test'
import AxeBuilder from '@axe-core/playwright'

test.describe('Accessibility (axe-core)', () => {
  test('dashboard page has no critical or serious violations', async ({ page }) => {
    await page.goto('/')
    await page.waitForLoadState('networkidle')

    const results = await new AxeBuilder({ page })
      .withTags(['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa'])
      .analyze()

    // Filter to only critical + serious
    const violations = results.violations.filter(
      v => v.impact === 'critical' || v.impact === 'serious',
    )

    expect(violations.length).toBe(0)
  })

  test('analytics page has no critical violations', async ({ page }) => {
    await page.goto('/analytics')
    await page.waitForLoadState('networkidle')

    const results = await new AxeBuilder({ page })
      .withTags(['wcag2a', 'wcag2aa'])
      .analyze()

    const violations = results.violations.filter(
      v => v.impact === 'critical' || v.impact === 'serious',
    )

    expect(violations.length).toBe(0)
  })
})
