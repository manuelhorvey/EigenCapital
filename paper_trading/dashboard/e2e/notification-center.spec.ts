import { test, expect } from '@playwright/test'

// ── Helpers ───────────────────────────────────────────────────────

const STORAGE_KEY = 'eigencapital_notifications'

function clearStorage() {
  sessionStorage.removeItem(STORAGE_KEY)
}

// ── Tests ─────────────────────────────────────────────────────────

test.describe('Notification center panel', () => {
  // ── Empty state ─────────────────────────────────────────────────

  test.describe('empty state', () => {
    test.beforeEach(async ({ page }) => {
      await page.addInitScript(clearStorage)
      await page.goto('/')
      // Wait for the top bar to render with the bell icon
      await page.waitForSelector('button[aria-label="Notifications"]', { timeout: 15_000 })
    })

    test('opens the notification center via bell icon', async ({ page }) => {
      const bellBtn = page.locator('button[aria-label="Notifications"]')
      await expect(bellBtn).toBeAttached()

      await bellBtn.click()

      const dialog = page.locator('div[role="dialog"][aria-label="Notification center"]')
      await expect(dialog).toBeVisible()
      await expect(dialog).toHaveAttribute('aria-modal', 'true')
    })

    test('shows empty state with "No notifications yet"', async ({ page }) => {
      await page.locator('button[aria-label="Notifications"]').click()
      await page.waitForSelector('div[role="dialog"][aria-label="Notification center"]', { timeout: 3_000 })

      // Empty state message
      await expect(page.locator('text=No notifications yet')).toBeVisible()
      // Contextual subtitle
      await expect(
        page.locator('text=System alerts, trade rejections, and status changes will appear here'),
      ).toBeVisible()
    })

    test('has severity filter tabs', async ({ page }) => {
      await page.locator('button[aria-label="Notifications"]').click()
      await page.waitForSelector('div[role="dialog"][aria-label="Notification center"]', { timeout: 3_000 })

      // All filter tabs should be present
      const filters = ['All', 'Errors', 'Warnings', 'Success', 'Info']
      for (const label of filters) {
        await expect(page.locator(`button:has-text("${label}")`)).toBeAttached()
      }

      // "All" filter is selected by default (has the active bg-panel class)
      const allFilter = page.locator('button:has-text("All")')
      await expect(allFilter).toHaveClass(/bg-panel/)

      // Other filters should not have the active class
      const errorsFilter = page.locator('button:has-text("Errors")')
      await expect(errorsFilter).not.toHaveClass(/bg-panel/)
    })

    test('close button and Escape key close the panel', async ({ page }) => {
      const bellBtn = page.locator('button[aria-label="Notifications"]')

      // Open
      await bellBtn.click()
      let dialog = page.locator('div[role="dialog"][aria-label="Notification center"]')
      await expect(dialog).toBeVisible()

      // Close via Escape
      await page.keyboard.press('Escape')
      await expect(dialog).not.toBeVisible()

      // Re-open
      await bellBtn.click()
      dialog = page.locator('div[role="dialog"][aria-label="Notification center"]')
      await expect(dialog).toBeVisible()

      // Close via backdrop click — backdrop covers the full viewport and the
      // panel is right-aligned, so clicking at (10, 10) hits the backdrop
      await page.mouse.click(10, 10)
      await expect(dialog).not.toBeVisible()
    })

    test('close button in the header closes the panel', async ({ page }) => {
      await page.locator('button[aria-label="Notifications"]').click()
      const dialog = page.locator('div[role="dialog"][aria-label="Notification center"]')
      await expect(dialog).toBeVisible()

      // X close button in header
      await page.locator('button[aria-label="Close notification center"]').click()
      await expect(dialog).not.toBeVisible()
    })
  })

  // ── Desktop notification permission request ─────────────────────

  test.describe('desktop notification permission', () => {
    test.beforeEach(async ({ page }) => {
      // Mock Notification API with 'default' permission so the
      // DesktopNotificationControls shows the "Enable" button instead
      // of the toggle switch. Also mock navigator.permissions.query
      // to prevent the useEffect sync from throwing.
      // Note: addInitScript runs in the browser's JavaScript context,
      // NOT through the TypeScript compiler — no type annotations allowed.
      await page.addInitScript(() => {
        // Override Notification with 'default' permission so the
        // DesktopNotificationControls shows the "Enable" button.
        function MockNotification(title, options) {
          // Minimal stub — tests don't call new Notification
        }
        MockNotification.permission = 'default'
        MockNotification.requestPermission = function () {
          return Promise.resolve('granted')
        }
        // Prevent the permission-sync useEffect from throwing
        var query = function () { return Promise.resolve({ onchange: null }) }
        if (navigator.permissions) {
          Object.defineProperty(navigator, 'permissions', {
            get: function () { return { query: query } },
            configurable: true,
          })
        }
        globalThis.Notification = MockNotification
      })
      await page.goto('/')
      await page.waitForSelector('button[aria-label="Notifications"]', { timeout: 15_000 })
    })

    test('shows "Enable" button when permission is default', async ({ page }) => {
      await page.locator('button[aria-label="Notifications"]').click()
      const dialog = page.locator('div[role="dialog"][aria-label="Notification center"]')
      await expect(dialog).toBeVisible()

      // Desktop notification controls section should be visible
      await expect(dialog.locator('text=Desktop notifications')).toBeVisible()
      // Status should show "off" since permission is default
      await expect(dialog.locator('text=off')).toBeVisible()
      // Enable button should be visible
      const enableBtn = dialog.locator('button:has-text("Enable")')
      await expect(enableBtn).toBeVisible()
    })

    test('clicking "Enable" transitions the UI to the granted state', async ({ page }) => {
      await page.locator('button[aria-label="Notifications"]').click()
      const dialog = page.locator('div[role="dialog"][aria-label="Notification center"]')
      await expect(dialog).toBeVisible()

      // Click the Enable button
      await dialog.locator('button:has-text("Enable")').click()

      // After granting permission, the status should change to "on"
      // and the toggle switch (role="switch") should appear
      await expect(dialog.locator('text=on')).toBeVisible()

      // Enable button should be gone
      await expect(dialog.locator('button:has-text("Enable")')).not.toBeVisible()

      // Toggle should be present with aria-checked="true"
      const toggle = dialog.locator('role=switch')
      await expect(toggle).toBeVisible()
      await expect(toggle).toHaveAttribute('aria-checked', 'true')
    })

    test('shows correct explanatory text before and after granting', async ({ page }) => {
      await page.locator('button[aria-label="Notifications"]').click()
      const dialog = page.locator('div[role="dialog"][aria-label="Notification center"]')
      await expect(dialog).toBeVisible()

      // Before: explanatory text about critical alerts
      await expect(
        dialog.locator('text=Receive critical alerts even when this tab is not focused'),
      ).toBeVisible()

      // Click Enable
      await dialog.locator('button:has-text("Enable")').click()

      // After: text about what desktop notifications do
      await expect(
        dialog.locator('text=Critical alerts and engine status changes will fire desktop notifications'),
      ).toBeVisible()
    })
  })

  // ── With seeded notifications ──────────────────────────────────

  test.describe('with notifications', () => {
    test.beforeEach(async ({ page }) => {
      // Seed 3 unread + 2 read notifications before React hydrates
      await page.addInitScript(() => {
        const STORAGE_KEY = 'eigencapital_notifications'
        const now = Date.now()
        sessionStorage.setItem(STORAGE_KEY, JSON.stringify([
          { id: 'n1', type: 'error', title: 'Asset AUDUSD halted', message: 'Max drawdown exceeded', timestamp: now - 60_000, read: false },
          { id: 'n2', type: 'warning', title: 'PSI drift elevated', message: 'EURUSD model drift at 42%', timestamp: now - 120_000, read: false },
          { id: 'n3', type: 'warning', title: 'GBPUSD signal rejected', message: 'PEK budget limit', timestamp: now - 180_000, read: false },
          { id: 'n4', type: 'success', title: 'Engine reconnected', message: '', timestamp: now - 300_000, read: true },
          { id: 'n5', type: 'info', title: 'Weekly report generated', message: 'Week 28 summary ready', timestamp: now - 600_000, read: true },
        ]))
      })
      await page.goto('/')
      await page.waitForSelector('button[aria-label="Notifications (3 unread)"]', { timeout: 15_000 })
    })

    test('bell icon shows unread badge with correct count', async ({ page }) => {
      const bellBtn = page.locator('button[aria-label="Notifications (3 unread)"]')
      await expect(bellBtn).toBeAttached()

      // Badge count should be visible (the red dot with number)
      await expect(bellBtn.locator('span')).toContainText('3')
    })

    test('lists all seeded notifications', async ({ page }) => {
      await page.locator('button[aria-label="Notifications (3 unread)"]').click()
      const dialog = page.locator('div[role="dialog"][aria-label="Notification center"]')
      await expect(dialog).toBeVisible()

      // All 5 notifications should be listed by title
      await expect(dialog.locator('text=Asset AUDUSD halted')).toBeVisible()
      await expect(dialog.locator('text=PSI drift elevated')).toBeVisible()
      await expect(dialog.locator('text=GBPUSD signal rejected')).toBeVisible()
      await expect(dialog.locator('text=Engine reconnected')).toBeVisible()
      await expect(dialog.locator('text=Weekly report generated')).toBeVisible()
    })

    test('severity filter shows only matching notifications', async ({ page }) => {
      await page.locator('button[aria-label="Notifications (3 unread)"]').click()
      const dialog = page.locator('div[role="dialog"][aria-label="Notification center"]')

      // Click "Errors" filter — only the error notification should remain
      await page.locator('button:has-text("Errors")').click()
      await expect(dialog.locator('text=Asset AUDUSD halted')).toBeVisible()
      await expect(dialog.locator('text=PSI drift elevated')).not.toBeVisible()

      // Click "Warnings" filter — only warnings
      await page.locator('button:has-text("Warnings")').click()
      await expect(dialog.locator('text=PSI drift elevated')).toBeVisible()
      await expect(dialog.locator('text=Asset AUDUSD halted')).not.toBeVisible()
      await expect(dialog.locator('text=GBPUSD signal rejected')).toBeVisible()

      // Click "Success" filter — only success
      await page.locator('button:has-text("Success")').click()
      await expect(dialog.locator('text=Engine reconnected')).toBeVisible()
      await expect(dialog.locator('text=Weekly report generated')).not.toBeVisible()

      // Click "All" — all visible again
      await page.locator('button:has-text("All")').click()
      await expect(dialog.locator('text=Asset AUDUSD halted')).toBeVisible()
      await expect(dialog.locator('text=Weekly report generated')).toBeVisible()
    })

    test('filter tabs show per-type counts', async ({ page }) => {
      await page.locator('button[aria-label="Notifications (3 unread)"]').click()

      // Each severity filter button should show the count in a span
      // Errors=1, Warnings=2, Success=1, Info=1
      const errorsBtn = page.locator('button:has-text("Errors")')
      await expect(errorsBtn.locator('span')).toContainText('1')

      const warningsBtn = page.locator('button:has-text("Warnings")')
      await expect(warningsBtn.locator('span')).toContainText('2')

      const successBtn = page.locator('button:has-text("Success")')
      await expect(successBtn.locator('span')).toContainText('1')

      const infoBtn = page.locator('button:has-text("Info")')
      await expect(infoBtn.locator('span')).toContainText('1')
    })

    test('marks a single notification as read', async ({ page }) => {
      await page.locator('button[aria-label="Notifications (3 unread)"]').click()
      const dialog = page.locator('div[role="dialog"][aria-label="Notification center"]')

      // The first unread notification should have a "Mark as read" button
      const markBtn = dialog.locator('button[aria-label="Mark \\"Asset AUDUSD halted\\" as read"]')
      await expect(markBtn).toBeAttached()

      // Click to mark as read
      await markBtn.click()

      // After marking one read, unread count should now be 2 in the bell badge
      // The page may not re-render the bell badge instantly — but the notification
      // should no longer have the "Mark as read" button (it's now read)
      await expect(markBtn).not.toBeAttached()
    })

    test('mark all as read clears all unread indicators', async ({ page }) => {
      await page.locator('button[aria-label="Notifications (3 unread)"]').click()

      // Mark all as read button should be visible
      const markAllBtn = page.locator('button[aria-label="Mark all as read"]')
      await expect(markAllBtn).toBeAttached()

      await markAllBtn.click()

      // After marking all as read:
      // - No individual mark-as-read buttons should remain
      await expect(page.locator('button[aria-label^="Mark \\""]')).not.toBeAttached()
      // - Bell badge should update (or disappear if all read)
      // The unread count in the badge may take a re-render cycle, but
      // the notification items should all show as read (no green dot)
    })

    test('footer summary shows total and unread counts', async ({ page }) => {
      await page.locator('button[aria-label="Notifications (3 unread)"]').click()

      // Footer shows "5 total · 3 unread" (using substring match for robustness)
      await expect(page.locator('div[role="dialog"]')).toContainText('5 total')
      await expect(page.locator('div[role="dialog"]')).toContainText('3 unread')
    })

    test('clear all removes all notifications', async ({ page }) => {
      await page.locator('button[aria-label="Notifications (3 unread)"]').click()

      // Click the clear all button
      const clearBtn = page.locator('button[aria-label="Clear all notifications"]')
      await expect(clearBtn).toBeAttached()
      await clearBtn.click()

      // Should show empty state
      await expect(page.locator('text=No notifications yet')).toBeVisible()
      // Footer summary should be gone
      await expect(page.locator('text=5 total · 3 unread')).not.toBeVisible()
      // Bell badge should be gone
      await expect(page.locator('button[aria-label="Notifications"]')).toBeAttached()
    })
  })

  // ── Bell badge sync ─────────────────────────────────────────────

  test.describe('bell badge sync', () => {
    test.beforeEach(async ({ page }) => {
      await page.addInitScript(() => {
        const STORAGE_KEY = 'eigencapital_notifications'
        const now = Date.now()
        sessionStorage.setItem(STORAGE_KEY, JSON.stringify([
          { id: 'n1', type: 'error', title: 'Asset AUDUSD halted', message: '', timestamp: now - 60_000, read: false },
          { id: 'n2', type: 'warning', title: 'PSI drift elevated', message: '', timestamp: now - 120_000, read: false },
          { id: 'n3', type: 'warning', title: 'GBPUSD signal rejected', message: '', timestamp: now - 180_000, read: false },
        ]))
      })
      await page.goto('/')
      await page.waitForSelector('button[aria-label="Notifications (3 unread)"]', { timeout: 15_000 })
    })

    test('bell badge shows correct unread count on page load', async ({ page }) => {
      const bellBtn = page.locator('button[aria-label="Notifications (3 unread)"]')
      await expect(bellBtn).toBeAttached()

      // Badge span shows the count
      const badge = bellBtn.locator('span')
      await expect(badge).toContainText('3')
    })

    test('marking one as read updates bell badge from 3 to 2', async ({ page }) => {
      const bellBtn = page.locator('button[aria-label="Notifications (3 unread)"]')
      await expect(bellBtn).toBeAttached()

      // Open notification center
      await bellBtn.click()
      const dialog = page.locator('div[role="dialog"][aria-label="Notification center"]')
      await expect(dialog).toBeVisible()

      // Mark the first notification as read
      const markBtn = dialog.locator('button[aria-label="Mark \\"Asset AUDUSD halted\\" as read"]')
      await expect(markBtn).toBeAttached()
      await markBtn.click()

      // Close the panel so we can see the bell badge update independently
      await page.keyboard.press('Escape')
      await expect(dialog).not.toBeVisible()

      // Bell badge should now show 2
      await expect(bellBtn).toHaveAttribute('aria-label', 'Notifications (2 unread)')
      await expect(bellBtn.locator('span')).toContainText('2')
    })

    test('marking all as read removes the bell badge', async ({ page }) => {
      const bellBtn = page.locator('button[aria-label="Notifications (3 unread)"]')
      await expect(bellBtn).toBeAttached()

      // Open and mark all as read
      await bellBtn.click()
      const dialog = page.locator('div[role="dialog"][aria-label="Notification center"]')
      await expect(dialog).toBeVisible()
      await dialog.locator('button[aria-label="Mark all as read"]').click()

      // Close the panel
      await page.keyboard.press('Escape')
      await expect(dialog).not.toBeVisible()

      // Bell badge should show no unread count
      await expect(bellBtn).toHaveAttribute('aria-label', 'Notifications')
      // Badge span should be absent
      await expect(bellBtn.locator('span')).toHaveCount(0)
    })

    test('clearing all notifications removes the bell badge', async ({ page }) => {
      const bellBtn = page.locator('button[aria-label="Notifications (3 unread)"]')
      await expect(bellBtn).toBeAttached()

      // Open and clear all
      await bellBtn.click()
      const dialog = page.locator('div[role="dialog"][aria-label="Notification center"]')
      await expect(dialog).toBeVisible()
      await dialog.locator('button[aria-label="Clear all notifications"]').click()

      // Close the panel
      await page.keyboard.press('Escape')
      await expect(dialog).not.toBeVisible()

      // Bell badge should show no unread count
      await expect(bellBtn).toHaveAttribute('aria-label', 'Notifications')
      await expect(bellBtn.locator('span')).toHaveCount(0)
    })
  })
})
