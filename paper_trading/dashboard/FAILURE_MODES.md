# EigenCapital Dashboard — Failure Mode Analysis

> Pre-mortem for the state-bundle migration. Covers what breaks, how it manifests,
> root cause, and exact mitigation — for every architectural seam in the target
> state. Written before Branch 1 so mitigations are built in, not retrofitted.

---

## How to read

Each failure mode has:

| Field | Meaning |
|-------|---------|
| **Layer** | Data / Frontend / System |
| **Manifestation** | What the user sees |
| **Root cause** | Why it happens in the architecture |
| **Mitigation** | Code-level fix |
| **Prevented by design?** | Yes / Partial / No |

---

## Layer 1: Data Layer Failures

### F1. Bundle response lag / partial response

| | |
|---|---|
| **Manifestation** | Header shows stale portfolio value for 5–30s while engine tab shows current. Metrics disagree between tabs. |
| **Root cause** | `/state-bundle.json` fetches snapshot + health + mt5 sequentially. If MT5 bridge is slow (network call to Wine process), the entire bundle stalls. A partial write (snapshot written, health not yet) causes inconsistent state. |
| **Mitigation** | **Timeout per sub-fetch, not per bundle.** In `bundle.py`, wrap each `live.*` fetch in a timeout (500ms). If MT5 times out, return `mt5: { error: "timeout", last_known: <cached> }`. Never stall the bundle on a slow sub-system. The bundle must always return within 1s. |
| **Prevented by design?** | **No** — current design serializes all fetches in the handler. Must be explicitly patched. |

### F2. Schema drift between backend and frontend

| | |
|---|---|
| **Manifestation** | Console errors: `Zod validation failed`. UI shows empty states or fallback data. No visible error to user. |
| **Root cause** | Backend adds or renames a field in the snapshot without updating the frontend Zod schema. The bundle returns valid JSON, but `EngineSnapshotSchema.safeParse()` rejects it silently — the whole tab catches `isError` and renders `ErrorScreen`. |
| **Mitigation** | **Lenient parsing with warnings.** Replace `.safeParse()` with `.passthrough()` on the bundle schema. Log schema drift to console in dev, but render whatever fields are present. A field rename should not crash the entire dashboard. Use `meta.schema_hash` in bundle: if hash changes between backend deploys, log a warning. |
| **Prevented by design?** | **Partial** — `meta.schema_hash` is defined in the contract but no enforcement logic exists yet. |

### F3. Cache staleness vs market state transitions

| | |
|---|---|
| **Manifestation** | Market closes at 17:00 ET. Dashboard still shows "LIVE" with 17:02 data for 30s. User makes a decision based on stale data. |
| **Root cause** | `refetchInterval: 5s` during market hours, 30s when closed. But the *transition* from open→closed is detected only on the *next* poll. If the engine sets `market_closed=true` at 17:00:00, the frontend won't see it until 17:00:05. Worse: if the engine clock and frontend clock skew, the transition could be missed entirely. |
| **Mitigation** | **Adaptive polling with hysteresis.** Poll every 5s always. The `market_closed` flag only affects staleTime (5s open, 30s closed). When `market_closed` transitions from `false→true`, trigger an additional immediate refetch. On the engine side, `market_closed` should be set 5min before actual close to account for last-trade timestamp. |
| **Prevented by design?** | **No** — polling interval is the only adaptation. No transition detection. |

### F4. Bundle size growth over time

| | |
|---|---|
| **Manifestation** | Dashboard loads get progressively slower over weeks. Bundle response grows from 50KB to 500KB. Mobile users time out. |
| **Root cause** | `snapshot.assets.*` grows with each new asset, each new metric field, each attached parquet blob. No pagination or field selection on the bundle endpoint. The contract says "no historical data in bundle" but does not limit *current* data size. |
| **Mitigation** | **Size budget.** Enforce a hard limit: bundle JSON must never exceed 200KB uncompressed. Add a CI check or a runtime warning in `bundle.py` that logs `WARN Bundle size: 450KB — investigate` above 150KB. If any single asset's serialized state exceeds 50KB, split it out to a lazy endpoint. |
| **Prevented by design?** | **Partial** — "no historical data" rule exists but no size enforcement. |

### F5. Sequence ID gap detection

| | |
|---|---|
| **Manifestation** | No visible symptom. Data is silently stale — engine crashed and restarted, sequence jumped from 1423 to 1, but frontend cache returns pre-crash snapshot (still at 1423) because it has no reason to invalidate. |
| **Root cause** | `meta.sequence_id` in bundle is defined but not wired into cache invalidation. React Query uses `queryKey` + `staleTime`, not sequence-based cache busting. A fresh bundle with lower sequence ID will be ignored until staleTime expires. |
| **Mitigation** | **Sequence-gated cache.** In `useSystemSnapshot`, compare `newData.meta.sequence_id` against previous value. If sequence decreased (engine restart) or jumped by >10% above expected (missed cycles), call `queryClient.setQueryDefaults` to bypass staleTime and refetch immediately. |
| **Prevented by design?** | **No** — `meta.sequence_id` defined but unused in cache logic. |

---

## Layer 2: Frontend Consistency Failures

### F6. Selector drift vs backend truth

| | |
|---|---|
| **Manifestation** | GovernanceRadar shows "HEALTHY" but engine logs show drawdown >15%. User trusts the green badge and takes no action. |
| **Root cause** | `selectors/governance.ts` defines `score = sharpe*0.4 + psr*0.3 + crs*0.2 - hhi*0.1`. This is an *interpretation* of governance, not a read of the engine's actual governance state (which uses `combined_sl_mult`, `validity_state`, and hard halt triggers). The selector and the engine use different governance models. |
| **Mitigation** | **Selectors must be backend-mirrored, not independently designed.** The governance selector should read `asset.governance.validity_state` and `asset.governance.halted` directly, not recompute a score. If a score is needed, the backend should compute it and expose it on the snapshot. The selector's job is projection, not re-derivation. |
| **Prevented by design?** | **No** — the current selector design invents its own scoring model. This is the single highest-risk failure mode in the entire migration. |

### F7. React Query cache desync between tabs

| | |
|---|---|
| **Manifestation** | User is on Dashboard tab (30s poll). Switches to Risk tab — signals table shows different data for the same asset. Refreshing makes them match. |
| **Root cause** | Different tabs may have different `queryKey` scopes if the migration is partial (some tabs use old hooks, some use bundle). Also: if `staleTime` differs between queries that should share data, the cache holds two versions. |
| **Mitigation** | **Single query key for all snapshot data.** Enforce: one `queryKey: ['systemSnapshot']` for all bundle reads. Every component reads from the same cache entry. During migration (DUAL phase), log a warning when old-hook data diverges from bundle data by >1%. |
| **Prevented by design?** | **Yes (target state)** — single query key. **No (mid-migration)** — dual-read phase will have temporary divergence. The migration log must catch this. |

### F8. Route change causing stale derived state

| | |
|---|---|
| **Manifestation** | User navigates from Risk tab (`#/risk?asset=EURUSD`) to Trading tab (`#/trading`). The detail panel closes but `selectedAsset` in context still holds "EURUSD". A component that reads context without checking the current route shows stale data. |
| **Root cause** | `SelectedAssetContext` is not synced with URL query params. Changing routes clears the visible panel but does not clear the context. Any component subscribed to `selectedAsset` without a route guard will render EURUSD data on the Trading tab. |
| **Mitigation** | **Context is derived from URL, not independent.** `SelectedAssetContext` should read from `useSearchParams().asset`, not from separate `useState`. When route changes and param is absent, context value becomes `null`. No stale state possible. |
| **Prevented by design?** | **No** — current plan has URL for tabs but context for selection. These must be merged. |

### F9. Modal stacking + Escape key inconsistency

| | |
|---|---|
| **Manifestation** | User opens AssetDetailPanel, then clicks "Deep Dive" → AssetDeepDive opens full-screen. Pressing Escape closes the Deep Dive, but the detail panel is now visible underneath with a stale backdrop. Pressing Escape again closes the detail panel but the page behind it scrolls unexpectedly. |
| **Root cause** | Two independent `useState` booleans (`selectedAsset`, `deepDiveAsset`) with no stacking coordination. Escape handler calls `onClose` on the topmost modal, but the backdrop z-index stack is not managed. |
| **Mitigation** | **Modal stack with z-index manager.** Introduce a `modalStack: ('detail' | 'deepdive' | 'health' | 'weekly')[]` state. Escape pops the top. Backdrop renders once (at the deepest z-index). DeepDive replaces DetailPanel in the stack (not stacked on top) — when DeepDive opens, DetailPanel closes. This matches how trading terminals handle nested inspection. |
| **Prevented by design?** | **No** — current design allows independent stacking. |

### F10. Empty state / loading state flicker

| | |
|---|---|
| **Manifestation** | Every 5s poll cycle: AssetGrid shows skeleton → data → skeleton → data. Grid height jumps by 200px each cycle. User cannot read position data because it keeps resetting. |
| **Root cause** | `isPending` is `true` during every background refetch (even though data is in cache). The component's `if (isPending) return <Skeleton />` block fires on every fetch. |
| **Mitigation** | **Use `isFetching` instead of `isPending` for background refetches, or `placeholderData: keepPreviousData`.** Show skeleton only on initial load (no data in cache). Background refetches keep the previous data and subtly update. |
| **Prevented by design?** | **No** — the current plan specifies `isPending` checks in multiple components. Must be explicitly switched to `keepPreviousData`. |

---

## Layer 3: System-Level Trading Failures

### F11. MT5 disconnect during active trading

| | |
|---|---|
| **Manifestation** | `MT5Status` shows "Connected". Engine logs show 0-position checks for 15min. User sees "Flat" on all assets, assumes no opportunity exists. Meanwhile, MT5 bridge is silently disconnected (Wine process froze) and no trades are being placed. |
| **Root cause** | `bundle.live.mt5` returns `{ connected: true }` from cache. The MT5 bridge's TCP heartbeat is not wired into the bundle — the status is the *last known* state, not a current probe. The bridge could be dead for up to 30s before the status recognizes it. |
| **Mitigation** | **Heartbeat-gated MT5 status.** The MT5 status probe must be *actively verified* on each bundle fetch (TCP ping to Wine process, <100ms). If ping fails, return `mt5: { connected: false, last_connected: <timestamp> }`. The engine must also produce a `mt5_alive` bool in the snapshot itself (written by the engine loop, independent of the bridge). Cross-check: UI shows red if `bundle.live.mt5.connected === false` OR `bundle.snapshot.engine_status.mt5_alive === false`. |
| **Prevented by design?** | **No** — MT5 status is cached and stale. |

### F12. Execution feed lag vs actual fills

| | |
|---|---|
| **Manifestation** | TradeFeed shows no activity for 2min. Then shows 5 trades that happened 2min ago. User already took action (changed strategy) based on the stale feed. |
| **Root cause** | `/trades.json` is cached with 15s TTL on the server. The frontend polls every 30s. Worst-case delay from fill to display: 15s (server cache) + 30s (poll) + re-render = ~45s. For a fast intraday scalping system, 45s is an eternity. |
| **Mitigation** | **Execution feed is real-time, not polled.** TradeFeed should use a lightweight polling path with 2s interval and no server caching. Separately: the engine should write fills to a `recent_fills.json` file (last 20 fills, no parquet) that the server reads without cache. The TradeFeed hook fetches this, not the general `/trades.json`. |
| **Prevented by design?** | **No** — trade feed uses the same slow path as the paginated trade history. |

### F13. Risk layer lagging behind portfolio state

| | |
|---|---|
| **Manifestation** | Portfolio value drops 5% in one cycle. GovernanceRadar still shows "GREEN". No alert fires. Next cycle, the halt trigger fires and the market circuit breaker stops trading — after the drawdown already occurred. |
| **Root cause** | Governance state (`selectors.governance`) derives from snapshot, which is updated at engine cycle frequency (~30s). The drawdown calculation in the selector uses `portfolio.drawdown` from the snapshot. But the engine's *live* drawdown (tracked intra-cycle) is not reflected in the snapshot until the cycle completes. |
| **Mitigation** | **Snapshot includes real-time drawdown estimate.** The engine should compute an intra-cycle drawdown estimate and write it to the snapshot on each tick (not just on cycle completion). The selector reads `snapshot.portfolio.realtime_drawdown` if available, falling back to `portfolio.drawdown`. The UI should show both: "Current drawdown: 4.2% (settled: 1.1%)". |
| **Prevented by design?** | **No** — drawdown is cycle-latent. |

### F14. "False safe state" problem

| | |
|---|---|
| **Manifestation** | Everything looks normal: green dots, positive return, healthy governance. But the engine has been halted for 3 cycles due to drift. The snapshot still reports `engine_status.initialized: true` because the engine loop is running — it's just not placing trades. |
| **Root cause** | `engine_status.initialized` reflects the *process* state, not the *trading* state. The engine can be initialized but halted (drift, drawdown, narrative halt). There is no single "is the system actually trading" boolean on the snapshot. The frontend infers trading state from asset-level `halt.halted` flags but has no portfolio-level halt indicator. |
| **Mitigation** | **Add `engine_status.trading_enabled: boolean` to the snapshot.** This is set by the engine once per cycle: `trading_enabled = not any(halt for asset in assets) and not global_drawdown_halt and not drift_halt`. The header quick stats bar reads this to show "TRADING" / "HALTED" / "DEGRADED" instead of just "LIVE". |
| **Prevented by design?** | **No** — no portfolio-level trading-enabled flag exists. |

### F15. Bundle timestamp vs engine timestamp skew

| | |
|---|---|
| **Manifestation** | `meta.server_time` (from bundle handler) is 5s ahead of `snapshot.portfolio.last_update` (from engine). A diagnostic tool that compares the two shows "data age: 5s". User thinks the system is lagging. |
| **Root cause** | `meta.server_time` is set at HTTP response time. `snapshot.portfolio.last_update` is set when the engine last wrote the snapshot (cycle boundary). These are two independent clocks in two processes. A 5s skew is normal during active trading but looks like a data freshness bug. |
| **Mitigation** | **Normalize timestamps.** The bundle handler adds `meta.snapshot_age_ms = server_time - snapshot.portfolio.last_update`. The frontend uses `snapshot_age_ms` for freshness display, not `server_time`. Any system that shows "last updated X ago" must subtract `snapshot_age_ms` from the current time. |
| **Prevented by design?** | **No** — `meta.server_time` exists but `snapshot_age_ms` does not. |

---

## Summary: What Gets Prevented vs What Needs Fixing

| Failure mode | Prevented? | Fix required before Branch 1? |
|---|---|---|
| F1. Bundle lag (serial sub-fetches) | No | Yes — add per-sub-fetch timeout in `bundle.py` |
| F2. Schema drift | Partial | Define `meta.schema_hash` and add `.passthrough()` to bundle schema |
| F3. Market transition latency | No | Add transition detection to `useSystemSnapshot` |
| F4. Bundle size growth | Partial | Add hard size limit + CI check |
| F5. Sequence ID gap | No | Wire `meta.sequence_id` into cache invalidation |
| F6. Selector drift vs backend | **No — highest risk** | Redesign governance selector to mirror backend, not re-derive |
| F7. Cache desync between tabs | Yes (target) / No (mid-migration) | Single query key enforcement |
| F8. Stale context on route change | No | Merge `SelectedAssetContext` with URL params |
| F9. Modal stacking | No | Modal stack manager with z-index |
| F10. Skeleton flicker | No | `keepPreviousData` everywhere |
| F11. MT5 disconnect | No | Active heartbeat probe per bundle fetch |
| F12. Execution feed lag | No | Dedicated fast path for recent fills |
| F13. Risk layer lag | No | Intra-cycle drawdown estimate on snapshot |
| F14. False safe state | No | `engine_status.trading_enabled` boolean |
| F15. Timestamp skew | No | `meta.snapshot_age_ms` field |

## Pre-migration fixes (do before Branch 1)

1. **Fix F6 first** — redesign `selectors/governance.ts` to read `asset.governance.*` fields from snapshot, not re-derive scores. This is the single highest-risk failure mode.

2. **Fix F1** — add per-sub-fetch timeouts to `bundle.py`. MT5 timeout does not stall the bundle.

3. **Fix F10** — audit all components for `isPending` checks and switch to `keepPreviousData`.

4. **Fix F14** — add `trading_enabled` field to the engine snapshot (small backend change in engine cycle).

Everything else can be fixed per-branch as the migration progresses. The 4 fixes above are preconditions — without them, the target architecture has known failure modes that will manifest immediately.
