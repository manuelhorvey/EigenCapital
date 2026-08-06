import {
  LayoutDashboard,
  TrendingUp,
  Zap,
  BarChart3,
  Shield,
  Activity,
  History,
  LineChart,
} from 'lucide-react'
import type { LucideIcon } from 'lucide-react'

/**
 * Single source of truth for application navigation.
 *
 * All navigation surfaces (Sidebar, TabBar, CommandPalette, global `g`-nav
 * shortcuts) derive from this one registry so a route change is a single edit.
 * Previously the route list was duplicated across four files and had already
 * drifted apart (e.g. the /execution description differed between surfaces).
 */

export interface NavItem {
  /** Stable route id, also used as the `g`-nav shortcut id target. */
  id: string
  to: string
  label: string
  /** Short description shown under the label in the sidebar / palette. */
  desc: string
  icon: LucideIcon
  /**
   * Badge counter key, defined by the alert system. `trading` and `risk` are
   * the two badge families the sidebar/tab-bar render today.
   */
  badgeKey?: 'trading' | 'risk'
  /** The key pressed after `g` to navigate (mnemonic; kept stable). */
  shortcut?: string
  /** Flat-surface sort order (TabBar / palette) — not the sidebar grouping. */
  order: number
}

export interface NavGroup {
  title: string
  icon: LucideIcon
  items: NavItem[]
}

export const NAV_GROUPS: NavGroup[] = [
  {
    title: 'Overview',
    icon: LayoutDashboard,
    items: [
      {
        id: 'overview',
        to: '/overview',
        label: 'Overview',
        desc: 'KPIs + portfolio + asset grid',
        icon: LayoutDashboard,
        shortcut: 'o',
        order: 1,
      },
    ],
  },
  {
    title: 'Live Market',
    icon: TrendingUp,
    items: [
      {
        id: 'trading',
        to: '/trading',
        label: 'Trading',
        desc: 'Signals, equity, live Sharpe',
        icon: Zap,
        badgeKey: 'trading',
        shortcut: 't',
        order: 2,
      },
      {
        id: 'trades',
        to: '/trades',
        label: 'Trades',
        desc: 'Outcomes, journal, execution log',
        icon: History,
        shortcut: 'a',
        order: 3,
      },
    ],
  },
  {
    title: 'Risk',
    icon: Shield,
    items: [
      {
        id: 'risk',
        to: '/risk',
        label: 'Risk',
        desc: 'PEK, exposures, governance, halt',
        icon: Shield,
        badgeKey: 'risk',
        shortcut: 'r',
        order: 5,
      },
      {
        id: 'monitor',
        to: '/monitor',
        label: 'Monitor',
        desc: 'Alerts, health, engine liveness',
        icon: Activity,
        shortcut: 'm',
        order: 6,
      },
    ],
  },
  {
    title: 'Execution',
    icon: BarChart3,
    items: [
      {
        id: 'execution',
        to: '/execution',
        label: 'Execution',
        desc: 'Quality, attribution, optimizer',
        icon: BarChart3,
        shortcut: 'h',
        order: 4,
      },
    ],
  },
  {
    title: 'Research',
    icon: LineChart,
    items: [
      {
        id: 'analytics',
        to: '/analytics',
        label: 'Analytics',
        desc: 'Statistical + calibration',
        icon: LineChart,
        shortcut: 'n',
        order: 7,
      },
    ],
  },
]

/** Flat list in sidebar group order (used for arrow-key navigation there). */
export const SIDEBAR_NAV_ITEMS: NavItem[] = NAV_GROUPS.flatMap(g => g.items)

/** Flat list in flat-surface display order (TabBar / command palette). */
export const NAV_ITEMS: NavItem[] = [...SIDEBAR_NAV_ITEMS].sort((a, b) => a.order - b.order)

/** `g`-nav lookup keyed by mnemonic letter, derived from the registry. */
export const SHORTCUT_TO_ROUTE: Record<string, string> = Object.fromEntries(
  NAV_ITEMS.filter(n => n.shortcut).map(n => [n.shortcut!, n.to]),
)

/** Human-readable list of `g`-nav shortcuts, e.g. "o/t/a/h/r/m/n". */
export const SHORTCUT_SUMMARY: string = NAV_ITEMS.filter(n => n.shortcut)
  .map(n => n.shortcut)
  .join('/')