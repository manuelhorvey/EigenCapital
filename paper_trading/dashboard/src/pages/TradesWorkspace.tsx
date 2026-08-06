import PageHeader from '../components/PageHeader'
import Section from '../components/ui/Section'
import TradeOutcomes from '../components/TradeOutcomes'
import TradeFeed from '../components/TradeFeed'
import ExecutionFeed from '../components/ExecutionFeed'

export default function TradesWorkspace() {
  return (
    <div className="space-y-6 sm:space-y-8">
      <PageHeader
        title="Trades"
        description="Closed-trade outcomes, the trade journal feed, and recent execution cycle log."
        crumbs={[{ label: 'Trades' }]}
      />
      <Section id="trades-outcomes" errorTitle="Trade Outcomes">
        <TradeOutcomes />
      </Section>
      <Section id="trade-log" errorTitle="Trade Log">
        <TradeFeed />
      </Section>
      <Section id="execution-feed" errorTitle="Execution Feed">
        <ExecutionFeed />
      </Section>
    </div>
  )
}