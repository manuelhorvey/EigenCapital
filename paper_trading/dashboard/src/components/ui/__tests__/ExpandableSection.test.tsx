import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import ExpandableSection from '../ExpandableSection'

describe('ExpandableSection', () => {
  beforeEach(() => {
    localStorage.clear()
  })

  it('renders title and children', () => {
    render(<ExpandableSection title="Test Section"><p>content</p></ExpandableSection>)
    expect(screen.getByText('Test Section')).toBeInTheDocument()
    expect(screen.getByText('content')).toBeInTheDocument()
  })

  it('starts collapsed by default', () => {
    render(<ExpandableSection title="Test"><p>content</p></ExpandableSection>)
    const region = document.querySelector('[role="region"]')
    expect(region).toBeInTheDocument()
    expect(region?.className).toContain('max-h-0')
    expect(region?.className).toContain('opacity-0')
  })

  it('starts open when defaultOpen=true', () => {
    render(<ExpandableSection title="Test" defaultOpen><p>content</p></ExpandableSection>)
    const region = document.querySelector('[role="region"]')
    expect(region?.className).toContain('max-h-[9999px]')
    expect(region?.className).toContain('opacity-100')
  })

  it('toggles open/closed on click', () => {
    render(<ExpandableSection title="Test"><p>content</p></ExpandableSection>)
    const button = screen.getByRole('button', { name: /test/i })
    
    expect(button).toHaveAttribute('aria-expanded', 'false')
    fireEvent.click(button)
    expect(button).toHaveAttribute('aria-expanded', 'true')
    
    const region = document.querySelector('[role="region"]')
    expect(region?.className).toContain('max-h-[9999px]')
    
    fireEvent.click(button)
    expect(button).toHaveAttribute('aria-expanded', 'false')
    expect(region?.className).toContain('max-h-0')
  })

  it('persists state to localStorage when storageKey is provided', () => {
    const key = 'test-section'
    render(<ExpandableSection title="Test" storageKey={key}><p>content</p></ExpandableSection>)
    
    // Toggle open - should write to localStorage
    fireEvent.click(screen.getByRole('button'))
    expect(localStorage.getItem(`expand_${key}`)).toBe('true')
    
    // Toggle closed
    fireEvent.click(screen.getByRole('button'))
    expect(localStorage.getItem(`expand_${key}`)).toBe('false')
  })

  it('restores open state from localStorage', () => {
    const key = 'test-restore'
    localStorage.setItem(`expand_${key}`, 'true')
    
    render(<ExpandableSection title="Test" storageKey={key}><p>content</p></ExpandableSection>)
    const button = screen.getByRole('button')
    expect(button).toHaveAttribute('aria-expanded', 'true')
  })

  it('renders badge when provided', () => {
    render(<ExpandableSection title="Test" badge={<span data-testid="badge">5 items</span>}><p>content</p></ExpandableSection>)
    expect(screen.getByTestId('badge')).toBeInTheDocument()
    expect(screen.getByText('5 items')).toBeInTheDocument()
  })

  it('wires aria-controls between button and content region', () => {
    render(<ExpandableSection title="Test"><p>content</p></ExpandableSection>)
    const button = screen.getByRole('button')
    const region = document.querySelector('[role="region"]')
    
    expect(button).toHaveAttribute('aria-controls')
    expect(region).toHaveAttribute('id')
    expect(button.getAttribute('aria-controls')).toBe(region?.getAttribute('id'))
  })

  it('renders ChevronDown icon with open/close state', () => {
    render(<ExpandableSection title="Test"><p>content</p></ExpandableSection>)
    const button = screen.getByRole('button')
    const svg = button.querySelector('svg')
    expect(svg).toBeInTheDocument()
    expect(button).toHaveAttribute('aria-expanded', 'false')
    
    fireEvent.click(button)
    expect(button).toHaveAttribute('aria-expanded', 'true')
  })

  it('handles localStorage error gracefully', () => {
    const key = 'test-error'
    const setItemSpy = vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
      throw new Error('storage full')
    })
    
    render(<ExpandableSection title="Test" storageKey={key}><p>content</p></ExpandableSection>)
    fireEvent.click(screen.getByRole('button'))
    // Should not throw
    expect(screen.getByText('Test')).toBeInTheDocument()
    
    setItemSpy.mockRestore()
  })

  it('applies custom className', () => {
    const { container } = render(<ExpandableSection title="Test" className="custom-class"><p>content</p></ExpandableSection>)
    const outer = container.firstElementChild
    expect(outer?.className).toContain('custom-class')
  })
})
