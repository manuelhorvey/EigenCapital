# EigenCapital — Production Maturity Model

## Level 0 — Research
**Definition:** Backtest / simulation only.

**Entry criteria:**
- Strategy implemented and tested
- Backtest engine operational
- No real capital at risk

**Exit criteria:**
- [x] Strategy frozen (R4.0)
- [x] Backtest results validated
- [x] Walk-forward analysis complete
- [x] Stress testing complete

**Current status:** ✅ COMPLETE

---

## Level 1 — Paper
**Definition:** Paper execution with simulated fills.

**Entry criteria:**
- [x] Paper broker implemented
- [x] Fill simulation
- [x] Position tracking
- [x] Risk enforcement on paper

**Exit criteria:**
- [x] Paper fidelity verified against backtest
- [x] Shadow comparison clean
- [x] Forward paper results consistent

**Current status:** ✅ COMPLETE

---

## Level 2 — Shadow
**Definition:** Real market data, simulated execution.

**Entry criteria:**
- [x] Shadow broker adapter
- [x] Real market data integration
- [x] Divergence analysis

**Exit criteria:**
- [x] Shadow/backtest divergence within tolerance
- [x] No critical divergences
- [x] Execution assumptions validated

**Current status:** ✅ COMPLETE

---

## Level 3 — Micro-Live
**Definition:** Very small capital ($5K) with full risk controls.

**Entry criteria:**
- [x] MT5 broker connection
- [x] Real order submission capability
- [x] All 7 risk gates operational
- [x] Fingerprint verification
- [x] Daily loss tracking
- [x] Process supervision
- [x] Disconnect recovery
- [x] Configuration single source
- [x] Platform abstraction

**Exit criteria (for $5K qualification):**
- [ ] 30 days supervised operation
- [ ] Zero position count breaches
- [ ] Zero risk control bypasses
- [ ] Zero fingerprint drifts
- [ ] All disconnects recovered
- [ ] All crashes recovered
- [ ] Daily loss resets correctly
- [ ] Audit trail complete

**Current status:** 🔄 IN PROGRESS (supervised qualification)

---

## Level 4 — Controlled Production
**Definition:** Validated capital tier with continuous supervision.

**Entry criteria (from Level 3):**
- [ ] Level 3 exit criteria met
- [ ] 30 days stable at $5K
- [ ] Zero critical incidents
- [ ] Capital scaling review approved
- [ ] Operational procedures documented

**Exit criteria (for $10K-$25K):**
- [ ] 60 days stable operation
- [ ] Process supervision proven
- [ ] Recovery from all tested failures
- [ ] Execution quality metrics established
- [ ] No requotes/rejects above threshold

**Current status:** ❌ NOT STARTED

---

## Level 5 — Scaled Production
**Definition:** Material capital with proven reliability.

**Entry criteria (from Level 4):**
- [ ] Level 4 exit criteria met
- [ ] 90 days stable at previous tier
- [ ] Capacity analysis complete
- [ ] Liquidity impact assessed
- [ ] Multi-broker evaluation (if needed)
- [ ] Institutional procedures

**Exit criteria:**
- [ ] Stable operation across market conditions
- [ ] Recovery from all failure modes
- [ ] Audit trail integrity verified
- [ ] Production maturity demonstrated

**Current status:** ❌ NOT STARTED

---

## Current Assessment

EigenCapital is at **Level 3 (Micro-Live)** — in supervised qualification.

The system has the architecture for Level 4+ but has not yet demonstrated the operational stability required to advance.

**Blocking items for Level 4:**
1. Complete 30-day supervised qualification
2. Demonstrate crash recovery in production
3. Demonstrate disconnect recovery in production
4. Establish execution quality baseline
