import { useQuery } from "@tanstack/react-query";
import { getQualification, getShadowReduced } from "../lib/api";
import { formatCurrency, cn } from "../lib/utils";
import Panel, { PanelHeader, PanelContent } from "../components/ui/Panel";
import StatusDot from "../components/ui/StatusDot";
import StatusBadge from "../components/ui/StatusBadge";
import Skeleton from "../components/ui/Skeleton";
import FreshnessIndicator from "../components/ui/FreshnessIndicator";
import { AlertTriangle, CheckCircle, FlaskConical, AlertOctagon } from "lucide-react";

export default function Evidence() {
  const { data: qual, isLoading } = useQuery({ queryKey: ["qualification"], queryFn: getQualification, refetchInterval: 30000 });
  const { data: shadow } = useQuery({ queryKey: ["shadowReduced"], queryFn: getShadowReduced, refetchInterval: 30000 });

  if (isLoading) {
    return (
      <div className="space-y-3 lg:space-y-4 ec-animate-in">
        <Skeleton className="h-8 w-48 rounded" />
        <Skeleton className="h-16 rounded-lg" />
        <Skeleton className="h-48 rounded-lg" />
      </div>
    );
  }

  const maturity = qual?.evidence_maturity;

  return (
    <div className="space-y-3 lg:space-y-4 ec-animate-in">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <h1 className="text-base lg:text-lg font-bold text-text-primary tracking-tight">Evidence</h1>
          <span className="text-[11px] text-text-muted font-mono hidden sm:inline">Campaign: {qual?.campaign_id || "No data"}</span>
        </div>
        <FreshnessIndicator level={qual?.freshness === "LIVE" ? "live" : "stale"} timestamp={qual?.timestamp} compact />
      </div>

      {/* Campaign Status */}
      <div className={cn(
        "rounded-lg border p-3 lg:p-4",
        qual?.evidence_insufficient ? "bg-warning-subtle border-warning/15" : "bg-success-subtle border-success/15"
      )}>
        <div className="flex items-center gap-3">
          {qual?.evidence_insufficient ? <AlertTriangle className="w-5 h-5 text-warning shrink-0" /> : <CheckCircle className="w-5 h-5 text-success shrink-0" />}
          <div>
            <div className="flex items-center gap-2">
              <h2 className="text-sm font-bold text-text-primary">{qual?.overall_status || "No data"}</h2>
              <StatusBadge variant={qual?.evidence_insufficient ? "warning" : "success"} size="sm">
                {qual?.evidence_insufficient ? "COLLECTING" : "SUFFICIENT"}
              </StatusBadge>
            </div>
            <p className="text-xs text-text-muted mt-0.5">
              {qual?.evidence_insufficient ? "Evidence still accumulating" : "Evidence sufficient — all criteria met"}
            </p>
          </div>
        </div>
      </div>

      {/* Evidence Maturity */}
      <Panel>
        <PanelHeader>
          <div className="flex items-center gap-2">
            <FlaskConical className="w-3.5 h-3.5 text-text-muted" />
            <h3>Evidence Maturity</h3>
          </div>
          <span className="text-[10px] text-text-muted font-mono">
            {maturity?.total_trades || 0} trades · {maturity?.completed_lifecycles || 0} lifecycles
          </span>
        </PanelHeader>
        <PanelContent>
          {/* Progression bar */}
          <div className="flex items-center gap-px mb-3">
            {["E0", "E1", "E2", "E3", "E4", "E5", "E6"].map((e, i) => {
              const count = maturity?.[`e${i}_count` as keyof typeof maturity] as number || 0;
              return (
                <div key={e} className="flex-1 relative group">
                  <div className={cn("h-1.5 transition-colors", i === 0 && "rounded-l", i === 6 && "rounded-r", count > 0 ? "bg-success" : "bg-surface-overlay")} />
                </div>
              );
            })}
          </div>
          <div className="flex justify-between text-[8px] sm:text-[9px] text-text-muted font-mono mb-3 px-0.5">
            <span>E0</span><span>E1</span><span>E2</span><span>E3</span><span>E4</span><span>E5</span><span>E6</span>
          </div>

          {/* Maturity grid — 4-col mobile, 8-col desktop */}
          <div className="grid grid-cols-4 lg:grid-cols-8 gap-px bg-border-subtle rounded overflow-hidden">
            {[
              { label: "E0", sub: "Signal", value: maturity?.e0_count || 0 },
              { label: "E1", sub: "Exec", value: maturity?.e1_count || 0 },
              { label: "E2", sub: "Entry", value: maturity?.e2_count || 0 },
              { label: "E3", sub: "Hold", value: maturity?.e3_count || 0 },
              { label: "E4", sub: "Exit", value: maturity?.e4_count || 0 },
              { label: "E5", sub: "Risk", value: maturity?.e5_count || 0 },
              { label: "E6", sub: "Port", value: maturity?.e6_count || 0 },
              { label: "Days", sub: "Obs", value: maturity?.observation_days || 0 },
            ].map((item) => (
              <div key={item.label} className="bg-surface-raised px-2 lg:px-3 py-2">
                <p className="text-[8px] lg:text-[9px] text-text-muted uppercase tracking-wider">{item.label}</p>
                <p className="text-xs lg:text-sm font-semibold ec-num text-text-primary mt-0.5">{item.value}</p>
                <p className="text-[8px] lg:text-[9px] text-text-muted hidden sm:block">{item.sub}</p>
              </div>
            ))}
          </div>
        </PanelContent>
      </Panel>

      {/* Qualification Gates */}
      {qual?.gates && qual.gates.length > 0 && (
        <Panel>
          <PanelHeader>
            <div className="flex items-center gap-2">
              <AlertTriangle className="w-3.5 h-3.5 text-text-muted" />
              <h3>Qualification Gates</h3>
            </div>
          </PanelHeader>
          <PanelContent noPadding>
            <div className="divide-y divide-border-subtle">
              {qual.gates.map((gate) => {
                const level = gate.status === "PASS" ? "green" : gate.status === "FAIL" ? "red" : "yellow";
                return (
                  <div key={gate.gate_id} className="px-3 lg:px-4 py-2.5 lg:py-3 hover:bg-surface-hover transition-colors">
                    <div className="flex items-center justify-between mb-2">
                      <div className="flex items-center gap-2 min-w-0">
                        <span className="text-xs font-medium text-text-primary">{gate.gate_id}</span>
                        <span className="text-xs text-text-muted">—</span>
                        <span className="text-xs text-text-secondary truncate">{gate.name}</span>
                      </div>
                      <div className="shrink-0"><StatusDot level={level} label={gate.status} size="xs" /></div>
                    </div>
                    <div className="h-1 rounded-full bg-surface-overlay overflow-hidden">
                      <div
                        className={cn("h-full rounded-full transition-all duration-700", gate.status === "PASS" ? "bg-success" : gate.status === "FAIL" ? "bg-danger" : "bg-warning")}
                        style={{ width: gate.status === "PASS" || gate.status === "FAIL" ? "100%" : "50%" }}
                      />
                    </div>
                  </div>
                );
              })}
            </div>
          </PanelContent>
        </Panel>
      )}

      {/* Shadow REDUCED */}
      <Panel accent="purple">
        <PanelHeader>
          <div className="flex items-center gap-2">
            <AlertOctagon className="w-3.5 h-3.5 text-purple" />
            <h3 className="!text-purple">Shadow REDUCED</h3>
          </div>
          <StatusBadge variant="purple" size="sm">NOT APPLIED LIVE</StatusBadge>
        </PanelHeader>
        <PanelContent>
          <div className="grid grid-cols-2 lg:grid-cols-4 gap-2 lg:gap-3">
            {[
              { label: "Observations", value: String(shadow?.observations || 0), color: "text-purple" as const },
              { label: "Reductions", value: String(shadow?.hypothetical_reductions || 0), color: "text-purple" as const },
              { label: "Actual P&L", value: shadow?.actual_pnl ? formatCurrency(shadow.actual_pnl) : "No data", color: "text-success" as const },
              { label: "Hypothetical", value: shadow?.hypothetical_pnl ? formatCurrency(shadow.hypothetical_pnl) : "No data", color: "text-purple" as const },
            ].map((item) => (
              <div key={item.label} className="bg-purple-subtle rounded-md px-3 py-2">
                <p className="text-[10px] text-purple/60 uppercase tracking-wider">{item.label}</p>
                <p className={cn("text-sm font-semibold ec-num mt-1", item.color)}>{item.value}</p>
              </div>
            ))}
          </div>
        </PanelContent>
      </Panel>
    </div>
  );
}
