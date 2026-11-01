# Live-Process Attestation Guidance

**Purpose:** Establish, from evidence, what live process is running, which code
and configuration it loaded, which campaign/account it is bound to, and whether
its evidence chain is intact.

**Scope:** Offline guidance and read-only inspection. This document does not
start, stop, restart, or modify any live process, and it does not authorize
trading or capital changes.

**Authoritative at:** commit `4861dc3` (Unit 3 HEAD). Re-verify the commands
below against the running commit before relying on them.

---

## 1. The claim being attested

A live-process attestation answers six separate questions. A "yes" to one does
not imply a "yes" to another:

| # | Question | Evidence source |
|---|---|---|
| 1 | **Is a loop process alive, and is it the only one?** | `supervisor.pid`, `/proc/<pid>`, exit code 75 |
| 2 | **Which code is it executing?** | `/proc/<pid>/cwd`, `/proc/<pid>/exe`, `git`, `eigencapital.__file__` |
| 3 | **Which configuration did it load?** | `EIGENCAPITAL_ENV`, config hash, fingerprint startup event |
| 4 | **Which campaign boundary and account is it bound to?** | latest `T0_*.json`, `t0_validated` event |
| 5 | **Is it healthy right now?** | `loop_health.json`, `supervisor_state.json`, `decisions.jsonl` mtime |
| 6 | **Is the evidence intact and attributable?** | JSONL ledgers, `DurableAudit.verify()` for hash-chained stores |

**Fail-closed rule:** if any of questions 1–4 cannot be evidenced from the
running process (not merely from the repository), the runtime identity is
**UNATTESTED**. Do not treat an unattested process as authorized for capital.

---

## 2. Canonical artifact map

| Artifact | Written by | Meaning | Tamper evidence |
|---|---|---|---|
| `reports/r4_loop/supervisor.pid` | `ProcessSupervisor.claim_instance()` | PID of the single loop claimant; removed on clean release | None (liveness via `kill -0`) |
| `reports/r4_loop/supervisor.lock` | `ProcessSupervisor.claim_instance()` | `flock` target making claim atomic | OS lock |
| `reports/r4_loop/supervisor_state.json` | `ProcessSupervisor` | `pid`, `started_at`, `restart_count`, `last_healthy_at`, `status`, `instance_id` | None; `release()` writes `stopped` (preserves `frozen`); artifacts written before that hardening may still read `running` |
| `reports/r4_loop/loop_health.json` | `ProcessSupervisor.mark_healthy()` / `release()` | `alive`, `pid`, `timestamp`, `instance_id` | None |
| `reports/r4_loop/last_health.json` | `scripts/r4_monitor.py` | Monitor fallback liveness snapshot | None |
| `reports/r4_loop/decisions.jsonl` | `scripts/r4_rebalance_loop.py::audit()` | Append-only operational/audit events | **Append-only only; not hash-chained** |
| `reports/r4_loop/risk_gate_audit.jsonl` | `RiskEnforcer` | Per-gate results | None |
| `reports/r4_loop/order_intents.jsonl` | loop | Independent order-intent ledger | None |
| `reports/r4_loop/weight_deviation.jsonl` | loop | T0 sizing evidence | None |
| `reports/r4_loop/rebalance_policy_state.json` | `RebalancePolicyLedger` | Persisted day/week anchors | None |
| `reports/r4_loop/runtime_state.json` | loop | Recovery/peak-equity state | None |
| `reports/execution_audit.jsonl` (+ `.mirror.jsonl`) | `DurableAudit` via execution events | Hash-chained execution events | **SHA-256 chain + mirror** |
| `reports/campaigns.jsonl` (+ `.mirror.jsonl`) | `DurableAudit` via campaign store | Hash-chained campaign history | **SHA-256 chain + mirror** |
| `reports/r4_qualification/T0_*.json` | `scripts/r4_generate_t0.py` | Campaign boundary: config fingerprint, account, snapshot hash | `snapshot_hash` field |
| `reports/r4_loop/loop_stdout.log` | `scripts/start_trading.sh` | Loop stdout (`log()` output) | None |
| `reports/r4_loop/runs/YYYY-MM-DD.log` | `scripts/r4_daily.sh` | Daily one-shot stdout | None |

> **Log path is launcher-dependent.** `start_trading.sh` writes
> `loop_stdout.log`; `r4_daily.sh` writes `runs/YYYY-MM-DD.log`; a manual
> `nohup ... > FILE` writes wherever the operator redirected it. Never assume
> `loop.log` exists.

---

## 3. Procedure

### Step 1 — Identify the process and prove uniqueness

```bash
# Claim holder (only exists while a loop holds the claim)
cat reports/r4_loop/supervisor.pid 2>/dev/null || echo "no supervisor.pid"

# Live processes (do not trust status files alone)
ps -eo pid,lstart,args | grep -E 'r4_rebalance_loop|r4_safety_supervisor' | grep -v grep

# For the claimed PID: liveness, cwd, exe, cmdline, start time
PID=$(cat reports/r4_loop/supervisor.pid 2>/dev/null)
[ -n "$PID" ] && kill -0 "$PID" 2>/dev/null && echo "alive: $PID" || echo "not alive"
[ -n "$PID" ] && readlink -f "/proc/$PID/cwd"
[ -n "$PID" ] && readlink -f "/proc/$PID/exe"
[ -n "$PID" ] && tr '\0' ' ' < "/proc/$PID/cmdline"; echo
```

Interpretation:

- **Exactly one** `r4_rebalance_loop.py` process in `--loop` mode is expected.
- `--flatten` and `--verify-config` **bypass** the single-instance guard by
  design; do not count them as the loop.
- A second live loop exits with code **75** (`EX_TEMPFAIL`) and must not be
  running; its refusal is printed to stdout, not to `decisions.jsonl`.
- `scripts/r4_daily.sh` takes its own `flock` on `reports/r4_loop/.lock` and
  skips when the live loop owns the claim. A skipped daily run is normal.

### Step 2 — Establish code identity

Attest the code from the **process's** working directory, not from wherever the
operator happens to be:

```bash
CWD=$(readlink -f "/proc/$PID/cwd")
git -C "$CWD" rev-parse HEAD
git -C "$CWD" status --porcelain=v1
git -C "$CWD" diff --stat
python -c "import eigencapital, sys; print(eigencapital.__file__); print(sys.version)"
```

Record: commit SHA, dirty/clean state, Python version, and whether
`eigencapital.__file__` resolves inside the same checkout (`src/`) rather than
an installed site-packages copy. A dirty tree or a mismatched module path means
the running code is **not** the committed code.

### Step 3 — Establish configuration identity

```bash
# Environment actually seen by the process (may require same-user/root)
tr '\0' '\n' < "/proc/$PID/environ" | grep -E '^EIGENCAPITAL_ENV=' || echo "unset (defaults to production)"

# Hash the exact config file
sha256sum configs/production/config.toml

# Five-component runtime fingerprint (run in the process's interpreter/venv)
python - <<'PY'
from eigencapital.production_qual.fingerprint_verifier import FingerprintVerifier
from eigencapital.config import load_config
r = FingerprintVerifier(config=load_config("production")).verify_all()
print("all_verified:", r.all_verified)
for c in r.checks:
    print(f"{c.component:16} {c.status:10} expected={c.expected[:16]} observed={c.observed[:16]}")
PY
```

The verifier checks five components: `r4_manifest`, `risk_policy`,
`live_risk`, `strategy_version`, and `config`. The loop computes these at
startup and emits `startup_fingerprint_verified` (or
`startup_fingerprint_failed`) with the same fields into `decisions.jsonl`.

**Important limitation:** the frozen fingerprints are computed at process
start and cached. They prove *no drift since startup*; they do **not** prove
the startup values were the approved ones. Cross-check the observed prefixes
against the latest `T0_*.json` and the expected commit.

### Step 4 — Establish the campaign boundary (T=0)

```bash
ls -1t reports/r4_qualification/T0_*.json | head -1
python - <<'PY'
import json, glob, os
p = max(glob.glob("reports/r4_qualification/T0_*.json"), key=os.path.getmtime)
d = json.load(open(p))
print("file:", p)
print("campaign_id:", d.get("campaign_id"))
print("account:", d.get("account", {}).get("id"))
print("config_fp:", d.get("fingerprints", {}).get("config", "")[:16])
print("snapshot_hash:", d.get("snapshot_hash", "")[:16])
PY
```

The loop validates T=0 at startup and emits `t0_validated` or `t0_mismatch`.
**If no T=0 snapshot exists, the loop logs a warning and proceeds without the
check** — treat that as a material attestation gap, not a pass.

### Step 5 — Establish broker/account identity

```bash
python scripts/r4_attestation.py        # read-only: ownership, attribution, quarantine
python scripts/r4_supervisor_dryrun.py  # read-only: 9-gate live-state verification
```

Both scripts connect to the MT5 bridge and read broker state; neither submits
orders. Confirm the account login matches the T=0 `account.id`, and that
foreign positions are zero (or quarantined) before treating the process as
bound to the intended campaign.

### Step 6 — Establish liveness and freshness

```bash
cat reports/r4_loop/supervisor_state.json
cat reports/r4_loop/loop_health.json
cat reports/r4_loop/last_health.json 2>/dev/null || echo "monitor snapshot absent"
stat -c '%y %n' reports/r4_loop/decisions.jsonl
```

Compare `loop_health.json.timestamp` and `decisions.jsonl` mtime against the
configured watchdog thresholds (`configs/production/config.toml`,
`[watchdog]`): `stale_after_seconds = 300`, `blind_after_seconds = 900`,
`contain_after_seconds = 3600`.

**Pitfall:** `release()` now writes `stopped` (or preserves `frozen`), but any
`supervisor_state.json` written before that hardening can still read
`"running"` after a process has exited. Always confirm with `kill -0 "$PID"`
and a fresh `loop_health.json` timestamp.

### Step 7 — Verify evidence integrity

```bash
# Hash-chained stores (fail closed on any break)
python - <<'PY'
from pathlib import Path
from eigencapital.live.durable_audit import DurableAudit
for p in [Path("reports/execution_audit.jsonl"), Path("reports/campaigns.jsonl")]:
    if not p.exists():
        print(p, "ABSENT")
        continue
    v = DurableAudit(p).verify()
    print(p, "valid=", v.valid, "n=", v.n_records, "broken_at=", v.broken_at_seq, v.reason)
PY

# Append-only (not hash-chained): inspect startup sequence
python - <<'PY'
import json
want = {"startup_fingerprint_verified", "startup_fingerprint_failed", "t0_validated",
        "t0_mismatch", "startup_position_assertion", "trading_authorized", "config_warning"}
for line in open("reports/r4_loop/decisions.jsonl"):
    try:
        r = json.loads(line)
    except json.JSONDecodeError:
        continue
    if r.get("event") in want:
        print(r.get("timestamp"), r.get("event"))
PY
```

`decisions.jsonl` is append-only but **not** cryptographically chained. It is
operational evidence, not tamper-proof evidence. Use the `DurableAudit` stores
for tamper-evident claims.

### Step 8 — Record the attestation

Store the result under `reports/audits/` with the timestamp and commit:

```markdown
## Live-process attestation — <UTC timestamp>
- Claimed PID / instance_id:
- Process alive and unique: yes/no (evidence: kill -0, ps)
- Code: commit <sha>, tree clean/dirty (evidence: git -C <cwd>)
- Config: env=<...>, sha256=<...>, fingerprint all_verified=<yes/no>
- T=0: file=<...>, campaign=<...>, account match=yes/no
- Broker: account=<...>, foreign positions=<n>
- Liveness: loop_health.ts=<...>, decisions.mtime=<...>, watchdog state=<...>
- Evidence: execution_audit valid=<...>, campaigns valid=<...>
- Verdict: ATTESTED / UNATTESTED (reason)
```

---

## 4. Known pitfalls and limitations

1. **Status-file staleness** — newer releases write `stopped`/`frozen`, but
   older `supervisor_state.json` artifacts may still say `running`. Always
   confirm with the live PID.
2. **T=0 is optional at startup** — absent T=0 produces a warning, not a halt.
   Record it as an evidence gap.
3. **`decisions.jsonl` is not hash-chained** — do not claim tamper evidence for
   it. Only `reports/execution_audit.jsonl` and `reports/campaigns.jsonl`
   (plus mirrors) are `DurableAudit` chains.
4. **Launcher-dependent logs** — `loop.log` is not a canonical path. Resolve
   the actual stdout destination from the launcher.
5. **Guard bypass modes** — `--flatten` and `--verify-config` intentionally
   bypass the single-instance claim; do not count them as the loop.
6. **`/proc/<pid>/environ` access** — may be restricted by permissions or
   hidepid; if unreadable, the configuration environment is unattested.
7. **Clock trust** — all timestamps assume a trusted system clock; record the
   host time source if attestation timing matters.
8. **Cached fingerprints** — prove no drift since startup, not approval of the
   startup values. Cross-check against T=0 and git.

---

## 5. Non-goals

- This guidance does **not** start, stop, restart, or reconfigure any process.
- It does **not** authorize trading, capital increases, or policy changes.
- It does **not** replace `scripts/r4_attestation.py`,
  `scripts/r4_supervisor_dryrun.py`, or the `DurableAudit` chain checks.
- It does **not** resolve R-002-A (invalid-SL gap), which remains open.
