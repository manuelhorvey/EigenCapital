import { useSystemSnapshot } from '../hooks/useSystemSnapshot'
import HealthScores from '../components/HealthScores'
import GovernanceRadar from '../components/governance/GovernanceRadar'
import PositionConcentrationPanel from '../components/PositionConcentrationPanel'
import FactorExposureBreakdown from '../components/FactorExposureBreakdown'
import PekScalarPanel from '../components/PekScalarPanel'
import PerformanceStateVelocityChart from '../components/PerformanceStateVelocityChart'
import RiskBudgetChart from '../components/RiskBudgetChart'
import DrawdownChart from '../components/DrawdownChart'
import CorrelationHeatmap from '../components/CorrelationHeatmap'
import HealthMonitorPanel from '../components/monitor/HealthMonitorPanel'
import PageShell from '../components/ui/PageShell'
import Section from '../components/ui/Section'
import { EntranceAnimator, Stagger, Skeleton } from '../components/ui'
import { SECTION_SPACING, GRID_GAP, gridSplit2 } from '../design/grid'

function RiskWorkspaceSkeleton() {
  return (
    <div className={SECTION_SPACING}>
      <Section id="governance-overview" errorTitle="Governance Overview">
        <div className={`grid grid-cols-1 lg:grid-cols-2 ${GRID_GAP}`}>
          <Skeleton className="h-40 rounded-lg" shimmer />
          <Skeleton className="h-40 rounded-lg" shimmer />
        </div>
      </Section>
      <Section id="portfolio-risk" errorTitle="Portfolio Risk">
        <div className={`grid grid-cols-1 lg:grid-cols-2 ${GRID_GAP}`}>
          <Skeleton className="h-48 rounded-lg" shimmer />
          <Skeleton className="h-48 rounded-lg" shimmer />
        </div>
        <div className="mt-4">
          <div className={`grid grid-cols-1 lg:grid-cols-2 ${GRID_GAP}`}>
            <Skeleton className="h-40 rounded-lg" shimmer />
            <Skeleton className="h-40 rounded-lg" shimmer />
          </div>
        </div>
      </Section>
      <Section id="model-health" errorTitle="Model Health">
        <Skeleton className="h-48 rounded-lg" shimmer />
        <div className="mt-4">
          <Skeleton className="h-48 rounded-lg" shimmer />
        </div>
      </Section>
    </div>
  )
}

export default function RiskWorkspace() {
  const { data, isPending, isError, error } = useSystemSnapshot((b) => b)

  return (
    <PageShell isPending={isPending} isError={isError} error={error} hasData={!!data} skeleton={<RiskWorkspaceSkeleton />}>
    <div className={SECTION_SPACING}>
      <Stagger staggerMs={30}>
        {/* Top: PEK scalars + governance radar — both are top-level governance summaries. */}
        <Section id="governance-overview" errorTitle="Governance Overview">
          <EntranceAnimator variant="fade-up">
            <div className={`${gridSplit2(true)} ${GRID_GAP}`}>
              <PekScalarPanel />
              <GovernanceRadar />
            </div>
          </EntranceAnimator>
        </Section>

        {/* Middle: portfolio risk constraints + PEK performance. */}
        <Section id="portfolio-risk" errorTitle="Portfolio Risk">
          <EntranceAnimator variant="fade-up">
            <div className={`${gridSplit2(true)} ${GRID_GAP}`}>
              <PositionConcentrationPanel />
              <FactorExposureBreakdown />
            </div>
          </EntranceAnimator>
          <EntranceAnimator variant="fade-up">
            <div className={`${gridSplit2(true)} ${GRID_GAP}`}>
              <PerformanceStateVelocityChart />
              <RiskBudgetChart />
            </div>
          </EntranceAnimator>
        </Section>

        {/* Drawdown + Correlation (V3, V4) — side by side */}
        <Section id="drawdown-correlation" errorTitle="Drawdown & Correlation">
          <EntranceAnimator variant="fade-up">
            <div className={`${gridSplit2(true)} ${GRID_GAP}`}>
              <DrawdownChart />
              <CorrelationHeatmap />
            </div>
          </EntranceAnimator>
        </Section>

        {/* Bottom: model health — stacked vertically so each component gets
            full width. HealthScores card grid (xl:grid-cols-6) and
            HealthMonitorPanel table both need horizontal space to render
            asset names and columns without truncation. */}
        <Section id="model-health" errorTitle="Model Health">
          <EntranceAnimator variant="fade-up">
            <HealthMonitorPanel />
          </EntranceAnimator>
          <EntranceAnimator variant="fade-up">
            <HealthScores />
          </EntranceAnimator>
        </Section>
      </Stagger>
    </div>
    </PageShell>
  )
}
