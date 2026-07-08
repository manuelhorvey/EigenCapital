import HealthScores from '../components/HealthScores'
import GovernanceRadar from '../components/governance/GovernanceRadar'
import PositionConcentrationPanel from '../components/PositionConcentrationPanel'
import FactorExposureBreakdown from '../components/FactorExposureBreakdown'
import PekScalarPanel from '../components/PekScalarPanel'
import PerformanceStateVelocityChart from '../components/PerformanceStateVelocityChart'
import RiskBudgetChart from '../components/RiskBudgetChart'
import HealthMonitorPanel from '../components/monitor/HealthMonitorPanel'
import Section from '../components/ui/Section'
import EntranceAnimator from '../components/ui/EntranceAnimator'

export default function RiskWorkspace() {
  return (
    <div className="space-y-6 sm:space-y-8">
      {/* Top: PEK scalars + governance radar — both are top-level governance summaries. */}
      <Section id="governance-overview" errorTitle="Governance Overview">
        <EntranceAnimator variant="fade-up">
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
            <PekScalarPanel />
            <GovernanceRadar />
          </div>
        </EntranceAnimator>
      </Section>

      {/* Middle: portfolio risk constraints + PEK performance. */}
      <Section id="portfolio-risk" errorTitle="Portfolio Risk">
        <EntranceAnimator variant="fade-up" delay={45}>
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
            <PositionConcentrationPanel />
            <FactorExposureBreakdown />
          </div>
        </EntranceAnimator>
        <EntranceAnimator variant="fade-up" delay={75}>
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
            <PerformanceStateVelocityChart />
            <RiskBudgetChart />
          </div>
        </EntranceAnimator>
      </Section>

      {/* Bottom: model health scores — combined into a single side-by-side section. */}
      <Section id="model-health" errorTitle="Model Health">
        <EntranceAnimator variant="fade-up" delay={105}>
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
            <HealthMonitorPanel />
            <HealthScores />
          </div>
        </EntranceAnimator>
      </Section>
    </div>
  )
}
