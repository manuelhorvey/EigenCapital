import ExecutionQualityStrip from '../components/execution/ExecutionQualityStrip'
import SlippageHistogram from '../components/execution/SlippageHistogram'
import FillQualityGauge from '../components/execution/FillQualityGauge'
import TradeExecutionTable from '../components/execution/TradeExecutionTable'
import AttributionBreakdownCard from '../components/attribution/AttributionBreakdownCard'
import PnLWaterfall from '../components/attribution/PnLWaterfall'
import MaeMfeScatter from '../components/attribution/MaeMfeScatter'
import Section from '../components/ui/Section'

export default function ExecutionWorkspace() {
  return (
    <div className="space-y-6 sm:space-y-8">
      <Section id="execution-quality" errorTitle="Execution Quality" className="space-y-5 sm:space-y-6">
        <ExecutionQualityStrip />
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-5 sm:gap-6">
          <div className="lg:col-span-2 min-w-0">
            <SlippageHistogram />
          </div>
          <div className="lg:col-span-1 min-w-0">
            <FillQualityGauge />
          </div>
        </div>
        <TradeExecutionTable />
      </Section>
      <Section id="trade-attribution" errorTitle="Trade Attribution" className="space-y-5 sm:space-y-6">
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-5 sm:gap-6">
          <AttributionBreakdownCard />
          <PnLWaterfall />
        </div>
        <MaeMfeScatter />
      </Section>
    </div>
  )
}
