import { useSystemSnapshot } from '../hooks/useSystemSnapshot'
import SignalsTable from '../components/SignalsTable'
import TradeOutcomes from '../components/TradeOutcomes'
import TradeFeed from '../components/TradeFeed'
import AdmissionPanel from '../components/AdmissionPanel'
import RejectedSignalExplorer from '../components/RejectedSignalExplorer'
import GateAggregationPanel from '../components/GateAggregationPanel'
import PageShell from '../components/ui/PageShell'
import Section from '../components/ui/Section'
import { EntranceAnimator, Stagger, Skeleton } from '../components/ui'
import { SECTION_SPACING, GRID_GAP, gridSplit2 } from '../design/grid'

function TradingWorkspaceSkeleton() {
  return (
    <div className="space-y-7 sm:space-y-10">
      <Section id="signals" errorTitle="Signals">
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-4 sm:gap-5">
          <Skeleton className="h-32 rounded-lg" shimmer />
          <Skeleton className="h-32 rounded-lg" shimmer />
        </div>
        <div className="mt-5">
          <Skeleton className="h-48 rounded-lg" shimmer />
        </div>
        <div className="mt-4">
          <Skeleton className="h-28 rounded-lg" shimmer />
        </div>
      </Section>
      <Section id="trades" errorTitle="Trades">
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-4 sm:gap-5">
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
    <PageShell isPending={isPending} isError={isError} error={error} hasData={!!data} skeleton={<TradingWorkspaceSkeleton />} serverTime={data?.meta?.server_time}>
      <div className={SECTION_SPACING}>
      <Stagger staggerMs={35}>
        <Section id="signals" errorTitle="Signals">
          <EntranceAnimator variant="fade-up">
            <div className={`${gridSplit2(true)} ${GRID_GAP}`}>
              <AdmissionPanel />
              <RejectedSignalExplorer />
            </div>
          </EntranceAnimator>
          <EntranceAnimator variant="fade-up">
            <SignalsTable />
          </EntranceAnimator>
          <EntranceAnimator variant="fade-up">
            <GateAggregationPanel />
          </EntranceAnimator>
        </Section>
        <Section id="trades" errorTitle="Trades">
          <EntranceAnimator variant="fade-up">
            <div className={`${gridSplit2(true)} ${GRID_GAP}`}>
              <TradeOutcomes />
              <TradeFeed />
            </div>
          </EntranceAnimator>
        </Section>
      </Stagger>
    </div>
    </PageShell>
  )
}
