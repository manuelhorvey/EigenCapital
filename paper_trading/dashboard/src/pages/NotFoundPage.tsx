import { useNavigate } from 'react-router-dom'
import { FileSearch, Home } from 'lucide-react'
import Button from '../components/ui/Button'

/**
 * 404 Not Found page.
 * Shown when the user navigates to an unrecognised route.
 */
export default function NotFoundPage() {
  const navigate = useNavigate()

  return (
    <div className="min-h-[60vh] flex flex-col items-center justify-center gap-6 px-6 animate-fade-in">
      <div className="w-16 h-16 rounded-xl panel flex items-center justify-center">
        <FileSearch className="w-8 h-8 text-tertiary/60" strokeWidth={1.25} />
      </div>

      <div className="text-center max-w-md">
        <h1 className="text-3xl font-bold text-primary tracking-tight">404</h1>
        <p className="text-sm text-tertiary mt-2 leading-relaxed">
          This page doesn't exist. It may have been moved, renamed, or never existed.
        </p>
      </div>

      <div className="flex items-center gap-3">
        <Button
          variant="primary"
          onClick={() => navigate('/')}
          icon={<Home className="w-3.5 h-3.5" strokeWidth={2} />}
        >
          Back to Dashboard
        </Button>
      </div>
    </div>
  )
}
