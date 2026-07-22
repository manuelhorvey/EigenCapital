import { useMemo } from 'react'
import { useProvenance } from '../hooks/useProvenance'
import { useProvenanceStats } from '../hooks/useProvenanceStats'
import PageShell from '../components/ui/PageShell'
import Section from '../components/ui/Section'
import SectionHeader from '../components/ui/SectionHeader'
import Panel from '../components/ui/Panel'
import StatCard from '../components/ui/StatCard'
import DataTable from '../components/ui/DataTable'
import Badge, { signalToBadge } from '../components/ui/Badge'
import EmptyState from '../components/ui/EmptyState'
import { EntranceAnimator, Stagger, Skeleton } from '../components/ui'
import { SECTION_SPACING, gridMetric4 } from '../design/grid'
import { formatTimeAgo } from '../utils/format'
import type { ProvenanceRecord } from '../lib/schemas'

function ProvenanceSkeleton() {
  return (
    <div className={SECTION_SPACING}>
      <div className={gridMetric4()}>
        {Array.from({ length: 4 }).map((_, i) => (
          <Skeleton key={i} className="h-20 rounded-lg" shimmer />
        ))}
      </div>
      <Skeleton className="h-80 rounded-lg" shimmer />
    </div>
  )
}

export default function ProvenancePage() {
  const { data, isPending, isError, error } = useProvenance()
  const stats = useProvenanceStats()

  const records = useMemo(() => data?.records ?? [], [data])
  const hasData = records.length > 0

  return (
    <PageShell
      isPending={isPending}
      isError={isError}
      error={error}
      hasData={hasData}
      skeleton={<ProvenanceSkeleton />}
    >
      <div className={SECTION_SPACING}>
        <Stagger staggerMs={30}>
          <Section id="provenance-stats" title="Provenance Overview">
            <EntranceAnimator variant="fade-up">
              <Panel padding="md">
                <SectionHeader title="Provenance Store" accent="emerald" />
                <div className={`mt-4 ${gridMetric4()}`}>
                  <StatCard
                    label="Total Records"
                    value={stats.data?.total ?? '-'}
                    loading={stats.isPending}
                    variant="kpi"
                    accent="var(--color-accent-emerald)"
                  />
                  <StatCard
                    label="Unique Assets"
                    value={stats.data?.unique_assets ?? '-'}
                    loading={stats.isPending}
                    variant="kpi"
                    accent="var(--color-accent-blue)"
                  />
                  <StatCard
                    label="Latest Cycle"
                    value={stats.data?.latest_cycle_id != null ? `#${stats.data.latest_cycle_id}` : '-'}
                    loading={stats.isPending}
                    variant="kpi"
                    accent="var(--color-accent-amber)"
                  />
                  <StatCard
                    label="Latest Timestamp"
                    value={stats.data?.latest_timestamp ? formatTimeAgo(stats.data.latest_timestamp) : '-'}
                    loading={stats.isPending}
                    variant="kpi"
                    accent="var(--color-accent-purple)"
                  />
                </div>
              </Panel>
            </EntranceAnimator>
          </Section>

          <Section id="provenance-records" title="Decision History">
            <EntranceAnimator variant="fade-up">
              <Panel padding="md">
                <SectionHeader title="Decision History" accent="neutral" />
                {hasData ? (
                  <div className="mt-4">
                    <DataTable<ProvenanceRecord>
                      columns={[
                        {
                          key: 'asset',
                          label: 'Asset',
                          sortable: true,
                          width: '80px',
                          render: (r) => <span className="font-mono font-semibold text-primary">{r.asset}</span>,
                        },
                        {
                          key: 'cycle_id',
                          label: 'Cycle',
                          sortable: true,
                          width: '60px',
                          align: 'right',
                          render: (r) => <span className="text-tertiary">#{r.cycle_id}</span>,
                        },
                        {
                          key: 'signal',
                          label: 'Signal',
                          sortable: true,
                          width: '90px',
                          render: (r) => {
                            if (!r.signal) return <span className="text-tertiary">—</span>
                            const { variant, icon } = signalToBadge(r.signal)
                            return <Badge variant={variant} icon={icon}>{r.signal}</Badge>
                          },
                        },
                        {
                          key: 'position_size',
                          label: 'Size',
                          sortable: true,
                          width: '80px',
                          align: 'right',
                          render: (r) => r.position_size != null ? r.position_size.toFixed(2) : <span className="text-tertiary">—</span>,
                        },
                        {
                          key: 'confidence',
                          label: 'Conf.',
                          sortable: true,
                          width: '70px',
                          align: 'right',
                          render: (r) => r.confidence != null ? `${(r.confidence * 100).toFixed(0)}%` : <span className="text-tertiary">—</span>,
                        },
                        {
                          key: 'prob_long',
                          label: 'P(Long)',
                          sortable: true,
                          width: '80px',
                          align: 'right',
                          render: (r) => r.prob_long != null ? `${(r.prob_long * 100).toFixed(0)}%` : <span className="text-tertiary">—</span>,
                        },
                        {
                          key: 'prob_short',
                          label: 'P(Short)',
                          sortable: true,
                          width: '80px',
                          align: 'right',
                          render: (r) => r.prob_short != null ? `${(r.prob_short * 100).toFixed(0)}%` : <span className="text-tertiary">—</span>,
                        },
                        {
                          key: 'total_equity',
                          label: 'Equity',
                          sortable: true,
                          width: '90px',
                          align: 'right',
                          render: (r) => r.total_equity != null ? `$${r.total_equity.toLocaleString(undefined, { maximumFractionDigits: 0 })}` : <span className="text-tertiary">—</span>,
                        },
                        {
                          key: 'drawdown_pct',
                          label: 'DD%',
                          sortable: true,
                          width: '70px',
                          align: 'right',
                          render: (r) => r.drawdown_pct != null ? `${r.drawdown_pct.toFixed(1)}%` : <span className="text-tertiary">—</span>,
                        },
                        {
                          key: 'decision_type',
                          label: 'Type',
                          sortable: true,
                          width: '100px',
                          render: (r) => {
                            if (r.decision_type === 'COUNTERFACTUAL') return <Badge variant="warning">CF</Badge>
                            if (r.decision_type === 'SHADOW') return <Badge variant="neutral">SHADOW</Badge>
                            return <Badge variant="default">LIVE</Badge>
                          },
                        },
                      ]}
                      data={records}
                      keyExtractor={(r) => r.decision_id}
                      sortable
                      defaultSortKey="decision_timestamp"
                      defaultSortDir="desc"
                      emptyMessage="No provenance records captured yet"
                    />
                  </div>
                ) : (
                  <EmptyState
                    icon="clock"
                    message="No provenance records yet"
                    hint="Decisions will appear here once the engine starts capturing provenance data."
                  />
                )}
              </Panel>
            </EntranceAnimator>
          </Section>
        </Stagger>
      </div>
    </PageShell>
  )
}
