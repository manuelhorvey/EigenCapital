import { useRef, useState, useCallback } from 'react'
import App from './App'
import HeroReveal from './components/HeroReveal'
import FeatureCards from './components/FeatureCards'
import EnterButton from './components/EnterButton'

export default function LandingPage() {
  const [entered, setEntered] = useState(false)
  const overlayRef = useRef<HTMLDivElement>(null)
  const featuresRef = useRef<HTMLDivElement>(null)
  const transitioning = useRef(false)

  const handleEnter = useCallback(async () => {
    if (transitioning.current) return
    transitioning.current = true

    let gsap: any
    try {
      // @ts-ignore - dynamic CDN import
      const mod = await import('https://cdn.jsdelivr.net/npm/gsap')
      gsap = mod.default || mod
    } catch {
      setEntered(true)
      transitioning.current = false
      return
    }

    const tl = gsap.timeline({
      onComplete: () => {
        setEntered(true)
        transitioning.current = false
      },
    })

    if (overlayRef.current) {
      tl.to(overlayRef.current, { opacity: 0, duration: 0.6, ease: 'power2.inOut' }, 0)
    }

    if (featuresRef.current) {
      tl.to(featuresRef.current, { opacity: 0, y: 60, duration: 0.4, ease: 'power2.in' }, 0.2)
    }
  }, [])

  if (entered) {
    return <App />
  }

  return (
    <div className="bg-gray-950">
      <div className="relative h-screen overflow-hidden">
        <div className="pointer-events-none h-full">
          <App />
        </div>
        <div ref={overlayRef} className="absolute inset-0 z-20">
          <HeroReveal />
        </div>
      </div>
      <div ref={featuresRef}>
        <FeatureCards />
        <EnterButton onClick={handleEnter} />
      </div>
    </div>
  )
}
