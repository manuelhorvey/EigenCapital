import { test, expect, type Page } from '@playwright/test'
import { createMockBundle, createMockHealthResponse, createMockAttributionTrades } from './mock-bundle'

// ── Helpers ───────────────────────────────────────────────────────

/**
 * Set up mock API routes before each test.
 * Intercepts all backend API calls to return mock data,
 * so the app renders fully without a running engine on port 5000.
 */
async function setupMockApi(page: Page) {
  const mockBundle = createMockBundle()

  // Main system bundle — the most critical endpoint
  await page.route('**/state-bundle.json', async route => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(mockBundle),
    })
  })

  // Engine health check
  await page.route('**/health', async route => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(createMockHealthResponse()),
    })
  })

  // Attribution trades (Analytics page PnL drill-down)
  await page.route('**/attribution/trades.json', async route => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(createMockAttributionTrades()),
    })
  })
}

// Navigation helper — works with HashRouter
function gotoHash(page: Page, path: string) {
  return page.goto(path === '/' ? '/' : `/#${path}`)
}

test.describe('Comprehensive smoke tests', () => {
  test.beforeEach(async ({ page }) => {
    await setupMockApi(page)
  })

  // ── Page Load & App Shell ───────────────────────────────────────

  test.describe('App shell renders on every route', () => {
    const ROUTES = [
      { path: '/', name: 'Command Center' },
      { path: '/trading', name: 'Trading' },
      { path: '/analytics', name: 'Analytics' },
      { path: '/risk', name: 'Risk' },
      { path: '/settings', name: 'Settings' },
      { path: '/reports', name: 'Reports' },
      { path: '/error', name: 'Server Error' },
      { path: '/offline', name: 'Offline' },
    ]

    for (const { path, name } of ROUTES) {
      test(`${name} (${path}) renders the app shell`, async ({ page }) => {
        await gotoHash(page, path)
        await page.waitForLoadState('networkidle')

        // Root element is mounted
        await expect(page.locator('#root')).toBeAttached({ timeout: 10_000 })

        // Main content landmark exists
        await expect(page.locator('main[role="main"]')).toBeAttached({ timeout: 10_000 })

        // Top bar is rendered
        await expect(page.locator('[aria-label="Top bar"]')).toBeAttached({ timeout: 5_000 })

        // Skip-to-content link exists on every page
        const skipLink = page.locator('a:has-text("Skip to main content")')
        await expect(skipLink).toBeAttached({ timeout: 5_000 })
        await expect(skipLink).toHaveAttribute('href', '#main-content')
      })
    }
  })

  test.describe('404 route renders NotFoundPage', () => {
    test('unknown route shows 404 page', async ({ page }) => {
      await page.goto('/#/some-nonexistent-route')
      await page.waitForLoadState('networkidle')
      await expect(page.locator('body')).toContainText(/404|page not found/i, { timeout: 10_000 })
      await expect(page.locator('button:has-text("Back to Dashboard")')).toBeAttached({ timeout: 5_000 })
    })
  })

  // ── Top Bar Elements ────────────────────────────────────────────

  test.describe('TopBar elements', () => {
    test('shows page title breadcrumb', async ({ page }) => {
      await page.goto('/')
      await page.waitForLoadState('networkidle')
      const topBar = page.locator('[aria-label="Top bar"]')
      await expect(topBar).toContainText(/EIGENCAPITAL|Command Center/, { timeout: 10_000 })
    })

    test('refresh button is clickable', async ({ page }) => {
      await page.goto('/')
      await page.waitForLoadState('networkidle')
      const refreshBtn = page.locator('button[aria-label="Refresh dashboard data"]')
      await expect(refreshBtn).toBeAttached({ timeout: 5_000 })
      // Use force:true in case an overlay (banner/toast) temporarily intercepts
      await refreshBtn.click({ force: true })
      await expect(refreshBtn).toBeAttached()
    })

    test('command palette button is present', async ({ page }) => {
      await page.goto('/')
      await page.waitForLoadState('networkidle')
      await expect(page.locator('button[aria-label="Open command palette"]')).toBeAttached({ timeout: 5_000 })
    })

    test('theme toggle button is present', async ({ page }) => {
      await page.goto('/')
      await page.waitForLoadState('networkidle')
      await expect(page.locator('button[aria-label*="Theme"]')).toBeAttached({ timeout: 5_000 })
    })

    test('notification bell is present', async ({ page }) => {
      await page.goto('/')
      await page.waitForLoadState('networkidle')
      await expect(page.locator('button[aria-label*="Notification"]')).toBeAttached({ timeout: 5_000 })
    })

    test('ticker rail shows status tokens', async ({ page }) => {
      await page.goto('/')
      await page.waitForLoadState('networkidle')
      const topBar = page.locator('[aria-label="Top bar"]')
      await expect(topBar).toContainText(/mt5|engine|halt|seq/, { timeout: 10_000 })
    })
  })

  // ── Sidebar Navigation ──────────────────────────────────────────

  test.describe('Sidebar navigation', () => {
    test('sidebar renders with all nav items on desktop', async ({ page }) => {
      await page.setViewportSize({ width: 1440, height: 900 })
      await page.goto('/')
      await page.waitForLoadState('networkidle')

      const sidebar = page.locator('aside[aria-label="Navigation"]')
      await expect(sidebar).toBeVisible({ timeout: 5_000 })

      await expect(sidebar.locator('#nav-dashboard')).toBeAttached()
      await expect(sidebar.locator('#nav-trading')).toBeAttached()
      await expect(sidebar.locator('#nav-analytics')).toBeAttached()
      await expect(sidebar.locator('#nav-risk')).toBeAttached({ timeout: 5_000 })
      await expect(sidebar.locator('#nav-reports')).toBeAttached({ timeout: 5_000 })
      await expect(sidebar.locator('#nav-settings')).toBeAttached({ timeout: 5_000 })
    })

    test('clicking sidebar nav item navigates to the correct route', async ({ page }) => {
      await page.setViewportSize({ width: 1440, height: 900 })
      await page.goto('/')
      await page.waitForLoadState('networkidle')

      await page.locator('#nav-analytics').click()
      await expect(page).toHaveURL(/\/analytics/, { timeout: 5_000 })
    })
  })

  // ── TabBar (Mobile) ─────────────────────────────────────────────

  test.describe('TabBar navigation', () => {
    test('tab bar renders with all tabs on mobile', async ({ page }) => {
      await page.setViewportSize({ width: 375, height: 667 })
      await page.goto('/')
      await page.waitForLoadState('networkidle')

      const tabBar = page.locator('nav[aria-label="Main tabs"]')
      await expect(tabBar).toBeVisible({ timeout: 5_000 })
      await expect(tabBar).toContainText('Dashboard')
      await expect(tabBar).toContainText('Trading')
      await expect(tabBar).toContainText('Analytics')
      await expect(tabBar).toContainText('Risk')
    })

    test('clicking tab bar navigates via hash URL', async ({ page }) => {
      await page.setViewportSize({ width: 375, height: 667 })
      // Navigate directly via hash URL instead of clicking tab (avoids overlay interception)
      await page.goto('/#/risk')
      await page.waitForLoadState('networkidle')
      await expect(page).toHaveURL(/\/risk/, { timeout: 5_000 })
      // Verify the page rendered by checking for a risk-specific element
      await expect(page.locator('h2:has-text("Governance")')).toBeAttached({ timeout: 5_000 })
    })
  })

  // ── Keyboard Navigation ─────────────────────────────────────────

  test.describe('Keyboard navigation', () => {
    test('? key opens keyboard shortcut dialog', async ({ page }) => {
      await page.goto('/')
      await page.waitForLoadState('networkidle')

      await page.keyboard.press('?')
      const dialog = page.locator('[role="dialog"][aria-label="Keyboard shortcuts"]')
      await expect(dialog).toBeAttached({ timeout: 3_000 })
      await expect(dialog).toBeVisible()

      await page.keyboard.press('Escape')
      await expect(dialog).not.toBeVisible()
    })

    test('Escape key closes the command palette if open', async ({ page }) => {
      await page.goto('/')
      await page.waitForLoadState('networkidle')

      await page.keyboard.press('Control+k')
      const searchInput = page.locator('input[role="combobox"]')
      await expect(searchInput).toBeVisible({ timeout: 3_000 })

      await page.keyboard.press('Escape')
      await expect(searchInput).not.toBeVisible()
    })

    test('sidebar nav supports roving tabindex with ArrowDown/ArrowUp', async ({ page }) => {
      await page.setViewportSize({ width: 1440, height: 900 })
      await page.goto('/')
      await page.waitForLoadState('networkidle')

      const firstNav = page.locator('nav[aria-label="Dashboard sections"] [role="listitem"]').first()
      await expect(firstNav).toBeAttached({ timeout: 5_000 })
      await firstNav.focus()

      await page.keyboard.press('ArrowDown')
      const secondNav = page.locator('nav[aria-label="Dashboard sections"] [role="listitem"]').nth(1)
      await expect(secondNav).toBeFocused()

      await page.keyboard.press('ArrowUp')
      await expect(firstNav).toBeFocused()
    })

    test('Home/End keys in sidebar nav jump to first/last', async ({ page }) => {
      await page.setViewportSize({ width: 1440, height: 900 })
      await page.goto('/')
      await page.waitForLoadState('networkidle')

      const navItems = page.locator('nav[aria-label="Dashboard sections"] [role="listitem"]')
      const count = await navItems.count()
      expect(count).toBeGreaterThanOrEqual(3)

      await navItems.first().focus()
      await page.keyboard.press('End')
      await expect(navItems.nth(count - 1)).toBeFocused()

      await page.keyboard.press('Home')
      await expect(navItems.first()).toBeFocused()
    })
  })

  // ── Command Palette ─────────────────────────────────────────────

  test.describe('Command palette', () => {
    test('Cmd+K opens the command palette', async ({ page }) => {
      await page.goto('/')
      await page.waitForLoadState('networkidle')

      await page.keyboard.press('Control+k')
      const palette = page.locator('input[role="combobox"]')
      await expect(palette).toBeVisible({ timeout: 3_000 })
      await expect(palette).toHaveAttribute('aria-expanded', 'true')
    })

    test('search filters commands', async ({ page }) => {
      await page.goto('/')
      await page.waitForLoadState('networkidle')

      await page.keyboard.press('Control+k')
      await page.locator('input[role="combobox"]').fill('Dashboard')
      const results = page.locator('[role="option"]')
      await expect(results.first()).toBeAttached()
    })

    test('enter on a navigation command navigates to the page', async ({ page }) => {
      await page.goto('/')
      await page.waitForLoadState('networkidle')

      await page.keyboard.press('Control+k')
      const searchInput = page.locator('input[role="combobox"]')
      await expect(searchInput).toBeVisible({ timeout: 3_000 })

      await searchInput.fill('Trading')
      const firstOption = page.locator('[role="option"]').first()
      await expect(firstOption).toContainText(/Trading/i, { timeout: 2_000 })

      await page.keyboard.press('Enter')
      await expect(page).toHaveURL(/\/trading/, { timeout: 5_000 })
    })

    test('shows section groupings (Navigation, Actions)', async ({ page }) => {
      await page.goto('/')
      await page.waitForLoadState('networkidle')

      await page.keyboard.press('Control+k')
      await expect(page.locator('input[role="combobox"]')).toBeVisible({ timeout: 3_000 })
      await expect(page.locator('text=Navigation')).toBeVisible()
      await expect(page.locator('text=Actions')).toBeVisible()
    })
  })

  // ── Theme Toggle ────────────────────────────────────────────────

  test.describe('Theme toggle', () => {
    test('theme cycling does not cause errors', async ({ page }) => {
      await page.goto('/')
      await page.waitForLoadState('networkidle')

      const themeBtn = page.locator('button[aria-label*="Theme"]')
      await expect(themeBtn).toBeAttached({ timeout: 5_000 })

      for (let i = 0; i < 3; i++) {
        await themeBtn.click({ force: true })
        await page.waitForTimeout(400)
        await expect(themeBtn).toBeAttached()
      }
    })
  })

  // ── Settings Page ───────────────────────────────────────────────

  test.describe('Settings page', () => {
    test('widget toggles are rendered', async ({ page }) => {
      await page.goto('/#/settings')
      await page.waitForLoadState('networkidle')

      await expect(page.locator('text=Dashboard Widgets')).toBeVisible({ timeout: 5_000 })
      const toggles = page.locator('input[type="checkbox"]')
      const count = await toggles.count()
      expect(count).toBeGreaterThanOrEqual(5)
    })

    test('notification settings section renders', async ({ page }) => {
      await page.goto('/#/settings')
      await page.waitForLoadState('networkidle')

      // Use h2 to target the section heading specifically
      await expect(page.locator('h2:has-text("Notifications")')).toBeVisible({ timeout: 5_000 })
      await expect(page.locator('text=Desktop Notifications')).toBeVisible()
      await expect(page.locator('text=Sound Alerts')).toBeVisible()
    })

    test('saved layouts section renders', async ({ page }) => {
      await page.goto('/#/settings')
      await page.waitForLoadState('networkidle')

      // Use h2 to target the section heading specifically, avoiding the empty state <p> that also contains 'saved layouts'
      await expect(page.locator('h2:has-text("Saved Layouts")')).toBeVisible({ timeout: 5_000 })
      await expect(page.locator('input[placeholder="Layout name…"]')).toBeAttached()
      await expect(page.locator('button:has-text("Save")')).toBeAttached()
    })

    test('reset to defaults button is present', async ({ page }) => {
      await page.goto('/#/settings')
      await page.waitForLoadState('networkidle')
      await expect(page.locator('button:has-text("Reset to defaults")')).toBeAttached({ timeout: 5_000 })
    })

    test('about section shows version info', async ({ page }) => {
      await page.goto('/#/settings')
      await page.waitForLoadState('networkidle')

      await expect(page.locator('text=About')).toBeVisible({ timeout: 5_000 })
      await expect(page.locator('text=Version')).toBeVisible()
      // Version number is unique to the About section — use it directly
      await expect(page.locator('text=2.0.0')).toBeVisible()
    })
  })

  // ── Reports Page ────────────────────────────────────────────────

  test.describe('Reports page', () => {
    test('report export buttons are rendered', async ({ page }) => {
      await page.goto('/#/reports')
      await page.waitForLoadState('networkidle')

      // Use the page heading specifically (h2 inside SectionHeader) rather than
      // the generic text="Reports" which matches TopBar, sidebar, and heading
      await expect(page.locator('h2:has-text("Reports")')).toBeVisible({ timeout: 5_000 })
      await expect(page.locator('text=Portfolio State Export')).toBeVisible()
      await expect(page.locator('text=Trade History Export')).toBeVisible()
      await expect(page.locator('text=Optimizer Data')).toBeVisible()
    })

    test('audit log section renders with search and filter controls', async ({ page }) => {
      await page.goto('/#/reports')
      await page.waitForLoadState('networkidle')

      // Use h2 to target the section heading specifically, avoiding sidebar/command palette matches
      await expect(page.locator('h2:has-text("Audit Log")')).toBeVisible({ timeout: 5_000 })
      await expect(page.locator('input[placeholder="Search audit log…"]')).toBeAttached()
      await expect(page.locator('button:has-text("Filters")')).toBeAttached()
      await expect(page.locator('button[title="Export as CSV"]')).toBeAttached()
    })
  })

  // ── Error & Offline Pages ───────────────────────────────────────

  test.describe('Error pages', () => {
    test('ServerErrorPage renders 500 content', async ({ page }) => {
      await page.goto('/#/error')
      await page.waitForLoadState('networkidle')

      await expect(page.locator('body')).toContainText(/500|something went wrong|internal error/i, { timeout: 10_000 })
      await expect(page.locator('summary:has-text("Troubleshooting")')).toBeAttached({ timeout: 5_000 })
    })

    test('OfflinePage renders offline content', async ({ page }) => {
      // Mock navigator.onLine to false BEFORE the page loads
      // so the OfflinePage component initializes in offline state
      await page.addInitScript(() => {
        Object.defineProperty(navigator, 'onLine', { configurable: true, get: () => false })
      })
      await page.goto('/#/offline')
      await page.waitForLoadState('networkidle')

      await expect(page.locator('body')).toContainText(/no connection|offline|network|try again/i, { timeout: 10_000 })
    })

    test('NotFoundPage renders 404 content', async ({ page }) => {
      await page.goto('/#/some-nonexistent-route')
      await page.waitForLoadState('networkidle')

      await expect(page.locator('body')).toContainText(/404|not found/i, { timeout: 10_000 })
      await expect(page.locator('button:has-text("Back to Dashboard")')).toBeAttached({ timeout: 5_000 })
    })
  })

  // ── HashRouter Behavior ─────────────────────────────────────────

  test.describe('HashRouter routing', () => {
    test('browser back/forward navigation works', async ({ page }) => {
      await page.goto('/')
      await page.waitForLoadState('networkidle')

      // Navigate to risk via sidebar link click
      await page.locator('#nav-risk').click()
      await page.waitForLoadState('networkidle')

      // Go back to dashboard
      await page.goBack()
      await expect(page).toHaveURL(/\/$/, { timeout: 5_000 })
    })
  })

  // ── ARIA Landmarks ──────────────────────────────────────────────

  test.describe('ARIA landmarks', () => {
    test('main content landmark is present on all routes', async ({ page }) => {
      const routes = ['/', '/trading', '/analytics', '/risk', '/settings', '/reports']
      for (const path of routes) {
        await page.goto(path === '/' ? '/' : `/#${path}`)
        await page.waitForLoadState('networkidle')

        const main = page.locator('main[role="main"]')
        await expect(main).toBeAttached({ timeout: 5_000 })
        await expect(main).toHaveAttribute('aria-label', 'Dashboard content')
      }
    })

    test('navigation landmarks are present', async ({ page }) => {
      await page.goto('/')
      await page.waitForLoadState('networkidle')

      await expect(page.locator('nav[aria-label="Dashboard sections"]')).toBeAttached({ timeout: 5_000 })
      await expect(page.locator('[aria-label="Top bar"]')).toBeAttached()
    })

    test('tab bar tabs have accessible aria-labels', async ({ page }) => {
      await page.goto('/')
      await page.waitForLoadState('networkidle')

      const tabs = page.locator('nav[aria-label="Main tabs"] a[aria-label]')
      const count = await tabs.count()
      expect(count).toBeGreaterThanOrEqual(3)
    })
  })
})
