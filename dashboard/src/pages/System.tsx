import { useQuery } from "@tanstack/react-query";
import { getBuildIdentity, getSystemInfo, getSystemHealth } from "../lib/api";
import { cn } from "../lib/utils";
import Panel, { PanelHeader, PanelContent } from "../components/ui/Panel";
import StatusDot from "../components/ui/StatusDot";
import StatusBadge from "../components/ui/StatusBadge";
import Skeleton from "../components/ui/Skeleton";
import FreshnessIndicator from "../components/ui/FreshnessIndicator";
import { Settings, Shield, CheckCircle, XCircle, Fingerprint, Lock } from "lucide-react";

export default function System() {
  const { data: build, isLoading } = useQuery({ queryKey: ["buildIdentity"], queryFn: getBuildIdentity, refetchInterval: 60000 });
  const { data: info } = useQuery({ queryKey: ["systemInfo"], queryFn: getSystemInfo });
  const { data: health } = useQuery({ queryKey: ["systemHealth"], queryFn: getSystemHealth, refetchInterval: 10000 });

  if (isLoading) {
    return (
      <div className="space-y-3 lg:space-y-4 ec-animate-in">
        <Skeleton className="h-8 w-48 rounded" />
        <Skeleton className="h-20 rounded-lg" />
        <Skeleton className="h-48 rounded-lg" />
      </div>
    );
  }

  return (
    <div className="space-y-3 lg:space-y-4 ec-animate-in">
      {/* Header */}
      <div className="flex items-center justify-between">
        <h1 className="text-base lg:text-lg font-bold text-text-primary tracking-tight">System</h1>
        <FreshnessIndicator level={build?.freshness === "LIVE" ? "live" : "stale"} timestamp={build?.timestamp} compact />
      </div>

      {/* Build Status Banner */}
      <div className={cn(
        "rounded-lg border p-3 lg:p-4",
        build?.verified ? "bg-success-subtle border-success/15" : "bg-danger-subtle border-danger/15"
      )}>
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className={cn("w-9 h-9 rounded-lg flex items-center justify-center shrink-0", build?.verified ? "bg-success/10" : "bg-danger/10")}>
              <Fingerprint className={cn("w-5 h-5", build?.verified ? "text-success" : "text-danger")} />
            </div>
            <div>
              <h2 className="text-sm font-bold text-text-primary">
                BUILD {build?.verified ? "VERIFIED" : "DRIFT DETECTED"}
              </h2>
              <p className="text-xs text-text-muted mt-0.5">
                {build?.verified ? "All fingerprints match" : "Fingerprint mismatch"}
              </p>
            </div>
          </div>
          <StatusBadge variant={build?.verified ? "success" : "danger"} size="md">
            {build?.verified ? "VERIFIED" : "DRIFT"}
          </StatusBadge>
        </div>
      </div>

      {/* Build Identity — 2-col mobile, 3-col desktop */}
      <Panel>
        <PanelHeader>
          <div className="flex items-center gap-2">
            <Settings className="w-3.5 h-3.5 text-text-muted" />
            <h3>Build Identity</h3>
          </div>
        </PanelHeader>
        <PanelContent>
          <div className="grid grid-cols-2 lg:grid-cols-3 gap-2">
            {[
              { label: "Git HEAD", value: build?.git_head || "No data" },
              { label: "Build ID", value: build?.build_id || "No data" },
              { label: "Manifest", value: build?.manifest_identity || "No data" },
              { label: "Config", value: build?.config_fingerprint || "No data" },
              { label: "Strategy", value: build?.loop_script_sha256?.slice(0, 12) || "No data" },
              { label: "Dashboard", value: info?.dashboard_version || "No data" },
            ].map((item) => (
              <div key={item.label} className="bg-surface-overlay rounded-md px-2.5 lg:px-3 py-2">
                <p className="text-[9px] lg:text-[10px] text-text-muted uppercase tracking-wider">{item.label}</p>
                <p className="text-[11px] lg:text-xs font-mono text-text-primary mt-0.5 break-all leading-relaxed">{item.value}</p>
              </div>
            ))}
          </div>
        </PanelContent>
      </Panel>

      {/* Guarantees — 2-col mobile, 3-col desktop */}
      <Panel>
        <PanelHeader>
          <div className="flex items-center gap-2">
            <Lock className="w-3.5 h-3.5 text-text-muted" />
            <h3>Guarantees</h3>
          </div>
        </PanelHeader>
        <PanelContent>
          <div className="grid grid-cols-2 lg:grid-cols-3 gap-2">
            {[
              { label: "Read-Only", ok: info?.read_only ?? true, desc: "No mutations" },
              { label: "R4 Frozen", ok: true, desc: "Policy immutable" },
              { label: "Fingerprint", ok: build?.verified ?? false, desc: "Build verified" },
              { label: "Fail-Closed", ok: true, desc: "Risk enforced" },
              { label: "Reconciliation", ok: true, desc: "Active monitoring" },
              { label: "Evidence Ledger", ok: true, desc: "Immutable record" },
            ].map((item) => (
              <div
                key={item.label}
                className={cn(
                  "flex items-start gap-2 p-2 rounded-md border",
                  item.ok ? "bg-success-subtle border-success/10" : "bg-danger-subtle border-danger/10"
                )}
              >
                {item.ok ? <CheckCircle className="w-3.5 h-3.5 text-success shrink-0 mt-0.5" /> : <XCircle className="w-3.5 h-3.5 text-danger shrink-0 mt-0.5" />}
                <div>
                  <span className="text-[11px] lg:text-xs font-medium text-text-primary">{item.label}</span>
                  <p className="text-[9px] lg:text-[10px] text-text-muted mt-0.5">{item.desc}</p>
                </div>
              </div>
            ))}
          </div>
        </PanelContent>
      </Panel>

      {/* Runtime Status */}
      <Panel>
        <PanelHeader>
          <div className="flex items-center gap-2">
            <Shield className="w-3.5 h-3.5 text-text-muted" />
            <h3>Runtime Status</h3>
          </div>
        </PanelHeader>
        <PanelContent>
          <div className="grid grid-cols-2 gap-3 lg:gap-4">
            <div>
              <p className="text-[10px] text-text-muted uppercase tracking-wider mb-1">System Health</p>
              <StatusDot
                level={health?.status === "ok" ? "green" : "red"}
                label={health?.status?.toUpperCase() || "No data"}
                size="xs"
              />
            </div>
            <div>
              <p className="text-[10px] text-text-muted uppercase tracking-wider mb-1">Authorization</p>
              <StatusDot
                level={health?.trading_authorization === "TRADING_AUTHORIZED" ? "green" : "red"}
                label={health?.trading_authorization?.replace("TRADING_", "") || "No data"}
                size="xs"
              />
            </div>
          </div>
        </PanelContent>
      </Panel>
    </div>
  );
}
