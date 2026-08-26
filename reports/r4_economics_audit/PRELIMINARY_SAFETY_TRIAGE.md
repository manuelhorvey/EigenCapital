# PRELIMINARY SAFETY TRIAGE — R4 Live Execution Chain

**Audit phase:** 1 (safety triage precedes all economic analysis) · **Git baseline:** `d16148e` (verified) · **Frozen identity:** `aaab6c00dc05…b2beb` (44/44 freeze tests)
**Companion artifact:** `reports/r4_economics_audit/PRELIMINARY_SAFETY_TRIAGE.json` · **Broker evidence:** `mt5_deals_live.json` (read-only exports, twice, hours apart)

---

## VERDICT — 🔴 PAUSE_REQUIRED = TRUE

**Scope: the R4 rebalance loop on account 436921728.** Four independent P0 conditions confirmed. The audit performed zero live actions; economic phases continued offline per governance.

| ID | Finding | Evidence |
|---|---|---|
| **P0-1** | No layer can reduce live exposure automatically. All gates are BLOCK-entries-only; regime-OFF/daily-loss/critical return *before* touching positions; **sl=0/tp=0 verified on all 16 open positions at broker**; flatten is manual CLI, single-pass, no retry. Worst case bounded only by margin call (2000:1 demo). | `risk_enforcement.check_all()`; loop early returns; broker export |
| **P0-2** | The declared 10% drawdown protection was breached in reality with zero reaction: peak $5,429.45 (00:20Z) → trough $4,885.99 (16:05Z) = **10.01%**, trough inside a ~9.5h bridge outage during which gates were never evaluated. | monitor EQUITY CHANGE series; loop.log |
| **P0-3** | Campaign boundary compromised: 8 foreign `magic=0` positions (~$789K notional ≈ 117–146× equity, AUD-concentrated + BTC 0.15 short); PQ report asserts "Manual trades: 0". Bot realized on closed trades: **−$3.67** vs manual realized −$242.65; equity swings entirely foreign-driven ($4,886 ↔ $6,753 observed range on a $5K account). Concurrency starvation then blocks the bot even from rotating its own losers. | two broker exports hours apart; PQ json |
| **P0-4** | Deployment drift: running loop predates git HEAD (no startup fingerprint lines, missing persisted-state files, exit comments in broker history absent from HEAD code). Qualification attests to an unknown binary. | loop.log structure vs HEAD `main()`; deal comments |

## Control chain (one line per layer)

Signal→sizing: cannot reduce exposure · RiskPolicy: inert for this account · RiskEnforcer gates: BLOCK-only (**per-position loss gate declared but never implemented**; internal daily-loss gate inert) · DailyLossTracker: blocks new cycles only, midnight-$0-baseline hazard · Regime gate: OFF ⇒ positions unmanaged by design · DisconnectRecovery: exists at HEAD, **not active in deployed build** · Flatten: manual only · Monitor: alert-only, Telegram off, re-alert amplification up to **1:1,506**.

## Reaction-time quantification

Order round-trip ≈ 3 s observed. Detection worst cases: hourly cycle ≤3600 s; daily cron ≤86,400 s; **observed blind window 34,200+ s** with unaudited silent SKIP cycles. Overnight/weekend gaps: no protection whatsoever.

## Minimum conditions to resume

1. Quarantine/close foreign positions; reconcile PQ attribution; fresh T0 after clean state.
2. Pin deployed build to audited commit; prove fingerprints at startup and every cycle; stamp build-id in records.
3. Independent **catastrophic protection layer** (broker-side disaster SL ≥ 2×ATR or watchdog auto-flatten with retry), safety-tested offline — distinct from R4 economics.
4. Fix P1 set: implement-or-remove per-position gate; midnight baseline guard; explicit regime-OFF position policy; alert dedup + acting escalation; one canonical regime definition.
5. Absolute audit paths; audited SKIPs.

*Full quantified detail lives in the JSON companion and `triage_log_forensics.json`.*
