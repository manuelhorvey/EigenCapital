import { useSystemSnapshot } from '../hooks/useSystemSnapshot'
import SignalsTable from '../components/SignalsTable'
import TradeOutcomes from '../components/TradeOutcomes'
import TradeFeed from '../components/TradeFeed'
import ExecutionFeed from '../components/ExecutionFeed'
import AdmissionPanel from '../components/AdmissionPanel'
import RejectedSignalExplorer from '../components/RejectedSignalExplorer'
import Section from '../components/ui/Section'
import EntranceAnimator from '../components/ui/EntranceAnimator'
import Panel from '../components/ui/Panel'
import { Skeleton } from '../components/ui/Skeleton'

function TradingWorkspaceSkeleton() {
  return (
    <div className="space-y-6 sm:space-y-8">
      <Section id="signals" errorTitle="Signals">
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
          <Skeleton className="h-32 rounded-lg" shimmer />
          <Skeleton className="h-32 rounded-lg" shimmer />
        </div>
        <div className="mt-4">
          <Skeleton className="h-48 rounded-lg" shimmer />
        </div>
      </Section>
      <Section id="trades" errorTitle="Trades">
        <Skeleton className="h-40 rounded-lg" shimmer />
      </Section>
      <Section id="execution-feed" errorTitle="Execution Feed">
        <Skeleton className="h-24 rounded-lg" shimmer />
      </Section>
    </div>
  )
}

export default function TradingWorkspace() {
  const { isPending, isError, error } = useSystemSnapshot()

  if (isError) {
    return (
      <Panel padding="md">
        <div className="flex items-center gap-3 text-gov-red">
          <span className="text-xs font-semibold uppercase tracking-wider">Engine unavailable</span>
          <span className="text-xs text-tertiary">
            {error instanceof Error ? error.message : 'Failed to load engine data'}
          </span>
        </div>
      </Panel>
    )
  }

  if (isPending) {
    return <TradingWorkspaceSkeleton />
  }

  return (
    <div className="space-y-6 sm:space-y-8">
      <Section id="signals" errorTitle="Signals">
        <EntranceAnimator variant="fade-up" delay={30}>
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
            <AdmissionPanel />
            <RejectedSignalExplorer />
          </div>
        </EntranceAnimator>
        <EntranceAnimator variant="fade-up">
          <SignalsTable />
        </EntranceAnimator>
      </Section>
      <Section id="trades" errorTitle="Trades">
        <EntranceAnimator variant="fade-up" delay={60}>
          <TradeOutcomes />
        </EntranceAnimator>
        <EntranceAnimator variant="fade-up" delay={100}>
          <TradeFeed />
        </EntranceAnimator>
      </Section>
      <Section id="execution-feed" errorTitle="Execution Feed">
        <EntranceAnimator variant="fade-up" delay={80}>
          <ExecutionFeed />
        </EntranceAnimator>
      </Section>
    </div>
  )
}
