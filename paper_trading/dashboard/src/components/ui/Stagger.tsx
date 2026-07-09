import { Children, isValidElement, cloneElement, type ReactElement, type ReactNode } from 'react'

interface StaggerProps {
  children: ReactNode
  /** Base delay increment between each child, in ms. Default 45. */
  staggerMs?: number
  /** Initial delay before the first child, in ms. Default 0. */
  initialDelay?: number
  as?: 'div' | 'section' | 'article'
  className?: string
}

/**
 * Auto-staggers EntranceAnimator children by assigning cascading delays.
 * Eliminates manual `delay={30}` `delay={60}` patterns in workspace pages.
 *
 * Usage:
 *   <Stagger staggerMs={45}>
 *     <EntranceAnimator variant="fade-up"><Panel>…</Panel></EntranceAnimator>
 *     <EntranceAnimator variant="fade-up"><Panel>…</Panel></EntranceAnimator>
 *     <EntranceAnimator variant="fade-up"><Panel>…</Panel></EntranceAnimator>
 *   </Stagger>
 *
 * The 3 children receive delays 0, 45, 90 automatically.
 */
export default function Stagger({
  children,
  staggerMs = 45,
  initialDelay = 0,
  as: Tag = 'div',
  className = '',
}: StaggerProps) {
  const elements = Children.toArray(children).filter(isValidElement)

  return (
    <Tag className={className}>
      {elements.map((child, i) => {
        if (!isValidElement(child)) return child

        const delay = initialDelay + i * staggerMs

        // Preserve explicit delay if child already has one (e.g. EntranceAnimator delay={100})
        const childDelay = (child.props as Record<string, unknown>).delay
        const resolvedDelay = childDelay !== undefined ? (childDelay as number) : delay

        return cloneElement(child as ReactElement<{ delay?: number }>, {
          delay: resolvedDelay,
        })
      })}
    </Tag>
  )
}
