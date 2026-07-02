# EigenCapital — Development Plan

*Generated 2026-06-22 from the dashboard architecture review and subsequent recalibration.*

## 1. What Changed

The original review scored the dashboard against institutional-trading-desk standards (Bloomberg Terminal, TT, MARS). That was the wrong yardstick for a solo-developer paper-trading research platform. This plan corrects the framing:

- **Design failures** — things that are *built incorrectly* for the system's actual purpose. Fix these now.
- **Scope gaps** — things that *don't exist yet* because the system never claimed to solve for them. Evaluate whether they belong on the roadmap at all, then sequence honestly.
- **Binary risks** — auth, exposure, state-machine safety. These aren't quality gradients; they're gates.

## 2. Dependency Graph

```
                        ┌──────────────────────────┐
                        │  Security model design   │ ◄── Gate for anything
                        │  (auth, network exposure)│     beyond localhost
                        └────────────┬─────────────┘
                                     │
              ┌──────────────────────┼──────────────────────┐
              │                      │                      │
              ▼                      ▼                      ▼
   ┌────────────────────┐  ┌────────────────────┐  ┌───────────────────┐
   │ Engine command     │  │ State sync design  │  │ Mechanical fixes  │
   │ interface design   │  │ (pause/override    │  │ (tab nav, Signals │
   │ (design pass)      │  │  interactions)     │  │  Table, MT5 comp, │
   └────────┬───────────┘  └────────┬───────────┘  │  calibration,     │
            │                       │              │  exec feed)       │
            │                       │              │  ┌─────────────┐  │
            │                       │              │  │ ALREADY DONE│  │
            │                       │              │  └─────────────┘  │
            ▼                       ▼              └───────────────────┘
   ┌────────────────────┐  ┌────────────────────┐
   │ Trading controls   │  │ Real-time state    │
   │ UI + backend       │◄─┤ push (WebSocket)   │
   │ (HIGHEST STAKES)   │  │                    │
   └────────────────────┘  └────────────────────┘
                                     │
                                     ▼
                            ┌────────────────────┐
                            │ External alerting  │
                            │ (email/Slack)      │
                            └────────────────────┘

Dependencies:
  ─  Security model → Trading controls (auth required)
  ─  Security model → Any remote access (gate)
  ─  State sync design → Trading controls (must understand engine interaction)
  ─  State sync design → Real-time push (same state model)
  ─  Engine command interface → Trading controls UI
  ─  Trading controls → Auth (otherwise unsafe)
  ─  Mechanical fixes: NO dependencies on above (can ship immediately)
```

## 3. Track Organization

Three parallel tracks. Items within a track are sequential; tracks run in parallel where their dependency graphs allow.

---

## Track A: Design Failures — Already Shipped

These were the genuine design failures identified in the review. All are built, compiled, and verified.

| Item | Effort | Status | Notes |
|------|--------|--------|-------|
| Tab navigation (replace single-page scroll) | 1 day | ✅ Done | 5 tabs: Dashboard, Trading, Execution, Research, Risk |
| Remove ENABLE_DETAIL_PANEL feature flag | 0.5 day | ✅ Done | AssetDetailPanel always enabled |
| SignalsTable redesign (gates, size, halted, uPnL columns) | 1 day | ✅ Done | Removed TP%/SL%/Alloc from main columns |
| MT5 status component (replace 8px dot) | 0.5 day | ✅ Done | Proper component with WiFi icon, equity display |
| ExecutionFeed component (per-cycle decision log) | 1 day | ✅ Done | Shows gates result, size, abort reason per asset |
| CalibrationCurve (predicted vs actual win rate) | 1 day | ✅ Done | Scatter plot with SELL-only overlay |
| Sidebar restructure (tab-based navigation) | 0.5 day | ✅ Done | 3 groups, descriptive subtitles |
| Split Execution section into Quality + Attribution | 0.5 day | ✅ Done | Two tab sections instead of one scroll |

**Total shipped: ~6 days equivalent**

---

## Track B: Safety & Infrastructure — Gating Items

These are *prerequisites*. Nothing in Track C or any remote-exposure feature should ship before these.

### B1. Security Model (⚠ BINARY RISK)

**What**: The current HTTP server (Python stdlib `ThreadingMixIn + SimpleHTTPRequestHandler`) on port 5000 has zero authentication. If this port is exposed beyond localhost — even temporarily for testing — the entire engine state is readable and the `/narrative/confirm` and `/weekly-review/acknowledge` POST endpoints are callable.

**Effort estimate**: 3–5 days total.

**Sub-items**:

1. **Audit current exposure** (0.5 day) — Check firewall rules, process namespace, any reverse-proxy configs. Determine whether port 5000 is actually reachable from outside localhost today.

2. **If exposed → immediate containment** (0.5 day) — Add `iptables` or `ufw` rule blocking inbound on 5000 from non-local sources. Or bind only to `127.0.0.1`. This is a 5-minute fix that should happen before any other work.

3. **Token-based auth for any future remote access** (2–3 days) — A stateless bearer-token scheme for the HTTP API. No sessions, no cookies (the server has no session middleware). Token from env var or config file. `Authorization: Bearer <token>` required on all POST endpoints and any GET endpoint that could reveal position-level data (which is all of them). Read the token once at startup, reject unauthenticated requests with 401.

4. **CSRF consideration for POST endpoints** (0.5 day) — The two existing POST endpoints (`/narrative/confirm`, `/weekly-review/acknowledge`) are low-stakes, but the pattern matters. Same-origin check + token header.

**Dependencies**: None. Can start immediately.

**Blocking**: Trading controls (B3), any remote dashboard access.

### B2. State Synchronization Design (🔷 NEEDS DESIGN PASS)

**What**: Before building any mechanism that lets an operator *change* engine state from the UI (pause, override, close), we need a design doc that answers:

- What happens when a pause command arrives mid-cycle during `AssetEngine.generate_signal()`?
- The engine runs in a `while not _shutdown.wait(60)` loop with `run_once()` per iteration. A pause command must be consumed before `run_once()` begins, not during. How does the command interface synchronize with this loop?
- If the engine crashes mid-pause, does it resume on restart? Does it stay paused? Where is pause state persisted?
- The audit log (WAL) — is it the source of truth for override history, or a side effect of the override command? If the WAL write fails, should the override be rolled back?
- Race condition: operator sends "close position" at the same time the engine's own position-management logic triggers a close. Double-close risk. Idempotency key on commands.

**Effort estimate**: Cannot estimate implementation until the design doc exists. Design doc itself: 2–3 days of focused writing.

**Output**: A `DESIGN_COMMAND_INTERFACE.md` document covering:
- Command model (pause/resume/override/close/flatten)
- Synchronization with engine loop
- Persistence and crash recovery
- Idempotency and race conditions
- Audit trail ownership
- Auth integration boundary

**Dependencies**: None on implementation. Should be done *before* any code is written for Track C.

**Blocking**: Track C — trading controls.

### B3. Engine Command Interface (🔷 NEEDS DESIGN PASS)

**Note**: B2 and B3 can be a single design pass if scoped together. The distinction is:
- **B2** = how does the engine safely accept and apply external commands?
- **B3** = what are the commands themselves? What are their semantics?

**Sub-items once design is complete**:

1. **Implement command queue** (2–3 days) — A `queue.Queue` consumed at the start of each `run_once()` iteration. Commands are: `PAUSE(asset)`, `RESUME(asset)`, `OVERRIDE(asset, signal)`, `CLOSE(asset)`, `FLATTEN_ALL`.
2. **Persist command state** (1 day) — Atomic JSON file or WAL replay. On restart, engine checks for pending pause/override state and re-applies.
3. **Audit log integration** (1 day) — Each command writes to WAL as `operator_command` event. The WAL is the source of truth.

**Dependencies**: Requires B2 design pass.

---

## Track C: Trading Controls (Highest Stakes)

**Do not start until B1 (auth) AND B2/B3 (command interface design) are complete.**

This isn't because trading controls are complex UI (they're a few buttons and confirmation dialogs). It's because the *backend* is a multi-threaded Python process with in-flight signal evaluation, atomic state writes, and no concept of external commands. A UI button that "just closes a position" needs the entire command interface from B3 to exist first, plus auth from B1 to ensure only an authenticated operator can call it.

**Effort estimate for the UI layer once backend exists**: 2–3 days.

**Components**:
- Per-asset pause/resume toggle (in AssetDetailPanel and SignalsTable row)
- Per-asset signal override dropdown (in AssetDetailPanel)
- Per-asset close position button (in AssetDetailPanel)
- Portfolio-level "Flatten All" button (in Dashboard tab, with confirmation dialog)
- Confirmation dialog for irreversible actions (close, override, flatten)
- Visual state indicator: is this asset paused? Is there a pending override? In cooldown?

**Safety requirements that must be met before this ships**:
- Auth enforced on all command endpoints (B1)
- Idempotency on close/override (B3 design)
- Crash recovery verified: if engine restarts, pause/override state is re-applied
- Audit log verified: every command is recorded before it's executed
- Confirmation dialog requires deliberate action (type asset name to confirm)

---

## Track D: Observability Upgrades (Lower Risk, Independent)

These can run in parallel with B1/B2/B3 with no dependency conflicts.

### D1. Real-time State Push

**What**: Replace polling with Server-Sent Events for state deltas.

**Why**: Not for latency (30s polling is fine for paper trading). For correctness: polling means the dashboard shows a snapshot that's 5–30s stale, and the operator has no way to distinguish "engine is running and produced no new state" from "engine crashed silently." SSE gives a continuous connection with automatic reconnect.

**Effort**: 3–5 days.

**Sub-items**:
1. **Server-side SSE endpoint** (1 day) — Python stdlib doesn't support SSE well. The minimal change is a dedicated thread with a streaming HTTP response. Or switch to a simple async framework (FastAPI is the obvious choice). This is a larger refactor than a weekend.
2. **Frontend EventSource integration** (1 day) — Replace polling with `EventSource` in `usePortfolioState`. Handle reconnect, backoff, staleness detection.
3. **Delta encoding** (1–2 days) — Full state on initial connection, then deltas for subsequent events. Reduces bandwidth 10–50x.

**Alternative**: Skip SSE entirely and add a `/_health` endpoint that the frontend polls at 5s intervals (lightweight), while keeping the full `/state.json` at 30s. This is 1 day of work and solves the "stale vs crashed" problem without a protocol change.

**Recommendation**: Do the lightweight health-ping first (1 day), defer SSE until the system has a reason to need sub-5s updates.

### D2. External Alerting

**What**: When a critical event occurs (asset halted, drawdown threshold breached, engine stops producing state), notify the operator without requiring them to watch the dashboard.

**Effort**: 2–4 days for a minimal but functional system.

**Design constraints**:
- Must be stateless from the engine's perspective (engine shouldn't care whether Slack is reachable)
- Must use the existing WAL as the event source, not duplicate event logic
- Must rate-limit (the engine already has rate-limited warnings in `HealthMonitor`; use the same mechanism)

**Sub-items**:
1. **Alert router daemon** (1–2 days) — A separate thread or lightweight process that tails `data/live/trace.jsonl` and `data/live/wal/engine.jsonl`, detects actionable events, and dispatches to configured channels. Decoupled from the engine — if the alert daemon crashes, the engine keeps running.
2. **Slack webhook integration** (1 day) — Simple HTTP POST to a Slack webhook URL. Message format: asset, event type, severity, timestamp, link to dashboard.
3. **Rate-limiting and dedup** (0.5 day) — Same-asset cooldown (don't alert on every cycle), severity escalation (don't alert on INFO if CRITICAL already active).
4. **Configuration** (0.5 day) — `configs/alerts.yaml`: per-channel enable/disable, severity filter, asset blacklist.

**Not building**: PagerDuty, SMS, email (SMTP is a dependency). Start with Slack — it's a single HTTP POST.

### D3. WAL Visualization in UI

**What**: The WAL captures `features_snapshot`, `inference_output`, and `decision_output` per cycle. The dashboard shows none of this. Add a WAL timeline view.

**Effort**: 2–3 days.

**Sub-items**:
1. **WAL reader API endpoint** (1 day) — `/wal/{asset}.json?limit=50&offset=0` that reads `engine.jsonl` and returns structured events.
2. **WAL timeline component** (1–2 days) — A chronological view in AssetDetailPanel showing: feature_hash → proba → gates trace → decision. Each event is a collapsible card. Feature hash diffing (green if same as previous cycle, red if changed).

**Dependency**: None. Can use the existing WAL format as-is.

---

## Track E: Research & Analytics (Medium Value, No Dependencies)

### E1. Per-trade Calibration Data

**What**: The current CalibrationCurve component uses aggregate `mean_confidence` vs `win_rate`. Real calibration requires per-trade confidence buckets.

**Effort**: 2–3 days.

**Sub-items**:
1. **Backend calibration endpoint** (1 day) — `/calibration.json` that reads closed trades from SQLite, groups by confidence bucket at entry time, computes actual win rate per bucket. Returns `{buckets: [{bucket_low, bucket_high, n_trades, win_rate}, ...]}`.
2. **Update CalibrationCurve** (1 day) — Switch from scatter plot to grouped bar chart with confidence bins. Add BUY/SELL split (two bars per bucket).
3. **Per-asset calibration in AssetDeepDive** (0.5 day) — Add calibration sub-view to the deep dive modal.

### E2. Feature Importance Over Time

**What**: Track top-5 feature importance per asset over rolling windows.

**Effort**: 3–5 days (significant new data pipeline).

**Sub-items**:
1. **Backend importance tracking** (2–3 days) — After each retraining, record feature importance to SQLite. Expose as timeseries.
2. **UI visualization** (1–2 days) — Area chart showing importance of top-5 features over time. In AssetDeepDive.

---

## Items Explicitly Dropped

These appeared in the original review's "Highest-Impact Improvements" but belong to the institutional-grade checklist for a system with a different operator than this one.

| Item | Reason for dropping |
|------|---------------------|
| Multi-user support with permissions | This system has one operator. Solve auth (B1), not RBAC. |
| PagerDuty / SMS alerting | Slack is sufficient for a single operator. PagerDuty is for on-call rotations. |
| Portfolio-level VaR and stress test | Useful, but the system has 18 assets and $100K paper equity. The modeling effort dwarfs the insight. |
| Backtest/live comparison view | The backtest scripts live in `scripts/`. Integrating them into the UI is polish, not function. |
| Multi-asset P&L ladder | Useful for 100+ asset desks. For 18 assets, the existing per-asset returns table suffices. |
| Bloomberg/MARS-style risk analytics | The project doesn't have a risk model. Adding one is a separate research project. |

---

## 4. Sequencing Summary (Dependency-Aware)

```
NOW ──────────────────────────────────────────────────────────────────────►

┌─── Priorities (0-30 days) ───────────────────────────────────────────────┐
│                                                                          │
│  Track A (DESIGN FAILURES — DONE)                                        │
│  ─────────────────────────────────                                       │
│  Tab nav, SignalsTable, MT5Status, CalibrationCurve, ExecutionFeed       │
│  No dependencies. Already shipped.                                       │
│                                                                          │
│  Track B1 (SECURITY — 5 days max)                                        │
│  ─────────────────────────────────                                       │
│  Week 1: Audit exposure → contain if needed → token auth                 │
│  Gate: nothing below ships without this                                  │
│                                                                          │
│  Track D1 mini (LIVENESS — 1 day)                                        │
│  ─────────────────────────────────                                       │
│  Add lightweight /_health endpoint, 5s frontend poll                     │
│  No dependencies. Solves "is the engine alive?" immediately              │
│                                                                          │
│  Track D2 (ALERTING — 2-4 days)                                          │
│  ─────────────────────────────────                                       │
│  Slack alert router for halt/drawdown/engine-down events                 │
│  No dependencies. Engine-agnostic: tails WAL                             │
│                                                                          │
├─── Medium-term (30-90 days) ─────────────────────────────────────────────┤
│                                                                          │
│  Track B2+B3 (COMMAND INTERFACE DESIGN — 5-7 days)                       │
│  ─────────────────────────────────                                       │
│  Design doc: command model, engine sync, crash recovery, idempotency     │
│  Must precede Track C. Start after B1.                                   │
│                                                                          │
│  Track D3 (WAL VISUALIZATION — 2-3 days)                                 │
│  ─────────────────────────────────                                       │
│  WAL timeline in AssetDetailPanel. No dependencies on B-track.           │
│                                                                          │
│  Track E1 (PER-TRADE CALIBRATION — 2-3 days)                             │
│  ─────────────────────────────────                                       │
│  Backend calibration endpoint + update CalibrationCurve component        │
│  No dependencies.                                                        │
│                                                                          │
├─── Long-term (90+ days) ─────────────────────────────────────────────────┤
│                                                                          │
│  Track C (TRADING CONTROLS — 2-3 days UI + unknown backend)              │
│  ─────────────────────────────────                                       │
│  Requires B1 (auth) + B2/B3 (command interface designed AND built)       │
│  Estimate assumes backend exists from B3. If B3 not started, drop this.  │
│                                                                          │
│  Track D1 full (SSE — 3-5 days)                                          │
│  ─────────────────────────────────                                       │
│  Production real-time push. Only worth it if trading controls            │
│  (Track C) or live capital demand sub-5s state visibility.               │
│                                                                          │
│  Track E2 (FEATURE IMPORTANCE OVER TIME — 3-5 days)                      │
│  ─────────────────────────────────                                       │
│  New SQLite pipeline + visualization. Independent but low value.          │
│                                                                          │
└──────────────────────────────────────────────────────────────────────────┘
```

## 5. Effort Summary Table

| Item | Category | Effort | Needs Design Pass | Blocked By |
|------|----------|--------|-------------------|------------|
| Tab navigation | Design failure | ✅ DONE | — | — |
| SignalsTable columns | Design failure | ✅ DONE | — | — |
| MT5Status component | Design failure | ✅ DONE | — | — |
| CalibrationCurve | Design failure | ✅ DONE | — | — |
| ExecutionFeed | Design failure | ✅ DONE | — | — |
| Security model audit + auth | Binary risk | ✅ DONE | — | — |
| Liveness health endpoint | Observability | 1 day | No | Nothing |
| Slack alerting | Observability | 2–4 days | No | Nothing |
| Command interface design | Infrastructure | 5–7 days | **YES** | Security model |
| Trading controls UI | Highest stakes | 2–3 days UI | **No — backend unknown** | Auth + command interface |
| WAL timeline | Observability | 2–3 days | No | Nothing |
| Per-trade calibration | Research | 2–3 days | No | Nothing |
| SSE real-time push | Observability | 3–5 days | No | Low urgency |
| Feature importance over time | Research | 3–5 days | No | Nothing |

## 6. What Success Looks Like

**At 30 days**:
- ✅ Auth on all endpoints, engine port bound to localhost (DONE 2026-06-22)
- Health ping keeps the dashboard honest about engine liveness
- Slack alerts fire when assets halt or drawdown thresholds breach
- WAL timeline visible per-asset in the detail panel
- Per-trade calibration replaces the aggregate scatter plot

**At 90 days**:
- Command interface design doc exists and is reviewed
- Operator can pause/resume individual assets from the dashboard (with auth)
- Audit trail links every operator action to a WAL event

**At 180 days**:
- Trading controls cover pause/override/close/flatten
- Real-time state push reduces dashboard latency to < 1s
- Alert configuration is user-editable from the dashboard

**Items that may never ship** (and that's fine):
- SSE (if 30s polling + health ping is good enough)
- Trading controls (if operator decides SSH is safer than a UI button)
- Feature importance over time (if no researcher asks for it)

---

*This plan replaces the original review's "Phase 1/2/3" institutional checklist. The original review's analysis of design failures and the calibration-curve finding remains valid; the recommended scope and sequencing are corrected here.*
