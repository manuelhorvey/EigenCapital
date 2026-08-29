import { Link, useLocation } from "react-router-dom";
import { useRef, useEffect, useState } from "react";
import {
  LayoutDashboard,
  Briefcase,
  Shield,
  Activity,
  FileText,
  Layers,
  AlertTriangle,
  Settings,
  ChevronUp,
  ChevronDown,
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

const primaryNav = navItems.slice(0, 5);
const secondaryNav = navItems.slice(5);

export default function MobileNav() {
  const location = useLocation();
  const moreRef = useRef<HTMLDivElement>(null);
  const [moreOpen, setMoreOpen] = useState(false);

  const isActive = (path: string) =>
    path === "/" ? location.pathname === "/" : location.pathname.startsWith(path);

  useEffect(() => {
    const handleClickOutside = (e: MouseEvent) => {
      if (moreRef.current && !moreRef.current.contains(e.target as Node)) {
        setMoreOpen(false);
      }
    };
    document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, []);

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Escape") {
      setMoreOpen(false);
      (moreRef.current?.querySelector("button") as HTMLButtonElement)?.focus();
    }
  };

  return (
    <>
      {/* Bottom nav bar — mobile only */}
      <nav
        className="lg:hidden fixed bottom-0 inset-x-0 z-40 bg-surface-raised border-t border-border-primary safe-area-bottom"
        onKeyDown={handleKeyDown}
      >
        <div className="flex items-center justify-around h-14">
          {primaryNav.map((item) => {
            const active = isActive(item.path);
            return (
              <Link
                key={item.path}
                to={item.path}
                className={cn(
                  "flex flex-col items-center gap-0.5 px-2 py-1 min-w-[48px] min-h-[44px] justify-center rounded-md transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-success focus-visible:ring-offset-2 focus-visible:ring-offset-surface-base",
                  active ? "text-success" : "text-text-muted"
                )}
                aria-current={active ? "page" : undefined}
              >
                <item.icon className="w-5 h-5" aria-hidden="true" />
                <span className="text-[9px] font-medium leading-tight">{item.label}</span>
              </Link>
            );
          })}
          {/* More menu — shows remaining nav items */}
          <div className="relative group" ref={moreRef}>
            <button
              className="flex flex-col items-center gap-0.5 px-2 py-1 min-w-[48px] min-h-[44px] justify-center rounded-md text-text-muted transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-success focus-visible:ring-offset-2 focus-visible:ring-offset-surface-base"
              onClick={() => setMoreOpen(!moreOpen)}
              aria-expanded={moreOpen}
              aria-haspopup="true"
              aria-label="More navigation options"
            >
              <Settings className="w-5 h-5" aria-hidden="true" />
              <span className="text-[9px] font-medium leading-tight">More</span>
              {moreOpen ? <ChevronUp className="w-3 h-3" /> : <ChevronDown className="w-3 h-3" />}
            </button>
            {/* Dropdown */}
            <div
              className={cn(
                "absolute bottom-full right-0 mb-2 w-44 bg-surface-overlay border border-border-primary rounded-lg shadow-xl overflow-hidden",
                moreOpen ? "visible opacity-100" : "invisible opacity-0"
              )}
              role="menu"
            >
              {secondaryNav.map((item) => {
                const active = isActive(item.path);
                return (
                  <Link
                    key={item.path}
                    to={item.path}
                    className={cn(
                      "flex items-center gap-2.5 px-3 py-2.5 text-xs transition-colors focus-visible:outline-none focus-visible:bg-surface-hover",
                      active ? "bg-success/8 text-success" : "text-text-secondary hover:bg-surface-hover"
                    )}
                    role="menuitem"
                    onClick={() => setMoreOpen(false)}
                    aria-current={active ? "page" : undefined}
                  >
                    <item.icon className="w-3.5 h-3.5" aria-hidden="true" />
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
