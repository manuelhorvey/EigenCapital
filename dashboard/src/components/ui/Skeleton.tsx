import { cn } from "../../lib/utils";

interface SkeletonProps {
  className?: string;
}

export default function Skeleton({ className }: SkeletonProps) {
  return <div className={cn("ec-skeleton", className)} />;
}

export function SkeletonLine({ className }: SkeletonProps) {
  return <div className={cn("ec-skeleton h-3.5 rounded", className || "w-3/4")} />;
}

export function SkeletonCard() {
  return (
    <div className="ec-panel p-4 space-y-3">
      <SkeletonLine className="w-20 h-2.5" />
      <SkeletonLine className="w-32 h-6" />
      <SkeletonLine className="w-24 h-2.5" />
    </div>
  );
}

export function SkeletonTable({ rows = 5 }: { rows?: number }) {
  return (
    <div className="ec-panel">
      <div className="p-4 space-y-2">
        {/* Header */}
        <div className="flex gap-4 pb-2 border-b border-border-subtle">
          {[100, 60, 80, 80, 120, 80].map((w, i) => (
            <div key={i} className="ec-skeleton h-2.5 rounded" style={{ width: w }} />
          ))}
        </div>
        {/* Rows */}
        {Array.from({ length: rows }).map((_, i) => (
          <div key={i} className="flex gap-4 py-2">
            {[80, 50, 60, 70, 100, 60].map((w, j) => (
              <div key={j} className="ec-skeleton h-3 rounded" style={{ width: w }} />
            ))}
          </div>
        ))}
      </div>
    </div>
  );
}
