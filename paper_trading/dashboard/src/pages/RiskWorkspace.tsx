import HealthScores from '../components/HealthScores'
import GovernanceRadar from '../components/governance/GovernanceRadar'
import PositionConcentrationPanel from '../components/PositionConcentrationPanel'
import FactorExposureBreakdown from '../components/FactorExposureBreakdown'
import PekScalarPanel from '../components/PekScalarPanel'
import PerformanceStateVelocityChart from '../components/PerformanceStateVelocityChart'
import RiskBudgetChart from '../components/RiskBudgetChart'
import GateAggregationPanel from '../components/GateAggregationPanel'
import Section from '../components/ui/Section'
import EntranceAnimator from '../components/ui/EntranceAnimator'

export default function RiskWorkspace() {
  return (
    <div className="space-y-6 sm:space-y-8">
      <Section id="pek" errorTitle="PEK State">
        <EntranceAnimator variant="fade-up">
          <PekScalarPanel />
        </EntranceAnimator>
        <EntranceAnimator variant="fade-up" delay={30}>
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
            <PerformanceStateVelocityChart />
            <RiskBudgetChart />
          </div>
        </EntranceAnimator>
      </Section>
      <Section id="portfolio-risk" errorTitle="Portfolio Risk">
        <EntranceAnimator variant="fade-up" delay={60}>
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
            <PositionConcentrationPanel />
            <FactorExposureBreakdown />
          </div>
        </EntranceAnimator>
        <EntranceAnimator variant="fade-up" delay={90}>
          <GateAggregationPanel />
        </EntranceAnimator>
      </Section>
      <Section id="governance" errorTitle="Governance Constraints">
        <EntranceAnimator variant="fade-up" delay={120}>
          <GovernanceRadar />
        </EntranceAnimator>
      </Section>
      <Section id="health-scores" errorTitle="Health Scores">
        <EntranceAnimator variant="fade-up" delay={150}>
          <HealthScores />
        </EntranceAnimator>
      </Section>
    </div>
  )
}
