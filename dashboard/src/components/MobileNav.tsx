import { Link, useLocation } from "react-router-dom";
import {
  LayoutDashboard,
  Briefcase,
  Shield,
  Activity,
  FileText,
  Layers,
  AlertTriangle,
  Settings,
} from "lucide-react";
import { cn } from "../lib/utils";

const navItems = [
  { path: "/", label: "Overview", icon: LayoutDashboard },
  { path: "/positions", label: "Positions", icon: Briefcase },
  { path: "/risk", label: "Risk", icon: Shield },
  { path: "/evidence", label: "Evidence", icon: FileText },
  { path: "/events", label: "Events", icon: Layers },
  { path: "/alerts", label: "Alerts", icon: AlertTriangle },
  { path: "/reconciliation", label: "Recon", icon: Activity },
  { path: "/system", label: "System", icon: Settings },
];

// Show top 5 on mobile bottom bar, rest in overflow
const primaryNav = navItems.slice(0, 5);
const secondaryNav = navItems.slice(5);

export default function MobileNav() {
  const location = useLocation();

  const isActive = (path: string) =>
    path === "/" ? location.pathname === "/" : location.pathname.startsWith(path);

  return (
    <>
      {/* Bottom nav bar — mobile only */}
      <nav className="lg:hidden fixed bottom-0 inset-x-0 z-40 bg-surface-raised border-t border-border-primary safe-area-bottom">
        <div className="flex items-center justify-around h-14">
          {primaryNav.map((item) => {
            const active = isActive(item.path);
            return (
              <Link
                key={item.path}
                to={item.path}
                className={cn(
                  "flex flex-col items-center gap-0.5 px-2 py-1 min-w-[48px] min-h-[44px] justify-center rounded-md transition-colors",
                  active ? "text-success" : "text-text-muted"
                )}
              >
                <item.icon className="w-5 h-5" />
                <span className="text-[9px] font-medium leading-tight">{item.label}</span>
              </Link>
            );
          })}
          {/* More menu — shows remaining nav items */}
          <div className="relative group">
            <button className="flex flex-col items-center gap-0.5 px-2 py-1 min-w-[48px] min-h-[44px] justify-center rounded-md text-text-muted transition-colors">
              <Settings className="w-5 h-5" />
              <span className="text-[9px] font-medium leading-tight">More</span>
            </button>
            {/* Dropdown */}
            <div className="invisible group-hover:visible group-focus-within:visible absolute bottom-full right-0 mb-2 w-44 bg-surface-overlay border border-border-primary rounded-lg shadow-xl overflow-hidden">
              {secondaryNav.map((item) => {
                const active = isActive(item.path);
                return (
                  <Link
                    key={item.path}
                    to={item.path}
                    className={cn(
                      "flex items-center gap-2.5 px-3 py-2.5 text-xs transition-colors",
                      active ? "bg-success/8 text-success" : "text-text-secondary hover:bg-surface-hover"
                    )}
                  >
                    <item.icon className="w-3.5 h-3.5" />
                    <span>{item.label}</span>
                  </Link>
                );
              })}
            </div>
          </div>
        </div>
      </nav>

      {/* Spacer for bottom nav on mobile */}
      <div className="lg:hidden h-14" />
    </>
  );
}
