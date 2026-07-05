import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, cleanup } from '@testing-library/react'
import Modal from '../Modal'

vi.mock('../../../hooks/useFocusTrap', () => ({
  default: () => ({ current: document.createElement('div') }),
}))

describe('Modal', () => {
  const onClose = vi.fn()

  beforeEach(() => {
    onClose.mockReset()
    document.body.style.overflow = ''
  })

  it('renders content when open', () => {
    render(<Modal open onClose={onClose} title="Test"><p>body</p></Modal>)
    expect(screen.getByText('body')).toBeInTheDocument()
    expect(screen.getByRole('dialog')).toBeInTheDocument()
  })

  it('returns null when closed', () => {
    render(<Modal open={false} onClose={onClose} title="Test"><p>body</p></Modal>)
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
    expect(screen.queryByText('body')).not.toBeInTheDocument()
  })

  it('renders title and description', () => {
    render(<Modal open onClose={onClose} title="My Title" description="My desc"><p>body</p></Modal>)
    expect(screen.getByText('My Title')).toBeInTheDocument()
    expect(screen.getByText('My desc')).toBeInTheDocument()
  })

  it('wires aria attributes from title and description', () => {
    render(<Modal open onClose={onClose} title="My Title" description="My desc"><p>body</p></Modal>)
    const dialog = screen.getByRole('dialog')
    expect(dialog).toHaveAttribute('aria-modal', 'true')
    expect(dialog).toHaveAttribute('aria-label', 'My Title')
    expect(dialog).toHaveAttribute('aria-labelledby', 'modal-title')
    expect(dialog).toHaveAttribute('aria-describedby', 'modal-description')
  })

  it('close button calls onClose', () => {
    render(<Modal open onClose={onClose} title="Test"><p>body</p></Modal>)
    fireEvent.click(screen.getByLabelText('Close modal'))
    expect(onClose).toHaveBeenCalledOnce()
  })

  it('Escape key calls onClose', () => {
    render(<Modal open onClose={onClose} title="Test"><p>body</p></Modal>)
    fireEvent.keyDown(window, { key: 'Escape' })
    expect(onClose).toHaveBeenCalledOnce()
  })

  it('overlay click calls onClose by default', () => {
    render(<Modal open onClose={onClose} title="Test"><p>body</p></Modal>)
    // the overlay is the fixed inset-0 bg-black/60 div
    const overlay = document.querySelector('.fixed.inset-0.bg-black\\/60')
    expect(overlay).toBeTruthy()
    if (overlay) fireEvent.click(overlay)
    expect(onClose).toHaveBeenCalled()
  })

  it('overlay click does NOT call onClose when closeOnOverlay=false', () => {
    render(<Modal open onClose={onClose} title="Test" closeOnOverlay={false}><p>body</p></Modal>)
    const overlay = document.querySelector('.fixed.inset-0.bg-black\\/60')
    if (overlay) fireEvent.click(overlay)
    expect(onClose).not.toHaveBeenCalled()
  })

  it('renders footer when provided', () => {
    render(<Modal open onClose={onClose} title="Test" footer={<button>OK</button>}><p>body</p></Modal>)
    expect(screen.getByText('OK')).toBeInTheDocument()
  })

  it('hides header when showHeader=false', () => {
    render(<Modal open onClose={onClose} title="Test" showHeader={false}><p>body</p></Modal>)
    expect(screen.queryByText('Test')).not.toBeInTheDocument()
  })

  it('sets body scroll lock on open and restores on close', () => {
    const { unmount } = render(<Modal open onClose={onClose} title="Test"><p>body</p></Modal>)
    expect(document.body.style.overflow).toBe('hidden')
    unmount()
    expect(document.body.style.overflow).toBe('')
  })

  it('does not lock scroll when bodyScrollLock=false', () => {
    render(<Modal open onClose={onClose} title="Test" bodyScrollLock={false}><p>body</p></Modal>)
    expect(document.body.style.overflow).not.toBe('hidden')
  })

  it('renders the correct size class', () => {
    const { container, rerender } = render(<Modal open onClose={onClose} title="Test" size="sm"><p>body</p></Modal>)
    expect(container.innerHTML).toContain('max-w-md')
    rerender(<Modal open onClose={onClose} title="Test" size="xl"><p>body</p></Modal>)
    expect(container.innerHTML).toContain('max-w-4xl')
  })

  it('noContentWrap renders children directly without header/body wrapper', () => {
    render(<Modal open onClose={onClose} title="Test" noContentWrap><div data-testid="direct">direct</div></Modal>)
    expect(screen.getByTestId('direct')).toBeInTheDocument()
    // Header is not rendered in noContentWrap mode
    expect(screen.queryByText('Test')).not.toBeInTheDocument()
  })
})
