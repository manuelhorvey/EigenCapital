import SignalsTable from '../components/SignalsTable'
import TradeOutcomes from '../components/TradeOutcomes'
import TradeFeed from '../components/TradeFeed'
import EquityChart from '../components/EquityChart'
import ExecutionFeed from '../components/ExecutionFeed'
import Section from '../components/ui/Section'

export default function TradingWorkspace() {
  return (
    <div className="space-y-6 sm:space-y-8">
      <Section id="signals" errorTitle="Signals">
        <div className="grid grid-cols-1 xl:grid-cols-5 gap-5 sm:gap-6">
          <div className="xl:col-span-3 min-w-0">
            <SignalsTable />
          </div>
          <div className="xl:col-span-2 min-w-0">
            <EquityChart />
          </div>
        </div>
      </Section>
      <Section id="trades" errorTitle="Trades">
        <TradeOutcomes />
        <TradeFeed />
      </Section>
      <Section id="execution-feed" errorTitle="Execution Feed">
        <ExecutionFeed />
      </Section>
    </div>
  )
}
