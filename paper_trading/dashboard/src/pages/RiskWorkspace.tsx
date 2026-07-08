import { useSystemSnapshot } from '../hooks/useSystemSnapshot'
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
import Panel from '../components/ui/Panel'
import { Skeleton } from '../components/ui/Skeleton'

function RiskWorkspaceSkeleton() {
  return (
    <div className="space-y-6 sm:space-y-8">
      <Section id="governance-overview" errorTitle="Governance Overview">
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
          <Skeleton className="h-40 rounded-lg" shimmer />
          <Skeleton className="h-40 rounded-lg" shimmer />
        </div>
      </Section>
      <Section id="portfolio-risk" errorTitle="Portfolio Risk">
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
          <Skeleton className="h-48 rounded-lg" shimmer />
          <Skeleton className="h-48 rounded-lg" shimmer />
        </div>
        <div className="mt-4">
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
            <Skeleton className="h-40 rounded-lg" shimmer />
            <Skeleton className="h-40 rounded-lg" shimmer />
          </div>
        </div>
      </Section>
      <Section id="model-health" errorTitle="Model Health">
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
          <Skeleton className="h-36 rounded-lg" shimmer />
          <Skeleton className="h-36 rounded-lg" shimmer />
        </div>
      </Section>
    </div>
  )
}

export default function RiskWorkspace() {
  const { data, isPending, isError, error } = useSystemSnapshot()

  if (isError && !data) {
    return (
      <Panel padding="md">
        <div className="flex items-center gap-3 text-gov-red">
          <span className="text-xs font-semibold uppercase tracking-wider">Engine unavailable</span>
          <span className="text-xs text-tertiary">
            {error instanceof Error ? error.message : 'Failed to load engine data'}
          </span>
        </div>
      </Panel>
    )
  }

  if (isPending && !data) {
    return <RiskWorkspaceSkeleton />
  }

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
