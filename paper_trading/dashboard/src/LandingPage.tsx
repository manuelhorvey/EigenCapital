import { useState, useCallback, lazy, Suspense } from 'react'
import App from './App'
import ErrorBoundary from './components/ErrorBoundary'
import HeroReveal from './components/HeroReveal'
import EnterButton from './components/EnterButton'

const FeatureCards = lazy(() => import('./components/FeatureCards'))

export default function LandingPage() {
  const [entered, setEntered] = useState(false)

  const handleEnter = useCallback(() => {
    setEntered(true)
  }, [])

  if (entered) {
    return <ErrorBoundary><App /></ErrorBoundary>
  }

  return (
    <div className="bg-gray-950 min-h-screen">
      <HeroReveal />
      <Suspense fallback={null}>
        <FeatureCards />
      </Suspense>
      <EnterButton onClick={handleEnter} />
    </div>
  )
}
