import HealthScores from '../components/HealthScores'
import GovernanceRadar from '../components/governance/GovernanceRadar'
import AssetGrid from '../components/AssetGrid'
import Section from '../components/ui/Section'
import EntranceAnimator from '../components/ui/EntranceAnimator'

export default function RiskWorkspace() {
  return (
    <div className="space-y-6 sm:space-y-8">
      <Section id="portfolio-risk" errorTitle="Portfolio Risk">
        <EntranceAnimator variant="fade-up">
          <HealthScores />
        </EntranceAnimator>
      </Section>
      <Section id="governance" errorTitle="Governance Constraints">
        <EntranceAnimator variant="fade-up" delay={60}>
          <GovernanceRadar />
        </EntranceAnimator>
      </Section>
      <Section id="asset-grid" errorTitle="All Assets">
        <EntranceAnimator variant="fade-up" delay={100}>
          <AssetGrid />
        </EntranceAnimator>
      </Section>
    </div>
  )
}
