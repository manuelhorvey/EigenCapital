import { useEffect, useState } from 'react'

const NAV_SECTIONS = [
  { id: 'portfolio', label: 'Portfolio' },
  { id: 'signals', label: 'Signals' },
  { id: 'execution', label: 'Execution' },
  { id: 'trades', label: 'Trades' },
  { id: 'risk', label: 'Risk' },
]

export default function AnchorNav() {
  const [active, setActive] = useState('portfolio')
  const [scrolled, setScrolled] = useState(false)

  useEffect(() => {
    const observer = new IntersectionObserver(
      entries => {
        for (const entry of entries) {
          if (entry.isIntersecting) setActive(entry.target.id)
        }
      },
      { rootMargin: '-80px 0px -60% 0px', threshold: 0 },
    )

    for (const { id } of NAV_SECTIONS) {
      const el = document.getElementById(id)
      if (el) observer.observe(el)
    }

    return () => observer.disconnect()
  }, [])

  useEffect(() => {
    const onScroll = () => setScrolled(window.scrollY > 60)
    window.addEventListener('scroll', onScroll, { passive: true })
    return () => window.removeEventListener('scroll', onScroll)
  }, [])

  return (
    <nav
      className={`sticky top-[45px] z-20 bg-app/80 backdrop-blur-md border-b transition-shadow duration-200 ${
        scrolled ? 'border-default shadow-[0_1px_0_rgba(255,255,255,0.03)]' : 'border-default/40'
      }`}
    >
      <div className="max-w-[90rem] mx-auto px-4 sm:px-7 flex items-center gap-0 overflow-x-auto scrollbar-none">
        {NAV_SECTIONS.map(({ id, label }) => (
          <a
            key={id}
            href={`#${id}`}
            onClick={e => {
              e.preventDefault()
              document.getElementById(id)?.scrollIntoView({ behavior: 'smooth' })
            }}
            className={`shrink-0 px-3 py-2 text-2xs font-medium transition-all duration-150 border-b-2 ${
              active === id
                ? 'text-primary border-accent-emerald'
                : 'text-tertiary border-transparent hover:text-secondary hover:border-default/40'
            }`}
          >
            {label}
          </a>
        ))}
      </div>
    </nav>
  )
}
