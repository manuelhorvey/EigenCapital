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

export default function ExecutionWorkspace() {
  return (
    <div className="space-y-6 sm:space-y-8">
      {/* Top row: execution quality at a glance — summary KPIs flanked
          by the slippage histogram and fill quality gauge. All three read
          as a single block at different granularities. */}
      <Section id="execution-quality" errorTitle="Execution Quality" className="space-y-5 sm:space-y-6">
        <EntranceAnimator variant="fade-up">
          <div className="grid grid-cols-1 lg:grid-cols-12 gap-5 sm:gap-6">
            <div className="lg:col-span-3 min-w-0">
              <FillQualityGauge />
            </div>
            <div className="lg:col-span-5 min-w-0">
              <ExecutionQualityStrip />
            </div>
            <div className="lg:col-span-4 min-w-0">
              <SlippageHistogram />
            </div>
          </div>
        </EntranceAnimator>
      </Section>

      {/* Middle: this cycle's gate decisions + recent trade performance. */}
      <Section id="recent-execution" errorTitle="Cycle Gates & Trades" className="space-y-5 sm:space-y-6">
        <EntranceAnimator variant="fade-up">
          <div className="grid grid-cols-1 lg:grid-cols-12 gap-5 sm:gap-6">
            <div className="lg:col-span-5 min-w-0">
              <ExecutionFeed />
            </div>
            <div className="lg:col-span-7 min-w-0">
              <PnLWaterfall />
            </div>
          </div>
        </EntranceAnimator>
        <EntranceAnimator variant="fade-up" delay={60}>
          <TradeExecutionTable />
        </EntranceAnimator>
      </Section>

      {/* Bottom: deep trade attribution — MAE/MFE scatter + domain scores. */}
      <Section id="trade-attribution" errorTitle="Trade Attribution" className="space-y-5 sm:space-y-6">
        <EntranceAnimator variant="fade-up">
          <div className="grid grid-cols-1 lg:grid-cols-12 gap-5 sm:gap-6">
            <div className="lg:col-span-7 min-w-0">
              <MaeMfeScatter />
            </div>
            <div className="lg:col-span-5 min-w-0">
              <AttributionBreakdownCard />
            </div>
          </div>
        </EntranceAnimator>
      </Section>
    </div>
  )
}
