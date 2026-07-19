/**
 * EigenCapital Motion System — Production Motion Design Tokens
 *
 * Three tiers of motion:
 *   1. Micro-interactions (hover/active) — 100-150ms, spring-like ease-out
 *   2. Presence transitions (enter/exit) — 200-350ms, overshoot-spring for emphasis
 *   3. Data transitions — 400-600ms, smooth ease-out for value changes
 *
 * All durations respect prefers-reduced-motion via the global CSS override.
 *
 * Spring-like cubic-bezier curves:
 *   spring-bouncy:  (0.34, 1.56, 0.64, 1)  — overshoot spring for sidebar/modal entrance
 *   spring-smooth:  (0.16, 1, 0.3, 1)       — smooth ease-out with subtle anticipation
 *   spring-subtle:  (0.25, 0.46, 0.45, 0.94) — deceleration curve for hover exit
 *   spring-snappy:  (0.22, 1, 0.36, 1)       — fast, natural settling
 */

export const SPRING = {
  bouncy: 'cubic-bezier(0.34, 1.56, 0.64, 1)' as const,
  smooth: 'cubic-bezier(0.16, 1, 0.3, 1)' as const,
  subtle: 'cubic-bezier(0.25, 0.46, 0.45, 0.94)' as const,
  snappy: 'cubic-bezier(0.22, 1, 0.36, 1)' as const,
} as const

export const MOTION = {
  duration: {
    micro: 100,
    interaction: 150,
    normal: 200,
    slow: 300,
    data: 500,
  },
  ease: {
    micro: 'ease-out',
    interaction: 'ease-out',
    presence: 'ease-out',
    data: 'ease-out',
    spring: SPRING,
  },
  className: {
    /** Base transition token — use on all interactive elements */
    interactive: 'transition-all duration-150 ease-out',
    /** Color-only transitions (background, text, border) */
    color: 'transition-colors duration-150 ease-out',
    /** Transform transitions (scale, translate) */
    transform: 'transition-transform duration-150 ease-out',
    /** Combined hover + active micro-interaction */
    button: [
      'transition-all duration-150 ease-out',
      'hover:brightness-110',
      'active:scale-[0.97] active:brightness-95',
    ].join(' '),
    /** Card/panel hover with lift + border highlight */
    card: [
      'transition-all duration-200 ease-out',
      'hover:border-strong hover:shadow-card hover:-translate-y-0.5',
      'active:scale-[0.98]',
    ].join(' '),
    /** Data-driven value transitions */
    data: 'transition-all duration-500 ease-out',
    /** Presence animations (fade/slide in) */
    presence: 'animate-fade-in',
    /** Sidebar slide with over-shoot spring */
    sidebar: [
      'transform transition-transform duration-300',
      `ease-[${SPRING.bouncy}]`,
    ].join(' '),
    /** Modal/dialog entrance */
    modal: [
      'transition-all duration-200',
      `ease-[${SPRING.snappy}]`,
    ].join(' '),
  },
} as const

export type MotionToken = keyof typeof MOTION.className
