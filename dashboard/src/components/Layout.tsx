import { Link, Outlet, useLocation } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import {
  LayoutDashboard,
  Briefcase,
  Shield,
  Activity,
  AlertTriangle,
  FileText,
  Layers,
  Settings,
} from "lucide-react";
import { getSystemHealth } from "../lib/api";
import { cn } from "../lib/utils";
import StatusDot from "./ui/StatusDot";
import CommandPalette from "./ui/CommandPalette";
import MobileNav from "./MobileNav";
import LiveConnectionIndicator from "./LiveConnectionIndicator";
import { ErrorBoundary } from "./ErrorBoundary";

interface NavGroup {
  label: string;
  items: NavItem[];
}

interface NavItem {
  path: string;
  label: string;
  icon: typeof LayoutDashboard;
}

const navGroups: NavGroup[] = [
  {
    label: "Operations",
    items: [
      { path: "/", label: "Overview", icon: LayoutDashboard },
      { path: "/positions", label: "Positions", icon: Briefcase },
      { path: "/risk", label: "Risk", icon: Shield },
      { path: "/reconciliation", label: "Reconciliation", icon: Activity },
      { path: "/alerts", label: "Alerts", icon: AlertTriangle },
    ],
  },
  {
    label: "Evidence",
    items: [
      { path: "/evidence", label: "Qualification", icon: FileText },
      { path: "/events", label: "Events", icon: Layers },
    ],
  },
  {
    label: "System",
    items: [{ path: "/system", label: "System", icon: Settings }],
  },
];

export default function Layout() {
  const location = useLocation();
  const { data: systemHealth } = useQuery({
    queryKey: ["systemHealth"],
    queryFn: getSystemHealth,
    refetchInterval: 10000,
  });

  const isAuthorized = systemHealth?.trading_authorization === "TRADING_AUTHORIZED";

  const isActive = (path: string) =>
    path === "/" ? location.pathname === "/" : location.pathname.startsWith(path);

  return (
    <div className="flex h-screen bg-surface-base">
      <a href="#main-content" className="skip-link">
        Skip to main content
      </a>
      <CommandPalette />

      {/* ═══ Desktop Sidebar ═══ */}
      <aside className="hidden lg:flex w-[220px] shrink-0 flex-col bg-surface-base border-r border-border-primary">
        {/* Brand */}
        <div className="px-4 py-4 border-b border-border-subtle">
          <div className="flex items-center gap-2.5">
            <div className="w-7 h-7 rounded-md bg-success/10 border border-success/20 flex items-center justify-center">
              <Shield className="w-3.5 h-3.5 text-success" />
            </div>
            <div className="min-w-0">
              <h1 className="text-xs font-bold text-text-primary tracking-tight truncate">EigenCapital</h1>
              <p className="text-[9px] text-text-muted uppercase tracking-wider">Operations</p>
            </div>
          </div>
        </div>

        {/* System status */}
        <div className="px-4 py-2.5 border-b border-border-subtle">
          <div className="flex items-center gap-2">
            <StatusDot level={isAuthorized ? "green" : "red"} pulse={isAuthorized} size="xs" />
            <span className={cn(
              "text-[10px] font-semibold uppercase tracking-wider",
              isAuthorized ? "text-success" : "text-danger"
            )}>
              {isAuthorized ? "LIVE" : "BLOCKED"}
            </span>
          </div>
        </div>

        {/* Navigation */}
        <nav className="flex-1 overflow-y-auto py-3 px-2">
          {navGroups.map((group) => (
            <div key={group.label} className="mb-3">
              <p className="px-2 mb-1 text-[9px] font-semibold text-text-muted uppercase tracking-widest">
                {group.label}
              </p>
              {group.items.map((item) => {
                const active = isActive(item.path);
                return (
                  <Link
                    key={item.path}
                    to={item.path}
                    className={cn(
                      "flex items-center gap-2.5 px-2.5 py-1.5 rounded-md text-xs transition-colors mb-0.5",
                      active
                        ? "bg-success/8 text-success font-medium"
                        : "text-text-muted hover:bg-surface-hover hover:text-text-secondary"
                    )}
                  >
                    <item.icon className={cn("w-3.5 h-3.5 shrink-0", active ? "text-success" : "")} />
                    <span className="truncate">{item.label}</span>
                  </Link>
                );
              })}
            </div>
          ))}
        </nav>

        {/* Footer */}
        <div className="px-4 py-3 border-t border-border-subtle">
          <div className="flex items-center gap-1.5">
            <span className="w-1.5 h-1.5 rounded-full bg-success" />
            <span className="text-[9px] text-text-muted uppercase tracking-wider">Read-only</span>
          </div>
          <LiveConnectionIndicator compact showLabel={false} className="mt-2" />
        </div>
      </aside>

      {/* ═══ Main area ═══ */}
      <div className="flex-1 flex flex-col min-w-0">
        {/* ═══ Mobile TopBar ═══ */}
        <header className="lg:hidden h-12 shrink-0 flex items-center justify-between px-4 border-b border-border-primary bg-surface-base">
          <div className="flex items-center gap-2">
            <div className="w-6 h-6 rounded bg-success/10 border border-success/20 flex items-center justify-center">
              <Shield className="w-3 h-3 text-success" />
            </div>
            <span className="text-xs font-bold text-text-primary">EigenCapital</span>
          </div>
          <div className="flex items-center gap-2">
            <StatusDot level={isAuthorized ? "green" : "red"} pulse={isAuthorized} size="xs" />
            <span className={cn(
              "text-[10px] font-semibold uppercase",
              isAuthorized ? "text-success" : "text-danger"
            )}>
              {isAuthorized ? "LIVE" : "BLOCKED"}
            </span>
          </div>
        </header>

        {/* ═══ Desktop TopBar ═══ */}
        <header className="hidden lg:flex h-11 shrink-0 items-center justify-end px-5 border-b border-border-primary bg-surface-base">
          <div className="flex items-center gap-4">
            <LiveConnectionIndicator compact={false} showLabel={true} />
            <CommandPalette />
          </div>
        </header>

        {/* ═══ Content ═══ */}
        <main id="main-content" className="flex-1 overflow-y-auto pb-0 lg:pb-0 pb-14">
          <div className="p-4 lg:p-6 max-w-[1600px] mx-auto">
            <ErrorBoundary>
              <Outlet />
            </ErrorBoundary>
          </div>
        </main>
      </div>

      {/* ═══ Mobile Bottom Nav ═══ */}
      <MobileNav />
    </div>
  );
}
