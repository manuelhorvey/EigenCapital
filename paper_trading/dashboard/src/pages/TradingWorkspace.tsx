import SignalsTable from '../components/SignalsTable'
import LiveSharpeCard from '../components/LiveSharpeCard'
import PageHeader from '../components/PageHeader'
import Section from '../components/ui/Section'

export default function TradingWorkspace() {
  return (
    <div className="space-y-6 sm:space-y-8">
      <PageHeader
        title="Trading"
        description="Live market snapshot: current signals per asset and live performance."
        crumbs={[{ label: 'Trading' }]}
      />
      <Section id="signals" errorTitle="Signals">
        <div className="grid grid-cols-1 xl:grid-cols-5 gap-5 sm:gap-6">
          <div className="xl:col-span-3 min-w-0">
            <SignalsTable />
          </div>
          <div className="xl:col-span-2 min-w-0">
            <LiveSharpeCard />
          </div>
        </div>
      </Section>
    </div>
  )
}