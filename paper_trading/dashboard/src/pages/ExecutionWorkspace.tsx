import { useSystemSnapshot } from '../hooks/useSystemSnapshot'
import ExecutionQualityStrip from '../components/execution/ExecutionQualityStrip'
import SlippageHistogram from '../components/execution/SlippageHistogram'
import FillQualityGauge from '../components/execution/FillQualityGauge'
import TradeExecutionTable from '../components/execution/TradeExecutionTable'
import AttributionBreakdownCard from '../components/attribution/AttributionBreakdownCard'
import PnLWaterfall from '../components/attribution/PnLWaterfall'
import MaeMfeScatter from '../components/attribution/MaeMfeScatter'
import ExecutionFeed from '../components/ExecutionFeed'
import Section from '../components/ui/Section'
import EntranceAnimator from '../components/ui/EntranceAnimator'
import Panel from '../components/ui/Panel'
import { Skeleton } from '../components/ui/Skeleton'

function ExecutionWorkspaceSkeleton() {
  return (
    <div className="space-y-6 sm:space-y-8">
      <Section id="execution-quality" errorTitle="Execution Quality">
        <Skeleton className="h-36 rounded-lg" shimmer />
        <div className="mt-4">
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-5 sm:gap-6">
            <Skeleton className="h-48 rounded-lg" shimmer />
            <Skeleton className="h-48 rounded-lg" shimmer />
          </div>
        </div>
      </Section>
      <Section id="execution-feed" errorTitle="Execution Feed">
        <Skeleton className="h-64 rounded-lg" shimmer />
      </Section>
      <Section id="trade-attribution" errorTitle="Trade Attribution">
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-5 sm:gap-6">
          <Skeleton className="h-48 rounded-lg" shimmer />
          <Skeleton className="h-48 rounded-lg" shimmer />
        </div>
        <div className="mt-4">
          <Skeleton className="h-64 rounded-lg" shimmer />
        </div>
        <div className="mt-4">
          <Skeleton className="h-48 rounded-lg" shimmer />
        </div>
      </Section>
    </div>
  )
}

export default function ExecutionWorkspace() {
  const { data, isPending, isError, error } = useSystemSnapshot()

  if (isError && !data) {
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

  if (isPending && !data) {
    return <ExecutionWorkspaceSkeleton />
  }

  return (
    <div className="space-y-6 sm:space-y-8">
      {/* Section 1 — Execution Quality
          Top: KPI summary strip (full width).
          Bottom: fill quality gauges + slippage distribution side by side.
          All three read from the same attribution bundle. */}
      <Section id="execution-quality" errorTitle="Execution Quality" className="space-y-5 sm:space-y-6">
        <EntranceAnimator variant="fade-up">
          <ExecutionQualityStrip />
        </EntranceAnimator>
        <EntranceAnimator variant="fade-up" delay={45}>
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-5 sm:gap-6">
            <FillQualityGauge />
            <SlippageHistogram />
          </div>
        </EntranceAnimator>
      </Section>

      {/* Section 2 — Execution Feed
          Full-width per-asset gate table. Needs the horizontal space for
          its 18+ asset rows and min-width columns. */}
      <Section id="execution-feed" errorTitle="Execution Feed">
        <EntranceAnimator variant="fade-up" delay={75}>
          <ExecutionFeed />
        </EntranceAnimator>
      </Section>

      {/* Section 3 — Trade Attribution
          All trade-level analysis grouped together: PnL decomposition +
          domain scores, detail table, and MAE/MFE scatter. */}
      <Section id="trade-attribution" errorTitle="Trade Attribution" className="space-y-5 sm:space-y-6">
        <EntranceAnimator variant="fade-up" delay={105}>
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-5 sm:gap-6">
            <PnLWaterfall />
            <AttributionBreakdownCard />
          </div>
        </EntranceAnimator>
        <EntranceAnimator variant="fade-up" delay={135}>
          <TradeExecutionTable />
        </EntranceAnimator>
        <EntranceAnimator variant="fade-up" delay={165}>
          <MaeMfeScatter />
        </EntranceAnimator>
      </Section>
    </div>
  )
}
