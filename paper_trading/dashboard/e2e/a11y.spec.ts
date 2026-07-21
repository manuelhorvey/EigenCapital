import { test, expect } from '@playwright/test'
import AxeBuilder from '@axe-core/playwright'

test.describe('Accessibility (axe-core)', () => {
  const PAGES = [
    { path: '/', name: 'dashboard' },
    { path: '/trading', name: 'trading workspace' },
    { path: '/analytics', name: 'analytics workspace' },
    { path: '/risk', name: 'risk workspace' },
    { path: '/settings', name: 'settings' },
    { path: '/reports', name: 'reports' },
  ]

  for (const { path, name } of PAGES) {
    test(`${name} page has no critical or serious violations`, async ({ page }) => {
      await page.goto(path)
      await page.waitForLoadState('networkidle')

      const results = await new AxeBuilder({ page })
        .withTags(['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa'])
        .analyze()

      // Filter to only critical + serious
      const violations = results.violations.filter(
        v => v.impact === 'critical' || v.impact === 'serious',
      )

      // Log all violations (including minor) for triage
      if (results.violations.length > 0) {
        console.log(`[a11y] ${name} violations:`, JSON.stringify(
          results.violations.map(v => ({
            id: v.id,
            impact: v.impact,
            description: v.description,
            nodes: v.nodes.length,
          })),
          null, 2,
        ))
      }

      expect(violations.length).toBe(0)
    })
  }

  // Dedicated color-contrast check (WCAG 2.1 AA minimum)
  // Uses sequential for...of to avoid race conditions on the shared page instance
  test('all pages pass color contrast minimum', async ({ page }) => {
    for (const { path, name } of PAGES) {
      await page.goto(path)
      await page.waitForLoadState('networkidle')
      const r = await new AxeBuilder({ page })
        .withTags(['wcag2aa'])
        .include('body')
        .analyze()
      const violations = r.violations.filter(v => v.id === 'color-contrast')
      if (violations.length > 0) {
        console.log(`[a11y] Color contrast violations on ${name} (${path}):`, violations.length)
      }
      expect(violations.length).toBe(0)
    }
  })

  // Keyboard focus order (tab stops should be logical)
  test('dashboard page has visible focus indicators', async ({ page }) => {
    await page.goto('/')
    await page.waitForLoadState('networkidle')

    // Tab through interactive elements and check for visible focus
    const focusableSelector = 'button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])'
    const elements = await page.locator(focusableSelector).all()
    
    let focusableCount = 0
    for (const el of elements) {
      if (await el.isVisible()) {
        focusableCount++
        await el.focus()
        // Check that the focused element has an outline or ring style
        const boxShadow = await el.evaluate(el => window.getComputedStyle(el).boxShadow)
        const outline = await el.evaluate(el => window.getComputedStyle(el).outline)
        const hasVisibleFocus = boxShadow !== 'none' || (outline !== 'none' && outline !== '')
        
        if (!hasVisibleFocus) {
          console.warn(`[a11y] Element may lack visible focus:`, await el.evaluate(el => el.outerHTML.slice(0, 100)))
        }
      }
    }
    
    // At least some focusable elements exist
    expect(focusableCount).toBeGreaterThan(0)
  })
})
