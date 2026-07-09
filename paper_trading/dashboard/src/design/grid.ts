// ── EigenCapital Responsive Grid System ────────────────────────────
//
// Single source of truth for all responsive breakpoints, column grids,
// and spacing roles used across the dashboard.
//
// ── Breakpoint Philosophy ──────────────────────────────────────────
//
//        Name     Min-width  Intent
//        ──────── ─────────  ─────────────────────────────────
//        mobile   0          Essential KPIs only — 4 metrics max
//        tablet   640px      Near-full density, stacked layout
//        laptop   1024px     Full work surface, 2-column splits
//        desktop  1440px     Full work surface, 3-column splits
//        ultrawide 1920px    Expanded, multi-column layouts
//
// Three breakpoints between mobile and ultrawide — not more — because
// each maps to a real operator workflow: phone glance (mobile),
// laptop lid-open (tablet), docked monitor (laptop/desktop), and
// trading station (ultrawide). Adding more creates ambiguity.
//
// ── Grid Strategy ──────────────────────────────────────────────────
//
// - 12-column grid at every breakpoint. What changes is *column
//   occupancy*, not the column count.
// - Components on desktop keep their 12-col math; on smaller screens
//   they span more columns, never reorder their source.
// - Two-column splits are desktop-only (lg:). On tablet, cards stack
//   vertically — never 50/50 split.
// - Data-dense tables → card-list transformation on mobile (sm:hidden).
//
// ── Spacing Roles ──────────────────────────────────────────────────
//
//   section       8 (32px)    Between major sections on a page
//   cardCluster   6 (24px)    Between grouped cards
//   cardInternal  4 (16px)    Inside a card, between logical groups
//   metricCluster 3 (12px)    Between metrics in a cluster
//   metricInternal 2 (8px)    Inside a metric block
//   tight         1.5 (6px)   Very tight spacing (badges, chips)
// ──────────────────────────────────────────────────────────────────

/** Breakpoint definitions — Tailwind-compatible min-widths in px. */
export const BREAKPOINTS = {
  mobile: 0,
  tablet: 640,
  laptop: 1024,
  desktop: 1440,
  ultrawide: 1920,
} as const

export type BreakpointName = keyof typeof BREAKPOINTS

/** Tailwind breakpoint prefixes used in responsive class strings. */
export const BP_PREFIX: Record<BreakpointName, string> = {
  mobile: '',         // default (no prefix)
  tablet: 'sm:',      // 640px
  laptop: 'lg:',      // 1024px
  desktop: 'xl:',     // 1440px
  ultrawide: '2xl:',  // 1920px
}

/**
 * Standardized grid column class generators.
 * Returns a Tailwind class string like "grid-cols-1 lg:grid-cols-2 xl:grid-cols-3"
 */

/** Two-column split (sidebar + main, or pair of panels). Desktop-only split. */
export function gridSplit2(ultrawide = false): string {
  return `grid-cols-1 lg:grid-cols-2${ultrawide ? ' 2xl:grid-cols-2' : ''}`
}

/** Three-column layout (dashboard overview). Desktop+. */
export function gridSplit3(ultrawide = false): string {
  return `grid-cols-1 lg:grid-cols-3${ultrawide ? ' xl:grid-cols-3' : ''}`
}

/** Four-column metric row. Tablet 2-col, laptop 4-col. */
export function gridMetric4(): string {
  return 'grid-cols-2 lg:grid-cols-4'
}

/** Six-column dense metric row. Tablet 3-col, laptop 4-col, desktop 6-col. */
export function gridMetric6(): string {
  return 'grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 xl:grid-cols-6'
}

/** Seven-column wide metric row (quick stats). Tablet 2-col, desktop 7-col. */
export function gridMetric7(): string {
  return 'grid-cols-2 lg:grid-cols-7'
}

/** Asset card grid — 2-col mobile, 3-col tablet, 4-col laptop. */
export function gridCards(): string {
  return 'grid-cols-2 md:grid-cols-3 lg:grid-cols-4'
}

/** Page content container — responsive width with max constraints. */
export const PAGE_CONTAINER = 'w-full max-w-[1440px] 2xl:max-w-[1920px] mx-auto'

/** Main content area padding. */
export const PAGE_PADDING = 'px-4 sm:px-7 py-5 sm:py-7'

/** Section spacing between major page blocks. */
export const SECTION_SPACING = 'space-y-7 sm:space-y-10'

/** Card grid gap — gives every side-by-side panel visible breathing room. */
export const GRID_GAP = 'gap-5 sm:gap-6 lg:gap-7'

/** Wide card gap (alias of GRID_GAP — kept for semantic clarity at call sites). */
export const GRID_GAP_WIDE = GRID_GAP

/**
 * Converts gap role number to Tailwind `gap-{n}` string.
 * Maps from the `gapRoles` tokens in color-system.ts.
 */
export function gapClass(role: number): string {
  const roleStr = role.toString().replace('.', '_')
  return `gap-${roleStr}`
}
