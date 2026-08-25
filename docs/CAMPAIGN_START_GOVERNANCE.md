# Campaign Start Governance — $5K MINIMAL Live Qualification

**This document is the operational procedure for transitioning from
PREFUNDING → BROKER-VALIDATED → TRADING_AUTHORIZED → FIRST R4 ORDER.**

It is NOT permission to bypass safety controls or immediately fire orders.
The objective is to prove that the exact frozen R4 system can safely
transition from a $5K funded account to real broker execution without
violating any previously validated invariant.

The campaign is evidence collection and qualification, NOT profit maximization.

---

## 1. READ THE GOVERNANCE BEFORE TOUCHING THE BROKER

Before making any broker-side change:

1. Read the frozen R4 manifest and verify its exact identity:
   `aaab6c00dc05a09a380af7fbd705cc8c241ea69023b6a8ddc8d5e7f0b82b2beb`

2. Read:
   - production qualification framework
   - Phase 1U controls
   - Prefunding Gate audit
   - Pre-Trading validation sequence
   - RiskPolicy
   - HealthGate / PortfolioHealthMonitor
   - disconnect recovery state machine
   - partial-fill policy
   - alert dispatcher
   - reconciliation logic
   - campaign boundary / trade attribution logic

3. Confirm that the live campaign is explicitly MINIMAL:
   - maximum equity: $5,000
   - maximum position: $500
   - maximum order: $250
   - maximum campaign DD: $1,000 / 20%
   - no manual trades
   - no strategy modification
   - no configuration drift

Do NOT modify the frozen R4 strategy or its research configuration.

---

## 2. DO NOT SEND AN ORDER YET

First connect to the actual MT5 account and execute the complete pre-trading
validation sequence.

Required sequence:

```
BROKER CONNECTED
        ↓
FUND_CAPITAL
        ↓
CONNECT_BROKER
        ↓
RECONCILE
        ↓
FINGERPRINT
        ↓
AUTHORIZE
        ↓
TRADING_AUTHORIZED
        ↓
ONLY THEN MAY AN ORDER BE SUBMITTED
```

Every step must succeed.

If ANY step fails:

```
TRADING_BLOCKED
```

and STOP.

- Do not work around the failure.
- Do not manually authorize trading.
- Do not weaken a gate.
- Do not submit a "test" order to see whether execution works.

---

## 3. VERIFY THE ACTUAL MT5 ACCOUNT

Against the live broker state, verify:

- account login matches the authorized account
- broker/server is correct
- live/demo environment is correct
- account currency is correct
- equity is within the $5K MINIMAL boundary
- free margin > 0
- leverage is compatible with the frozen campaign assumptions
- required R4 instruments exist
- symbol specifications are valid
- contract sizes are correct
- minimum volume is compatible with permitted position sizing
- tick size / tick value are sane
- trading permissions are enabled
- market is open where applicable
- spreads are within the configured execution envelope

Do not assume the account state from configuration. Read the actual MT5 state.

Record the complete broker snapshot.

---

## 4. RECONCILE BEFORE TRADING

Before the first order:

- enumerate all open positions
- enumerate all pending orders
- classify every position/order
- confirm there are no manual trades
- confirm there are no unexplained positions
- confirm there are no stale R4 positions from an earlier campaign
- confirm broker equity matches the expected starting state
- confirm internal state matches broker state

If anything cannot be classified:

```
BLOCK TRADING.
```

The account must have a clean, explicitly understood campaign boundary.

---

## 5. VERIFY THE FROZEN R4 IDENTITY

Compute/verify the connected production configuration fingerprint.

It MUST match:
`aaab6c00dc05a09a380af7fbd705cc8c241ea69023b6a8ddc8d5e7f0b82b2beb`

Verify:

- strategy configuration
- model/configuration identity
- risk configuration
- execution configuration
- relevant governed parameters
- software/version guards
- frozen manifest identity

No silent differences.

If fingerprint mismatch:

```
BLOCK.
```

---

## 6. VERIFY ALL LIVE SAFETY CONTROLS

Before authorization, explicitly prove that the following are active in the
actual execution path:

### RISK

- RiskPolicy is the authoritative account-level risk policy
- concentration limits enforced
- asset-class limits enforced
- exposure maps populated from actual positions
- missing exposure data fails closed
- position limits enforced
- order-size limits enforced
- leverage/margin limits enforced
- drawdown breaker active

### HEALTH

- PortfolioHealthMonitor is called by the live loop
- HEALTHY → new trading permitted
- DEGRADED → MANAGE_ONLY
- CRITICAL → HALT
- FROZEN → HALT
- stale snapshot → HALT
- malformed/unparseable health state → HALT
- monitor exception → HALT

### CONNECTIVITY

- reconnect does not automatically authorize trading
- reconciliation is mandatory after disconnect
- mismatches require reconcile-or-flatten
- excessive recovery cycles freeze the system
- manual reset is required after FROZEN

### EXECUTION

- requested vs filled quantity tracked separately
- partial fills handled by policy
- replacement/chase orders pass risk/exposure/spread gates
- chase limits enforced
- fill events idempotent by fill_id
- post-cancel fills handled correctly
- broker-authoritative reconciliation occurs

### OBSERVABILITY

- alerts are active
- durable JSONL records are being written
- stderr/operator visibility works
- alert failure cannot weaken safety
- state transitions are hash chained

---

## 7. RUN THE COMPLETE PRE-TRADING GATE

Run:

```
PrefundingGateAuditor
        +
PrefundingGate
        +
PreTradingValidator
        +
RiskPolicy
        +
HealthGate
        +
Broker reconciliation
```

The final state must explicitly be:

```
TRADING_AUTHORIZED
```

Do not infer authorization from the fact that the account has been funded.

Print a structured pre-trade report containing:

- broker/account identity
- starting equity
- free margin
- open positions
- pending orders
- exposure maps
- asset-class exposures
- active risk limits
- health state
- broker environment
- spread state
- frozen R4 fingerprint
- gate fingerprints
- reconciliation result
- final authorization state

---

## 8. ONLY AFTER AUTHORIZATION: START THE R4 LOOP

Once and ONLY once:

```
TRADING_AUTHORIZED
```

is established, start the normal frozen R4 live execution loop.

The first order must come from:

```
frozen R4 signal
        ↓
normal decision pipeline
        ↓
normal suppression/gating
        ↓
normal RiskPolicy
        ↓
normal position sizing
        ↓
normal execution controls
        ↓
broker order
```

- Do NOT create a special "first live trade" pathway.
- Do NOT bypass the normal decision pipeline.
- Do NOT force a BUY or SELL merely to test execution.
- If R4 currently produces no valid signal, that is completely acceptable.

**WAIT.**

The first trade should occur only when the frozen strategy legitimately
generates an authorized signal.

---

## 9. ENFORCE MINIMAL-SCALE LIMITS

Hard limits:

| Limit | Value |
|---|---|
| MAX EQUITY | $5,000 |
| MAX POSITION | $500 |
| MAX ORDER | $250 |
| MAX CAMPAIGN DD | $1,000 / 20% |

All sizing must pass the existing RiskPolicy.

- Do not increase these limits.
- Do not manually resize an order upward.
- Do not change lot size merely because the broker accepts larger size.

---

## 10. FIRST-TRADE EVIDENCE CHAIN

For every first trade, capture:

```
decision_id
evidence_id
campaign_id
R4 fingerprint
timestamp
symbol
direction
signal/probability information
risk decision
requested volume
approved volume
order request
broker response
order ticket
fill(s)
fill price
spread
slippage
commission
swap if applicable
position state
post-trade equity
risk state
health state
```

The complete chain must be reconstructable:

```
R4 DECISION
    ↓
RISK AUTHORIZATION
    ↓
ORDER
    ↓
BROKER ACK
    ↓
FILL
    ↓
POSITION
    ↓
RECONCILIATION
    ↓
P&L
```

---

## 11. AFTER THE FIRST ORDER

- Do NOT immediately scale.
- Do NOT modify the strategy based on the first trade.
- Do NOT tune parameters.
- Do NOT add new hypotheses.
- Do NOT optimize for short-term P&L.

Instead verify:

- order was correctly attributed to R4
- broker/internal state reconciles
- requested/fill quantities reconcile
- risk exposure is correct
- position limits remain enforced
- health monitor remains operational
- alerts were emitted
- execution costs were recorded
- campaign boundary remains intact
- no configuration drift occurred

Then continue the predefined MINIMAL campaign.

---

## 12. FAIL-CLOSED RULE

At ANY point, if there is:

- identity drift
- configuration drift
- broker mismatch
- unexplained position
- manual trade
- reconciliation mismatch
- missing exposure data
- risk-policy failure
- health failure
- stale data
- disconnect requiring reconciliation
- partial-fill inconsistency
- execution anomaly
- position-limit breach
- unexpected broker behavior
- missing observability
- alerting failure that violates the audit contract

**STOP NEW ENTRIES.**

Transition to the appropriate:

```
MANAGE_ONLY
HALT
HALT_RECONCILE_OR_FLATTEN
FROZEN
```

state according to the existing state machines.

Never solve a safety failure by weakening the control.

---

## 13. FINAL INSTRUCTION

Do not simply tell me that the account is funded and begin trading.

First perform the complete broker-connected pre-trading gate.

If the gate passes:

```
report TRADING_AUTHORIZED
```

and then allow the normal frozen R4 execution loop to operate.

If the gate fails:

```
report TRADING_BLOCKED
```

with every blocking reason and DO NOT submit any order.

The objective is not:
> "get the first trade executed."

The objective is:
> "prove that the exact frozen R4 system can safely transition from a $5K
> funded account to real broker execution without violating any previously
> validated invariant."

The first real order is evidence. Treat it accordingly.
