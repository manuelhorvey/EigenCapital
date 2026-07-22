import { useState, useMemo } from 'react'
import { useProvenance } from '../hooks/useProvenance'
import { useCounterfactual } from '../hooks/useCounterfactual'
import PageShell from '../components/ui/PageShell'
import Section from '../components/ui/Section'
import SectionHeader from '../components/ui/SectionHeader'
import Panel from '../components/ui/Panel'
import DataTable from '../components/ui/DataTable'
import Badge, { signalToBadge } from '../components/ui/Badge'
import EmptyState from '../components/ui/EmptyState'
import { EntranceAnimator, Stagger, Skeleton } from '../components/ui'
import { SECTION_SPACING } from '../design/grid'
import { Play, AlertCircle, CheckCircle } from 'lucide-react'
import type { ProvenanceRecord } from '../lib/schemas'

interface CfFormState {
  decisionId: string
  overrideType: 'gate' | 'probability' | 'signal' | 'sltp'
  gateName: string
  gateValue: boolean
  probLong: string
  probShort: string
  probNeutral: string
  signalValue: string
  slValue: string
  tpValue: string
}

const INITIAL_FORM: CfFormState = {
  decisionId: '',
  overrideType: 'gate',
  gateName: 'spread_gate_blocked',
  gateValue: false,
  probLong: '0.0',
  probShort: '0.0',
  probNeutral: '0.0',
  signalValue: 'BUY',
  slValue: '',
  tpValue: '',
}

function CfSkeleton() {
  return (
    <div className={SECTION_SPACING}>
      <Skeleton className="h-12 rounded-lg w-1/3" shimmer />
      <Skeleton className="h-80 rounded-lg" shimmer />
      <Skeleton className="h-40 rounded-lg" shimmer />
    </div>
  )
}

export default function CounterfactualPage() {
  const { data, isPending, isError, error } = useProvenance()
  const cfMutation = useCounterfactual()
  const [form, setForm] = useState<CfFormState>(INITIAL_FORM)
  const [result, setResult] = useState<string | null>(null)

  const records = useMemo(() => data?.records ?? [], [data])
  const hasData = records.length > 0

  const updateForm = (patch: Partial<CfFormState>) => setForm(prev => ({ ...prev, ...patch }))

  const handleRun = async () => {
    setResult(null)
    try {
      const params: Record<string, unknown> = {
        decision_id: form.decisionId,
        override_type: form.overrideType,
      }
      if (form.overrideType === 'gate') {
        params.field = form.gateName
        params.value = form.gateValue
      } else if (form.overrideType === 'probability') {
        params.value = {
          prob_long: parseFloat(form.probLong),
          prob_short: parseFloat(form.probShort),
          prob_neutral: parseFloat(form.probNeutral),
        }
      } else if (form.overrideType === 'signal') {
        params.field = form.signalValue
      } else if (form.overrideType === 'sltp') {
        const val: Record<string, number> = {}
        if (form.slValue) val.sl = parseFloat(form.slValue)
        if (form.tpValue) val.tp = parseFloat(form.tpValue)
        params.value = val
      }
      const res = await cfMutation.mutateAsync(params as any)
      const cfId = res?.counterfactual?.decision_id?.decision_id ?? 'unknown'
      setResult(`Counterfactual created: ${cfId}`)
    } catch (e) {
      setResult(`Error: ${e instanceof Error ? e.message : 'Unknown error'}`)
    }
  }

  return (
    <PageShell
      isPending={isPending}
      isError={isError}
      error={error}
      hasData={true}
      skeleton={<CfSkeleton />}
    >
      <div className={SECTION_SPACING}>
        <Stagger staggerMs={30}>
          <Section id="counterfactual-select" title="Select Decision">
            <EntranceAnimator variant="fade-up">
              <Panel padding="md">
                <SectionHeader title="Select a Decision" accent="emerald" />
                {hasData ? (
                  <div className="mt-4">
                    <DataTable<ProvenanceRecord>
                      columns={[
                        {
                          key: 'asset', label: 'Asset', sortable: true, width: '80px',
                          render: (r) => <span className="font-mono font-semibold text-primary">{r.asset}</span>,
                        },
                        {
                          key: 'cycle_id', label: 'Cycle', sortable: true, width: '60px', align: 'right',
                          render: (r) => <span className="text-tertiary">#{r.cycle_id}</span>,
                        },
                        {
                          key: 'signal', label: 'Signal', sortable: true, width: '90px',
                          render: (r) => {
                            if (!r.signal) return <span className="text-tertiary">—</span>
                            const { variant, icon } = signalToBadge(r.signal)
                            return <Badge variant={variant} icon={icon}>{r.signal}</Badge>
                          },
                        },
                        {
                          key: 'decision_timestamp', label: 'Time', sortable: true,
                          render: (r) => <span className="text-tertiary text-[10px]">{r.decision_timestamp}</span>,
                        },
                        {
                          key: 'decision_id', label: 'Decision ID', width: '220px',
                          render: (r) => (
                            <button
                              type="button"
                              onClick={() => updateForm({ decisionId: r.decision_id })}
                              className={`text-[10px] font-mono truncate max-w-[200px] block rounded px-1 py-0.5 transition-colors ${
                                form.decisionId === r.decision_id
                                  ? 'bg-accent-emerald/10 text-accent-emerald border border-accent-emerald/30'
                                  : 'text-tertiary hover:text-primary hover:bg-panel/60 border border-transparent'
                              }`}
                              title="Click to select this decision"
                            >
                              {r.decision_id.slice(0, 8)}…
                            </button>
                          ),
                        },
                      ]}
                      data={records}
                      keyExtractor={(r) => r.decision_id}
                      sortable
                      defaultSortKey="decision_timestamp"
                      defaultSortDir="desc"
                      emptyMessage="No decisions available"
                    />
                  </div>
                ) : (
                  <EmptyState icon="clock" message="No decisions available yet" hint="Wait for the engine to capture provenance data." />
                )}
              </Panel>
            </EntranceAnimator>
          </Section>

          <Section id="counterfactual-form" title="Override Configuration">
            <EntranceAnimator variant="fade-up">
              <Panel padding="md">
                <SectionHeader title="Override Configuration" accent="amber" />
                <div className="mt-4 space-y-4">
                  <div className="flex flex-wrap gap-4">
                    <div className="flex-1 min-w-[200px]">
                      <label className="block text-[10px] font-semibold uppercase tracking-wider text-tertiary mb-1">Override Type</label>
                      <select
                        value={form.overrideType}
                        onChange={(e) => updateForm({ overrideType: e.target.value as any })}
                        className="w-full bg-surface border border-default rounded-lg px-2.5 py-1.5 text-xs text-primary focus:outline-none focus:ring-1 focus:ring-accent-emerald"
                      >
                        <option value="gate">Gate Override</option>
                        <option value="probability">Probability Override</option>
                        <option value="signal">Signal Override</option>
                        <option value="sltp">SL/TP Override</option>
                      </select>
                    </div>

                    <div className="flex-1 min-w-[200px]">
                      <label className="block text-[10px] font-semibold uppercase tracking-wider text-tertiary mb-1">Decision ID</label>
                      <input
                        type="text"
                        value={form.decisionId}
                        onChange={(e) => updateForm({ decisionId: e.target.value })}
                        placeholder="Paste or click a decision above"
                        className="w-full bg-surface border border-default rounded-lg px-2.5 py-1.5 text-xs font-mono text-primary placeholder:text-tertiary/40 focus:outline-none focus:ring-1 focus:ring-accent-emerald"
                      />
                    </div>
                  </div>

                  {form.overrideType === 'gate' && (
                    <div className="flex flex-wrap gap-4">
                      <div className="flex-1 min-w-[200px]">
                        <label className="block text-[10px] font-semibold uppercase tracking-wider text-tertiary mb-1">Gate Name</label>
                        <input
                          type="text"
                          value={form.gateName}
                          onChange={(e) => updateForm({ gateName: e.target.value })}
                          className="w-full bg-surface border border-default rounded-lg px-2.5 py-1.5 text-xs font-mono text-primary focus:outline-none focus:ring-1 focus:ring-accent-emerald"
                        />
                      </div>
                      <div className="flex-1 min-w-[200px]">
                        <label className="block text-[10px] font-semibold uppercase tracking-wider text-tertiary mb-1">Gate Should Pass?</label>
                        <select
                          value={form.gateValue ? 'true' : 'false'}
                          onChange={(e) => updateForm({ gateValue: e.target.value === 'true' })}
                          className="w-full bg-surface border border-default rounded-lg px-2.5 py-1.5 text-xs text-primary focus:outline-none focus:ring-1 focus:ring-accent-emerald"
                        >
                          <option value="true">Yes (pass)</option>
                          <option value="false">No (block)</option>
                        </select>
                      </div>
                    </div>
                  )}

                  {form.overrideType === 'probability' && (
                    <div className="flex flex-wrap gap-4">
                      <div className="flex-1">
                        <label className="block text-[10px] font-semibold uppercase tracking-wider text-tertiary mb-1">P(Long)</label>
                        <input type="number" step="0.01" min="0" max="1" value={form.probLong}
                          onChange={(e) => updateForm({ probLong: e.target.value })}
                          className="w-full bg-surface border border-default rounded-lg px-2.5 py-1.5 text-xs font-mono text-primary focus:outline-none focus:ring-1 focus:ring-accent-emerald" />
                      </div>
                      <div className="flex-1">
                        <label className="block text-[10px] font-semibold uppercase tracking-wider text-tertiary mb-1">P(Short)</label>
                        <input type="number" step="0.01" min="0" max="1" value={form.probShort}
                          onChange={(e) => updateForm({ probShort: e.target.value })}
                          className="w-full bg-surface border border-default rounded-lg px-2.5 py-1.5 text-xs font-mono text-primary focus:outline-none focus:ring-1 focus:ring-accent-emerald" />
                      </div>
                      <div className="flex-1">
                        <label className="block text-[10px] font-semibold uppercase tracking-wider text-tertiary mb-1">P(Neutral)</label>
                        <input type="number" step="0.01" min="0" max="1" value={form.probNeutral}
                          onChange={(e) => updateForm({ probNeutral: e.target.value })}
                          className="w-full bg-surface border border-default rounded-lg px-2.5 py-1.5 text-xs font-mono text-primary focus:outline-none focus:ring-1 focus:ring-accent-emerald" />
                      </div>
                    </div>
                  )}

                  {form.overrideType === 'signal' && (
                    <div className="flex-1 min-w-[200px]">
                      <label className="block text-[10px] font-semibold uppercase tracking-wider text-tertiary mb-1">Signal Value</label>
                      <select value={form.signalValue} onChange={(e) => updateForm({ signalValue: e.target.value })}
                        className="w-full bg-surface border border-default rounded-lg px-2.5 py-1.5 text-xs text-primary focus:outline-none focus:ring-1 focus:ring-accent-emerald">
                        <option value="BUY">BUY</option>
                        <option value="SELL">SELL</option>
                        <option value="HOLD">HOLD</option>
                      </select>
                    </div>
                  )}

                  {form.overrideType === 'sltp' && (
                    <div className="flex flex-wrap gap-4">
                      <div className="flex-1">
                        <label className="block text-[10px] font-semibold uppercase tracking-wider text-tertiary mb-1">Stop Loss</label>
                        <input type="number" step="0.00001" value={form.slValue}
                          onChange={(e) => updateForm({ slValue: e.target.value })}
                          placeholder="Leave blank to keep original"
                          className="w-full bg-surface border border-default rounded-lg px-2.5 py-1.5 text-xs font-mono text-primary placeholder:text-tertiary/40 focus:outline-none focus:ring-1 focus:ring-accent-emerald" />
                      </div>
                      <div className="flex-1">
                        <label className="block text-[10px] font-semibold uppercase tracking-wider text-tertiary mb-1">Take Profit</label>
                        <input type="number" step="0.00001" value={form.tpValue}
                          onChange={(e) => updateForm({ tpValue: e.target.value })}
                          placeholder="Leave blank to keep original"
                          className="w-full bg-surface border border-default rounded-lg px-2.5 py-1.5 text-xs font-mono text-primary placeholder:text-tertiary/40 focus:outline-none focus:ring-1 focus:ring-accent-emerald" />
                      </div>
                    </div>
                  )}

                  <button
                    type="button"
                    onClick={handleRun}
                    disabled={!form.decisionId || cfMutation.isPending}
                    className="inline-flex items-center gap-2 px-4 py-2 rounded-lg bg-accent-emerald text-white text-xs font-semibold hover:bg-accent-emerald/90 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
                  >
                    {cfMutation.isPending ? (
                      <span className="w-3.5 h-3.5 border-2 border-white/30 border-t-white rounded-full animate-spin" />
                    ) : (
                      <Play className="w-3.5 h-3.5" strokeWidth={2} />
                    )}
                    Run Counterfactual
                  </button>

                  {cfMutation.isError && (
                    <div className="flex items-center gap-2 text-signal-short text-xs bg-signal-short/5 border border-signal-short/20 rounded-lg px-3 py-2">
                      <AlertCircle className="w-3.5 h-3.5 shrink-0" strokeWidth={2} />
                      {cfMutation.error instanceof Error ? cfMutation.error.message : 'Unknown error'}
                    </div>
                  )}

                  {cfMutation.isSuccess && result && (
                    <div className="flex items-center gap-2 text-accent-emerald text-xs bg-accent-emerald/5 border border-accent-emerald/20 rounded-lg px-3 py-2">
                      <CheckCircle className="w-3.5 h-3.5 shrink-0" strokeWidth={2} />
                      {result}
                    </div>
                  )}
                </div>
              </Panel>
            </EntranceAnimator>
          </Section>
        </Stagger>
      </div>
    </PageShell>
  )
}
