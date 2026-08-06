import HealthScores from '../components/HealthScores'
import GovernanceRadar from '../components/governance/GovernanceRadar'
import PositionConcentrationPanel from '../components/PositionConcentrationPanel'
import FactorExposureBreakdown from '../components/FactorExposureBreakdown'
import PekScalarPanel from '../components/PekScalarPanel'
import PerformanceStateVelocityChart from '../components/PerformanceStateVelocityChart'
import RiskBudgetChart from '../components/RiskBudgetChart'
import GateAggregationPanel from '../components/GateAggregationPanel'
import HaltConditions from '../components/HaltConditions'
import AdmissionPanel from '../components/AdmissionPanel'
import RejectedSignalExplorer from '../components/RejectedSignalExplorer'
import PageHeader from '../components/PageHeader'
import Section from '../components/ui/Section'

export default function RiskWorkspace() {
  return (
    <div className="space-y-6 sm:space-y-8">
      <PageHeader
        title="Risk"
        description="PEK state and admission, portfolio risk exposures, governance constraints, halt gates, and system health scores."
        crumbs={[{ label: 'Risk' }]}
      />
      <Section id="pek" errorTitle="PEK State">
        <PekScalarPanel />
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
          <PerformanceStateVelocityChart />
          <RiskBudgetChart />
        </div>
      </Section>
      <Section id="admission" errorTitle="PEK Admission">
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
          <AdmissionPanel />
          <RejectedSignalExplorer />
        </div>
      </Section>
      <Section id="portfolio-risk" errorTitle="Portfolio Risk">
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
          <PositionConcentrationPanel />
          <FactorExposureBreakdown />
        </div>
        <GateAggregationPanel />
      </Section>
      <Section id="governance" errorTitle="Governance Constraints">
        <GovernanceRadar />
      </Section>
      <Section id="halt-gates" errorTitle="Halt Gates">
        <HaltConditions />
      </Section>
      <Section id="health-scores" errorTitle="Health Scores">
        <HealthScores />
      </Section>
    </div>
  )
}
