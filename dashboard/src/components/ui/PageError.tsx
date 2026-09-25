import ErrorState from "./ErrorState";

interface PageErrorProps {
  /** Page title — also used for the h1 (one h1 per route). */
  title: string;
  /** Endpoint that failed, e.g. "GET /alerts". */
  subsystem: string;
  onRetry: () => void;
}

/**
 * Full-page query failure. Renders an honest error state instead of letting
 * the page fall through to "no data" copy that reads as success
 * (contract T3: unknown ≠ zero/normal; audit: isError never handled).
 */
export default function PageError({ title, subsystem, onRetry }: PageErrorProps) {
  return (
    <div className="space-y-3 lg:space-y-4 ec-animate-in">
      <h1 className="text-base lg:text-lg font-bold text-text-primary tracking-tight">{title}</h1>
      <div className="rounded-lg border border-border-primary bg-surface-raised">
        <ErrorState
          message={`Could not load ${title.toLowerCase()} — the dashboard API did not respond, so no values are shown because none were observed.`}
          subsystem={subsystem}
          retryAction={onRetry}
        />
      </div>
    </div>
  );
}
