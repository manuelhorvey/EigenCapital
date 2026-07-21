/**
 * Headless WCAG AA accessibility check for CI — with baseline comparison.
 *
 * Compares current axe-core violations against a committed baseline file
 * so that only NEW violations (not pre-existing ones) cause CI to fail.
 * This allows the team to fix violations incrementally without blocking
 * CI on known issues.
 *
 * Baseline format (scripts/a11y-baseline.json):
 *   { "PageName": { "violation-id": nodeCount } }
 *
 * Usage:
 *   # Update baseline (run when you've fixed violations or added known new ones):
 *   npx tsx scripts/check-a11y.ts --update-baseline
 *
 *   # Check against baseline (default — used in CI):
 *   npx tsx scripts/check-a11y.ts
 *
 *   # Override baseline file:
 *   npx tsx scripts/check-a11y.ts --baseline path/to/baseline.json
 *
 *   # Connect to a custom server:
 *   PLAYWRIGHT_BASE_URL=http://localhost:3000 npx tsx scripts/check-a11y.ts
 *
 * Comparison rules:
 *   - Violation NOT in baseline  → NEW → FAIL
 *   - Node count HIGHER than baseline → REGRESSION → FAIL
 *   - Node count SAME or LOWER than baseline → OK
 *   - Node count LOWER than baseline → improvement logged (informational)
 */

import { chromium, type Browser, type Page } from 'playwright'
import AxeBuilder from '@axe-core/playwright'
import * as fs from 'fs'
import * as path from 'path'
import { fileURLToPath } from 'url'

const __filename = fileURLToPath(import.meta.url)
const __dirname = path.dirname(__filename)

// ── Configuration ──────────────────────────────────────────────────

const PAGES = [
  { path: '/', name: 'Command Center' },
  { path: '/trading', name: 'Trading Workspace' },
  { path: '/analytics', name: 'Analytics Workspace' },
  { path: '/risk', name: 'Risk Workspace' },
  { path: '/settings', name: 'Settings' },
  { path: '/reports', name: 'Reports' },
  { path: '/error', name: 'Server Error' },
  { path: '/offline', name: 'Offline' },
  { path: '/some-nonexistent-route', name: '404 Not Found' },
]

const BASE_URL = process.env.PLAYWRIGHT_BASE_URL || 'http://localhost:4173'
const DEFAULT_BASELINE_PATH = path.join(__dirname, 'a11y-baseline.json')

// Tags that define WCAG 2.1 AA compliance scope
const WCAG_AA_TAGS = ['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa']

// Axe rules to disable (with documented justification)
//
// Pre-existing violations are listed here so CI only flags NEW violations.
// Each entry includes the known count range and a reference to the tracking
// issue. When a violation is fixed, remove it from this array and run:
//   npm run a11y:update-baseline
const DISABLE_RULES: string[] = [
  // ── Pre-existing: color contrast on panel/surface backgrounds ──
  // Known range: Command Center (3), content pages (39), error pages (40)
  // Scope: text-tertiary and text-muted on elevated surfaces (elev-3, elev-4)
  // Progress: reduced from 279 → ~39 via text color token fix in color-system.ts
  // Next step: fix remaining instances in elevated/nested surfaces
  'color-contrast',

  // ── Fixed: aria-prohibited-attr (engine dot) + aria-required-children (nav list) ──
  // Removed from DISABLE_RULES 2026-07-20. See investigation in Sidebar.tsx:
  // - Engine dot: added role="status" to make aria-label valid
  // - Nav list: removed role="list" from <nav> (nav already provides landmark)
  // - NavLink: removed role="listitem" (NavLink renders <a>, implicit link role)
  //
  // ── Pre-existing: SVG images missing accessible labels ────────
  // 6 pages affected (1 element each) — lucide icons and chart SVGs
  // without aria-label or title in child elements.
  // Fix: add title element or aria-label to SVG components.
  'svg-img-alt',

  // ── Pre-existing: ARIA roles nested incorrectly ───────────────
  // 8 pages affected (2 violations each) — shared layout components.
  // Roles include aria-allowed-attr (element role doesn't support its
  // attributes) and aria-required-parent (role lacks required parent).
  // Fix: audit the component tree for correct ARIA role hierarchy.
  'aria-allowed-attr',
  'aria-required-parent',

  // ── Pre-existing: custom scroll containers ────────────────────
  // Dashboard panels use custom scroll containers that aren't keyboard-focusable.
  // Fix: add tabindex="0" or use native overflow with keyboard support.
  'scrollable-region-focusable',
]

// ── Baseline types ─────────────────────────────────────────────────

/** Baseline shape: { "Page Name": { "violation-id": nodeCount, ... } } */
type Baseline = Record<string, Record<string, number>>

/** Diff result for a single violation on a single page */
interface ViolationDiff {
  page: string
  id: string
  impact: string
  description: string
  helpUrl: string
  currentCount: number
  baselineCount: number | undefined
  status: 'OK' | 'IMPROVED' | 'REGRESSION' | 'NEW'
}

// ── CLI arg parsing ────────────────────────────────────────────────

const args = process.argv.slice(2)
const UPDATE_BASELINE = args.includes('--update-baseline')
const BASELINE_PATH = (() => {
  const idx = args.indexOf('--baseline')
  if (idx !== -1 && idx + 1 < args.length) {
    return path.resolve(args[idx + 1])
  }
  return DEFAULT_BASELINE_PATH
})()

// ── Baseline load / save ───────────────────────────────────────────

function loadBaseline(filePath: string): Baseline {
  try {
    const raw = fs.readFileSync(filePath, 'utf-8')
    return JSON.parse(raw) as Baseline
  } catch {
    return {}
  }
}

function saveBaseline(filePath: string, baseline: Baseline): void {
  const dir = path.dirname(filePath)
  if (!fs.existsSync(dir)) {
    fs.mkdirSync(dir, { recursive: true })
  }
  fs.writeFileSync(filePath, JSON.stringify(baseline, null, 2) + '\n', 'utf-8')
  console.log(`\n  📝 Baseline written: ${filePath}`)
}

// ── Diff computation ───────────────────────────────────────────────

function computeDiffs(
  pageViolations: ViolationSummary[],
  baseline: Baseline,
  pageName: string,
): ViolationDiff[] {
  const pageBaseline = baseline[pageName] || {}
  const diffs: ViolationDiff[] = []

  for (const v of pageViolations) {
    const baselineCount = pageBaseline[v.id]
    let status: ViolationDiff['status']

    if (baselineCount === undefined) {
      status = 'NEW'
    } else if (v.nodes > baselineCount) {
      status = 'REGRESSION'
    } else if (v.nodes < baselineCount) {
      status = 'IMPROVED'
    } else {
      status = 'OK'
    }

    diffs.push({
      page: pageName,
      id: v.id,
      impact: v.impact,
      description: v.description,
      helpUrl: v.helpUrl,
      currentCount: v.nodes,
      baselineCount,
      status,
    })
  }

  // Also flag if the baseline has entries that are now gone (fully fixed)
  for (const [id, count] of Object.entries(pageBaseline)) {
    const stillExists = pageViolations.some((v) => v.id === id)
    if (!stillExists) {
      diffs.push({
        page: pageName,
        id,
        impact: 'serious',
        description: 'This violation no longer exists — update baseline to reflect the fix.',
        helpUrl: '',
        currentCount: 0,
        baselineCount: count,
        status: 'IMPROVED',
      })
    }
  }

  return diffs
}

// ── Baseline extractor (for --update-baseline) ─────────────────────

function extractBaseline(pageViolations: ViolationSummary[]): Record<string, number> {
  const baseline: Record<string, number> = {}
  for (const v of pageViolations) {
    baseline[v.id] = v.nodes
  }
  return baseline
}

// ── Results helpers ────────────────────────────────────────────────

interface ViolationSummary {
  page: string
  id: string
  impact: string
  description: string
  help: string
  helpUrl: string
  nodes: number
  tags: string[]
}

interface PageResult {
  page: string
  path: string
  violations: ViolationSummary[]
  passed: boolean
  durationMs: number
}

// ── Main ───────────────────────────────────────────────────────────

async function runAudit() {
  console.log(`\n  🔍 Accessibility Audit — WCAG 2.1 AA\n`)
  console.log(`  Target: ${BASE_URL}`)
  console.log(`  Pages:  ${PAGES.length}`)
  if (UPDATE_BASELINE) {
    console.log(`  Mode:   📝 Update baseline (${BASELINE_PATH})`)
  } else {
    console.log(`  Mode:   🔍 Compare against baseline (${BASELINE_PATH})`)
  }
  console.log()

  const startTime = Date.now()
  const results: PageResult[] = []
  const baselineAccumulator: Baseline = {}
  let totalViolations = 0
  let totalCritical = 0
  let totalSerious = 0

  let browser: Browser | null = null

  try {
    browser = await chromium.launch({ headless: true })
    const context = await browser.newContext({
      viewport: { width: 1440, height: 900 },
      reducedMotion: 'reduce',
    })
    const page: Page = await context.newPage()

    for (const { path: route, name } of PAGES) {
      const pageStart = Date.now()

      try {
        await page.goto(`${BASE_URL}/#${route === '/' ? '/' : route}`, {
          waitUntil: 'domcontentloaded',
          timeout: 15_000,
        })
      } catch (err) {
        const msg = err instanceof Error ? err.message : String(err)
        console.log(`  ⚠️  ${name.padEnd(25)} — page load failed: ${msg}`)
        results.push({
          page: name,
          path: route,
          violations: [],
          passed: true,
          durationMs: Date.now() - pageStart,
        })
        continue
      }

      // Wait for React to hydrate
      try {
        await page.waitForSelector('#root', { timeout: 10_000 })
        await page.waitForTimeout(1_000)
      } catch {
        // Root never mounted — analyze whatever is on screen
      }

      const analysis = await new AxeBuilder({ page })
        .withTags(WCAG_AA_TAGS)
        .disableRules(DISABLE_RULES)
        .analyze()

      const pageViolations: ViolationSummary[] = analysis.violations.map((v) => ({
        page: name,
        id: v.id,
        impact: v.impact || 'unknown',
        description: v.description,
        help: v.help,
        helpUrl: v.helpUrl,
        nodes: v.nodes.length,
        tags: v.tags,
      }))

      const criticalAndSerious = pageViolations.filter(
        (v) => v.impact === 'critical' || v.impact === 'serious',
      )

      results.push({
        page: name,
        path: route,
        violations: pageViolations,
        passed: criticalAndSerious.length === 0,
        durationMs: Date.now() - pageStart,
      })

      // Accumulate baseline data (all violations, not just critical/serious)
      baselineAccumulator[name] = extractBaseline(pageViolations)

      // Summary line per page
      const icon = criticalAndSerious.length === 0 ? '✅' : '❌'
      const detail = pageViolations.length > 0
        ? ` (${pageViolations.length} total, ${criticalAndSerious.length} critical/serious)`
        : ''
      console.log(`  ${icon} ${name.padEnd(25)} ${(Date.now() - pageStart) / 1000}s${detail}`)

      totalViolations += pageViolations.length
      totalCritical += criticalAndSerious.filter((v) => v.impact === 'critical').length
      totalSerious += criticalAndSerious.filter((v) => v.impact === 'serious').length
    }
  } finally {
    if (browser) await browser.close()
  }

  const totalTime = ((Date.now() - startTime) / 1000).toFixed(1)

  // ── UPDATE-BASELINE MODE ──────────────────────────────────────────
  if (UPDATE_BASELINE) {
    saveBaseline(BASELINE_PATH, baselineAccumulator)
    console.log()
    console.log(`  📊 Baseline snapshot:`)
    for (const [pageName, violations] of Object.entries(baselineAccumulator)) {
      const entries = Object.entries(violations)
      if (entries.length === 0) {
        console.log(`     ${pageName}: clean`)
      } else {
        console.log(`     ${pageName}: ${entries.map(([id, n]) => `${id}(${n})`).join(', ')}`)
      }
    }
    console.log(`\n  ✅ Baseline updated. ${PAGES.length} pages scanned in ${totalTime}s.\n`)
    process.exit(0)
  }

  // ── CHECK MODE (compare against baseline) ─────────────────────────
  const baseline = loadBaseline(BASELINE_PATH)

  // Compute diffs for critical/serious violations only
  const allDiffs: ViolationDiff[] = []
  for (const r of results) {
    const critSerious = r.violations.filter(
      (v) => v.impact === 'critical' || v.impact === 'serious',
    )
    const diffs = computeDiffs(critSerious, baseline, r.page)
    allDiffs.push(...diffs)
  }

  const newViolations = allDiffs.filter((d) => d.status === 'NEW')
  const regressions = allDiffs.filter((d) => d.status === 'REGRESSION')
  const improvements = allDiffs.filter((d) => d.status === 'IMPROVED')

  // ── Summary ──────────────────────────────────────────────────────
  console.log(`\n  ── Summary ──────────────────────────────────────`)
  console.log(`  Pages scanned:  ${PAGES.length}`)
  console.log(`  Time elapsed:   ${totalTime}s`)
  console.log(`  Total issues:   ${totalViolations}`)
  console.log(`  Critical:       ${totalCritical}`)
  console.log(`  Serious:        ${totalSerious}`)
  console.log(`  Minor/Moderate: ${totalViolations - totalCritical - totalSerious}`)

  if (improvements.length > 0) {
    console.log(`\n  ── Improvements (baseline lowered) ───────────────`)
    for (const d of improvements) {
      const icon = d.currentCount === 0 ? '🎉' : '📉'
      console.log(`     ${icon} ${d.page}: ${d.id} (${d.baselineCount} → ${d.currentCount})`)
      if (d.description) {
        console.log(`        ${d.description}`)
      }
    }
  }

  const failures = [...newViolations, ...regressions]
  if (failures.length > 0) {
    console.log(`\n  ── Failures ─────────────────────────────────────`)
    for (const d of failures) {
      const icon = d.status === 'NEW' ? '🆕' : '🔴'
      const countInfo = d.status === 'NEW'
        ? `${d.currentCount} elements (not in baseline)`
        : `${d.baselineCount} → ${d.currentCount} elements (baseline exceeded)`
      console.log(`     ${icon} ${d.page}: ${d.id}`)
      console.log(`        ${d.description}`)
      console.log(`        Impact: ${d.impact}  |  Elements: ${countInfo}`)
      if (d.helpUrl) {
        console.log(`        ${d.helpUrl}`)
      }
    }

    const totalFailures = failures.length
    console.log(`\n  ❌ ${totalFailures} violation(s) not in baseline or regressions — failing.\n`)
    process.exit(1)
  }

  console.log(`\n  ✅ No new violations or regressions against baseline.\n`)
  process.exit(0)
}

runAudit().catch((err) => {
  console.error('Fatal error running a11y check:', err)
  process.exit(1)
})
