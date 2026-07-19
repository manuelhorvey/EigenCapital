/**
 * <Modal /> — single primitive for all operator-console in-app dialogs.
 *
 * Encapsulates:
 *  - backdrop + content scroll lock
 *  - Escape closes via props.onClose
 *  - click-out closes via props.onClose (configurable via
 *    `closeOnOverlay` prop)
 *  - focus trap via useFocusTrap on the inner content
 *  - role="dialog" aria-modal="true" aria-label=<title>
 *  - width ladder via `size` prop (sm/md/lg/xl) — defaults to lg
 *
 * Optional header rendering:
 *  - title + close-X when `showHeader` (default true)
 *  - titleId / descriptionId are wired to aria-labelledby / aria-describedby
 *  - bodyScrollLock prop (default true) toggles the document-overflow
 *    setting required for the modal overlay to work without scroll bleed
 *
 * `children` are mounted inside the body region. The `<Modal>` returns
 * null when `open` is false; reactivity downstream is preserved.
 *
 * Replaces per-modal chrome duplicated across SystemHealthModal,
 * WeeklyReviewModal, TradeInspectorModal (Commit 4.3 retrofit).
 */
import {
  useEffect,
  useRef,
  type ReactNode,
} from 'react'
import { X } from 'lucide-react'
import useFocusTrap from '../../hooks/useFocusTrap'
import { Skeleton } from './Skeleton'

export type ModalSize = 'sm' | 'md' | 'lg' | 'xl'

const SIZE_TO_MAX: Record<ModalSize, string> = {
  sm: 'max-w-md',
  md: 'max-w-xl',
  lg: 'max-w-2xl',
  xl: 'max-w-4xl',
}

// ── Modal stack tracking ─────────────────────────────────────────
// Each open modal increments a global counter so stacked modals get
// increasing z-index values instead of all fighting at z-50.
// (Audit finding F9: modal stacking)

let _stackDepth = 0

export function useRegisterModal(open: boolean): number {
  const depthRef = useRef(0)

  useEffect(() => {
    if (!open) {
      if (depthRef.current > 0) {
        _stackDepth = Math.max(0, _stackDepth - 1)
        depthRef.current = 0
      }
      return
    }

    // Register: increment stack depth. The z-index is captured once
    // on mount and remains stable for the modal's lifetime — modals
    // opened later get higher z-index values automatically.
    _stackDepth += 1
    depthRef.current = _stackDepth

    return () => {
      if (depthRef.current > 0) {
        _stackDepth = Math.max(0, _stackDepth - 1)
        depthRef.current = 0
      }
    }
  }, [open])

  // z-index formula: base 50 + stack_depth ensures each modal sits
  // above the previous one.
  return 50 + depthRef.current
}

export interface ModalProps {
  open: boolean
  onClose: () => void
  /** Visible title rendered in the header and exposed to AT. */
  title?: string
  /** Sub-title below title (rendered in the header). */
  description?: string
  /** Body is mounted inside the scrollable dialog region. */
  children: ReactNode
  /** Optional footer rendered below the scrollable body. */
  footer?: ReactNode
  /** Size tier; defaults to lg. */
  size?: ModalSize
  /** Close when clicking outside the dialog. Default true. */
  closeOnOverlay?: boolean
  /** Enable body scroll lock while open. Default true. */
  bodyScrollLock?: boolean
  /** Render the title + close-X header. Default true. */
  showHeader?: boolean
  /** Optional className for the inner dialog container. */
  className?: string
  /**
   * When true, children render directly as the dialog's flex content
   * (no scroll wrapper). Use when the consumer provides its own
   * header / tabs / scroll / footer layout. Default false.
   */
  noContentWrap?: boolean
}

export default function Modal({
  open,
  onClose,
  title,
  description,
  children,
  footer,
  size = 'lg',
  closeOnOverlay = true,
  bodyScrollLock = true,
  showHeader = true,
  className = '',
  noContentWrap = false,
}: ModalProps) {
  // focus trap owns its ref internally and tracks DOM lifecycle.
  const modalRef = useFocusTrap()

  // Escape to close
  useEffect(() => {
    if (!open) return
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [open, onClose])

  // Body scroll lock
  useEffect(() => {
    if (!open || !bodyScrollLock) return
    const prev = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    return () => {
      document.body.style.overflow = prev
    }
  }, [open, bodyScrollLock])

  // Modal stack: each open modal gets an increasing z-index (F9 fix)
  const zIndex = useRegisterModal(open)

  if (!open) return null

  const titleId = title ? 'modal-title' : undefined
  const descriptionId = description ? 'modal-description' : undefined
  const ariaLabelledby = titleId ? titleId : undefined
  const ariaDescribedby = descriptionId ? descriptionId : undefined

  const handleOverlayClick = closeOnOverlay ? onClose : undefined

  return (
    <div className="fixed inset-0 flex items-start justify-center pt-8 sm:pt-16 px-4" style={{ zIndex }}>
      <div
        className="fixed inset-0 bg-black/60"
        onClick={handleOverlayClick}
        aria-hidden="true"
      />
      <div
        ref={modalRef}
        className={
          'relative w-full ' +
          SIZE_TO_MAX[size] +
          ' bg-surface border border-default rounded shadow-modal animate-modal-open max-h-[85vh] flex flex-col ' +
          className
        }
        role="dialog"
        aria-modal="true"
        aria-label={title}
        aria-labelledby={ariaLabelledby}
        aria-describedby={ariaDescribedby}
      >
        {noContentWrap ? (
          children
        ) : (
          <>
            {showHeader && title && (
              <div className="flex items-center justify-between px-4 py-3 border-b border-default shrink-0">
                <div>
                  <h2 id={titleId} className="text-sm font-semibold text-primary">
                    {title}
                  </h2>
                  {description && (
                    <p
                      id={descriptionId}
                      className="text-2xs text-tertiary font-mono mt-0.5"
                    >
                      {description}
                    </p>
                  )}
                </div>
                <button
                  onClick={onClose}
                  aria-label="Close modal"
                  className="min-h-[44px] min-w-[44px] inline-flex items-center justify-center rounded-md hover:bg-panel border border-transparent hover:border-default transition-colors"
                >
                  <X className="w-3.5 h-3.5 text-tertiary" strokeWidth={2} />
                </button>
              </div>
            )}

            {/* Content */}
            <div className="flex-1 overflow-y-auto p-4 space-y-4">{children}</div>

            {footer && (
              <div className="flex items-center justify-end gap-2 px-4 py-3 border-t border-default bg-surface/50 shrink-0 rounded-b-xl">
                {footer}
              </div>
            )}
          </>
        )}
      </div>
    </div>
  )
}

export { Skeleton }
