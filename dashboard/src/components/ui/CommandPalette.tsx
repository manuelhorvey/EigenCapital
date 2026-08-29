import { useState, useEffect, useCallback, useRef } from "react";
import { useNavigate, useLocation } from "react-router-dom";
import { cn } from "../../lib/utils";
import {
  LayoutDashboard,
  Briefcase,
  Shield,
  Activity,
  FileText,
  Layers,
  AlertTriangle,
  Settings,
  Search,
  X,
} from "lucide-react";

const commands = [
  { path: "/", label: "Overview", icon: LayoutDashboard, group: "Operations" },
  { path: "/positions", label: "Positions", icon: Briefcase, group: "Operations" },
  { path: "/risk", label: "Risk", icon: Shield, group: "Operations" },
  { path: "/reconciliation", label: "Reconciliation", icon: Activity, group: "Operations" },
  { path: "/evidence", label: "Evidence", icon: FileText, group: "Evidence" },
  { path: "/events", label: "Events", icon: Layers, group: "Evidence" },
  { path: "/alerts", label: "Alerts", icon: AlertTriangle, group: "System" },
  { path: "/system", label: "System", icon: Settings, group: "System" },
];

export default function CommandPalette() {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [selectedIdx, setSelectedIdx] = useState(0);
  const inputRef = useRef<HTMLInputElement>(null);
  const navigate = useNavigate();
  const location = useLocation();

  const filtered = commands.filter(
    (c) => c.label.toLowerCase().includes(query.toLowerCase())
  );

  const handleQueryChange = (value: string) => {
    setQuery(value);
    setSelectedIdx(0);
  };

  const handleOpen = useCallback(() => {
    setOpen(true);
    setQuery("");
    setSelectedIdx(0);
  }, []);

  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key === "k") {
        e.preventDefault();
        handleOpen();
      }
      if (e.key === "Escape") setOpen(false);
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [handleOpen]);

  useEffect(() => {
    if (open) inputRef.current?.focus();
  }, [open]);



  const select = (path: string) => {
    navigate(path);
    setOpen(false);
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "ArrowDown") {
      e.preventDefault();
      setSelectedIdx((i) => Math.min(i + 1, filtered.length - 1));
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setSelectedIdx((i) => Math.max(i - 1, 0));
    } else if (e.key === "Enter" && filtered[selectedIdx]) {
      select(filtered[selectedIdx].path);
    }
  };

  if (!open) {
    return (
      <button
        onClick={handleOpen}
        className="flex items-center gap-2 px-3 py-1.5 text-xs text-text-muted bg-surface-overlay border border-border-primary rounded-lg hover:bg-surface-hover hover:text-text-secondary transition-colors"
        title="Command palette (⌘K)"
      >
        <Search className="w-3 h-3" />
        <span className="hidden sm:inline">Navigate</span>
        <kbd className="hidden sm:inline text-[10px] font-mono bg-surface-base border border-border-primary px-1 py-0.5 rounded">⌘K</kbd>
      </button>
    );
  }

  return (
    <div className="fixed inset-0 z-50 flex items-start justify-center pt-[15vh]">
      {/* Backdrop */}
      <div className="absolute inset-0 bg-black/60" onClick={() => setOpen(false)} />

      {/* Dialog */}
      <div className="relative w-full max-w-md mx-4 bg-surface-raised border border-border-primary rounded-xl shadow-2xl overflow-hidden">
        {/* Search input */}
        <div className="flex items-center gap-3 px-4 py-3 border-b border-border-subtle">
          <Search className="w-4 h-4 text-text-muted shrink-0" />
          <input
            ref={inputRef}
            type="text"
            value={query}
            onChange={(e) => handleQueryChange(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder="Navigate to..."
            className="flex-1 bg-transparent text-sm text-text-primary placeholder:text-text-muted outline-none"
          />
          <button onClick={() => setOpen(false)} className="text-text-muted hover:text-text-secondary">
            <X className="w-4 h-4" />
          </button>
        </div>

        {/* Results */}
        <div className="max-h-64 overflow-y-auto py-1">
          {filtered.length === 0 && (
            <div className="px-4 py-6 text-center text-xs text-text-muted">No results</div>
          )}
          {filtered.map((cmd, idx) => {
            const isActive = location.pathname === cmd.path;
            const Icon = cmd.icon;
            return (
              <button
                key={cmd.path}
                onClick={() => select(cmd.path)}
                className={cn(
                  "w-full flex items-center gap-3 px-4 py-2.5 text-left transition-colors",
                  idx === selectedIdx && "bg-surface-hover",
                  isActive && "bg-surface-overlay"
                )}
              >
                <Icon className={cn("w-4 h-4 shrink-0", isActive ? "text-success" : "text-text-muted")} />
                <div className="flex-1 min-w-0">
                  <span className={cn("text-sm", isActive ? "text-success font-medium" : "text-text-primary")}>
                    {cmd.label}
                  </span>
                  <span className="text-[10px] text-text-muted ml-2">{cmd.group}</span>
                </div>
                {isActive && <span className="text-[10px] text-success font-medium">current</span>}
              </button>
            );
          })}
        </div>
      </div>
    </div>
  );
}
