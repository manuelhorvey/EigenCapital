import SignalsTable from '../components/SignalsTable'
import TradeOutcomes from '../components/TradeOutcomes'
import TradeFeed from '../components/TradeFeed'
import EquityChart from '../components/EquityChart'
import ExecutionFeed from '../components/ExecutionFeed'
import AdmissionPanel from '../components/AdmissionPanel'
import RejectedSignalExplorer from '../components/RejectedSignalExplorer'
import AssetMiniGrid from '../components/AssetMiniGrid'
import Section from '../components/ui/Section'
import EntranceAnimator from '../components/ui/EntranceAnimator'

export default function TradingWorkspace() {
  return (
    <div className="space-y-6 sm:space-y-8">
      <Section id="signals" errorTitle="Signals">
        <EntranceAnimator variant="fade-up">
          <div className="grid grid-cols-1 xl:grid-cols-5 gap-5 sm:gap-6">
            <div className="xl:col-span-3 min-w-0">
              <SignalsTable />
            </div>
            <div className="xl:col-span-2 min-w-0">
              <EquityChart />
            </div>
          </div>
        </EntranceAnimator>
        <EntranceAnimator variant="fade-up" delay={30}>
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
            <AdmissionPanel />
            <RejectedSignalExplorer />
          </div>
        </EntranceAnimator>
      </Section>
      <Section id="open-positions" errorTitle="Open Positions">
        <EntranceAnimator variant="fade-up" delay={45}>
          <AssetMiniGrid openOnly />
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
