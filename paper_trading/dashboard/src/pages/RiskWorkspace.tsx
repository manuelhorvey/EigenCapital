import HealthScores from '../components/HealthScores'
import GovernanceRadar from '../components/governance/GovernanceRadar'
import AssetGrid from '../components/AssetGrid'
import Section from '../components/ui/Section'

export default function RiskWorkspace() {
  return (
    <div className="space-y-6 sm:space-y-8">
      <Section id="portfolio-risk" errorTitle="Portfolio Risk">
        <HealthScores />
      </Section>
      <Section id="governance" errorTitle="Governance Constraints">
        <GovernanceRadar />
      </Section>
      <Section id="asset-grid" errorTitle="All Assets">
        <AssetGrid />
      </Section>
    </div>
  )
}
