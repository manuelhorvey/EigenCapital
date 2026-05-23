import { usePortfolioState } from '../hooks/usePortfolioState'

export default function Footer() {
  const { data } = usePortfolioState()
  const p = data?.portfolio
  const startDate = p?.start_date
  const gateDate = startDate ? new Date(new Date(startDate).getTime() + 180 * 86400000) : null

  return (
    <footer className="border-t border-default glass glass-border mt-auto">
      <div className="max-w-[90rem] mx-auto px-4 sm:px-6 py-2.5 flex flex-wrap items-center justify-between gap-3 text-[10px] text-tertiary">
        <span>
          Next retrain{' '}
          <span className="text-secondary font-medium font-mono">
            Jan 1, {new Date().getFullYear() + 1}
          </span>
        </span>
        <div className="flex flex-wrap items-center gap-4 font-mono">
          <span>
            Started{' '}
            <span className="text-secondary">
              {startDate
                ? new Date(startDate).toLocaleDateString('en-US', {
                    month: 'short',
                    day: 'numeric',
                    year: 'numeric',
                  })
                : '—'}
            </span>
          </span>
          <span>
            Gate{' '}
            <span className="text-secondary">
              {gateDate
                ? gateDate.toLocaleDateString('en-US', {
                    month: 'short',
                    day: 'numeric',
                    year: 'numeric',
                  })
                : '—'}
            </span>
          </span>
          <span>
            Cleared{' '}
            <span className={p?.deployment_cleared ? 'text-gov-green font-semibold' : 'text-gov-yellow font-semibold'}>
              {p?.deployment_cleared ? 'Yes' : 'No'}
            </span>
          </span>
        </div>
      </div>
    </footer>
  )
}
