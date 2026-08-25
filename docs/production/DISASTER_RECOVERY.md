# EigenCapital — Disaster Recovery Plan

## Recovery Objectives

| Metric | Target | Rationale |
|--------|--------|-----------|
| RTO | < 5 minutes | System halts within seconds; reconciliation < 1 minute |
| RPO | 0 data loss | Broker is authoritative |

## State Classification

### Broker-Authoritative (Never Trust Local Alone)
- Open positions, orders, equity, balance, free margin

### Persisted Locally (Recoverable from Disk)
- Daily loss baseline, supervisor PID state, configuration, audit logs

### Reconstructable (Derived from Broker + Config)
- Disconnect recovery, health gate, trading authorization, risk evaluation

## Disaster Scenarios

### 1. Process Crash
```
Supervisor detects missing PID → restart → load state → query broker → reconcile → verify fingerprint → resume
```

### 2. Machine Reboot
```
OS starts supervisor → start EigenCapital → load state → connect broker → full reconcile → verify safety gates → resume
```

### 3. Broker Outage
```
Disconnect detected → HALT → no orders → broker returns → full reconciliation → verify positions/equity/orders → resume
```
After 3 failed recovery attempts → FROZEN (operator required)

### 4. Disk Corruption
```
JSON/hash validation fails → discard corrupted state → query broker → create new baseline → resume
```
**Invariant:** Corrupted local state NEVER overrides broker state.

### 5. Configuration Corruption
```
Fingerprint mismatch → HALT → operator investigates → restore correct config → restart → verify → resume
```

### 6. Complete Data Loss
```
New machine → install → configure → start → connect broker → full reconciliation → resume
```
**Principle:** No local state is required to safely resume — broker is always authoritative.

## Backup Strategy

| Artifact | Frequency | Retention |
|----------|-----------|-----------|
| configs/ | On change | Permanent |
| reports/r4_loop/ | Daily | 90 days |
| supervisor_state.json | On change | Latest |
| daily_baseline.json | Daily | Latest |

## RTO Verification

| Scenario | Measured RTO | Target | Verdict |
|----------|-------------|--------|---------|
| Process crash + restart | <5s | <5min | ✅ |
| State recovery from disk | <1s | <1min | ✅ |
| Broker reconciliation | <30s | <1min | ✅ |
| Full restart from scratch | <2min | <5min | ✅ |
