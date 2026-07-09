import { useSystemSnapshot } from '../hooks/useSystemSnapshot'
import ExecutionQualityStrip from '../components/execution/ExecutionQualityStrip'
import SlippageHistogram from '../components/execution/SlippageHistogram'
import FillQualityGauge from '../components/execution/FillQualityGauge'
import TradeExecutionTable from '../components/execution/TradeExecutionTable'
import AttributionBreakdownCard from '../components/attribution/AttributionBreakdownCard'
import PnLWaterfall from '../components/attribution/PnLWaterfall'
import MaeMfeScatter from '../components/attribution/MaeMfeScatter'
import ExecutionFeed from '../components/ExecutionFeed'
import PageShell from '../components/ui/PageShell'
import Section from '../components/ui/Section'
import { EntranceAnimator, Stagger, Skeleton } from '../components/ui'
import { SECTION_SPACING, GRID_GAP_WIDE, gridSplit2 } from '../design/grid'

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
  const { data, isPending, isError, error } = useSystemSnapshot((b) => b)

  return (
    <PageShell isPending={isPending} isError={isError} error={error} hasData={!!data} skeleton={<ExecutionWorkspaceSkeleton />}>
      <div className={SECTION_SPACING}>
      <Stagger staggerMs={30}>
        {/* Section 1 — Execution Quality
            Top: KPI summary strip (full width).
            Bottom: fill quality gauges + slippage distribution side by side.
            All three read from the same attribution bundle. */}
        <Section id="execution-quality" errorTitle="Execution Quality" className="space-y-5 sm:space-y-6">
          <EntranceAnimator variant="fade-up">
            <ExecutionQualityStrip />
          </EntranceAnimator>
          <EntranceAnimator variant="fade-up">
            <div className={`${gridSplit2(true)} ${GRID_GAP_WIDE}`}>
              <FillQualityGauge />
              <SlippageHistogram />
            </div>
          </EntranceAnimator>
        </Section>

        {/* Section 2 — Execution Feed
            Full-width per-asset gate table. Needs the horizontal space for
            its 18+ asset rows and min-width columns. */}
        <Section id="execution-feed" errorTitle="Execution Feed">
          <EntranceAnimator variant="fade-up">
            <ExecutionFeed />
          </EntranceAnimator>
        </Section>

        {/* Section 3 — Trade Attribution
            All trade-level analysis grouped together: PnL decomposition +
            domain scores, detail table, and MAE/MFE scatter. */}
        <Section id="trade-attribution" errorTitle="Trade Attribution" className="space-y-5 sm:space-y-6">
          <EntranceAnimator variant="fade-up">
            <div className={`${gridSplit2(true)} ${GRID_GAP_WIDE}`}>
              <PnLWaterfall />
              <AttributionBreakdownCard />
            </div>
          </EntranceAnimator>
          <EntranceAnimator variant="fade-up">
            <TradeExecutionTable />
          </EntranceAnimator>
          <EntranceAnimator variant="fade-up">
            <MaeMfeScatter />
          </EntranceAnimator>
        </Section>
      </Stagger>
    </div>
    </PageShell>
  )
}
