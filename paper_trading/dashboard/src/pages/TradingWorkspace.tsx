import { useSystemSnapshot } from '../hooks/useSystemSnapshot'
import SignalsTable from '../components/SignalsTable'
import TradeOutcomes from '../components/TradeOutcomes'
import TradeFeed from '../components/TradeFeed'
import AdmissionPanel from '../components/AdmissionPanel'
import RejectedSignalExplorer from '../components/RejectedSignalExplorer'
import GateAggregationPanel from '../components/GateAggregationPanel'
import PageShell from '../components/ui/PageShell'
import Section from '../components/ui/Section'
import EntranceAnimator from '../components/ui/EntranceAnimator'
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
        <div className="mt-4">
          <Skeleton className="h-28 rounded-lg" shimmer />
        </div>
      </Section>
      <Section id="trades" errorTitle="Trades">
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
          <Skeleton className="h-40 rounded-lg" shimmer />
          <Skeleton className="h-40 rounded-lg" shimmer />
        </div>
      </Section>
    </div>
  )
}

export default function TradingWorkspace() {
  const { data, isPending, isError, error } = useSystemSnapshot()

  return (
    <PageShell isPending={isPending} isError={isError} error={error} hasData={!!data} skeleton={<TradingWorkspaceSkeleton />}>
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
        <EntranceAnimator variant="fade-up" delay={100}>
          <GateAggregationPanel />
        </EntranceAnimator>
      </Section>
      <Section id="trades" errorTitle="Trades">
        <EntranceAnimator variant="fade-up" delay={60}>
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
            <TradeOutcomes />
            <TradeFeed />
          </div>
        </EntranceAnimator>
      </Section>
    </div>
    </PageShell>
  )
}
