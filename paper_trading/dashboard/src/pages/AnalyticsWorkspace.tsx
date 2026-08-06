import PageHeader from '../components/PageHeader'
import Section from '../components/ui/Section'
import StatisticalMetricsTable from '../components/StatisticalMetricsTable'
import CalibrationCurve from '../components/CalibrationCurve'

export default function AnalyticsWorkspace() {
  return (
    <div className="space-y-6 sm:space-y-8">
      <PageHeader
        title="Analytics"
        description="Backtest statistical metrics and confidence-calibration diagnostics per asset."
        crumbs={[{ label: 'Analytics' }]}
      />
      <Section id="statistics" errorTitle="Statistics">
        <StatisticalMetricsTable />
      </Section>
      <Section id="calibration" errorTitle="Calibration">
        <CalibrationCurve />
      </Section>
    </div>
  )
}