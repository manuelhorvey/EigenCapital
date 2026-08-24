# EigenCapital Research Engine Contract

The constitution of the backtester. Every simulation component must conform to this document.

---

## Core Principle

> **Signal at time t CANNOT use information unavailable at time t.**

A backtester that violates this single principle is worse than no backtester at all.

---

## Timestamp Semantics

### Signal Timestamp (`t_signal`)

- When the strategy generates a trading signal
- The strategy has access to all data **up to and including** bar `t_signal`
- The strategy has **zero access** to data after bar `t_signal`

### Information Cutoff (`t_info`)

- `t_info = t_signal` (same as signal timestamp)
- No future bars, no future prices, no future volume
- No future feature values, no future model outputs

### Order Submission Timestamp (`t_submit`)

- When the order is submitted to the execution engine
- `t_submit >= t_signal` (order cannot precede signal)
- In backtesting: `t_submit = t_signal + minimum_latency`

### Fill Timestamp (`t_fill`)

- When the order is executed (filled)
- `t_fill >= t_submit` (fill cannot precede submission)
- In backtesting: fill occurs on a **subsequent bar** after submission
- **Never fill at the same bar as the signal** unless explicitly configured

### Execution Delay

- Minimum delay: 1 bar interval after signal
- Default: next-bar execution (`t_fill = t_signal + bar_interval`)
- Configurable per-backtest, but must be explicit

---

## Information Availability Rules

### At Signal Time (`t_signal`)

**Available:**
- All bars with `timestamp <= t_signal`
- All features computed from those bars
- Current position state
- Current cash/equity state
- Portfolio state

**NOT Available:**
- Bars with `timestamp > t_signal`
- Future feature values
- Future prices or volume
- Fills that haven't occurred yet
- Future risk decisions

### At Execution Time (`t_fill`)

**Available:**
- Everything available at `t_signal`
- Additional bars between `t_signal` and `t_fill`
- Market conditions at execution time (for slippage/spread estimation)

---

## Execution Model

### Bar-Close Execution

- Default assumption: orders fill at the **close** of the bar
- This is conservative and avoids look-ahead bias
- The fill price is `bar.close`

### Next-Bar Execution

- Signal on bar `t`, fill on bar `t+1`
- This is the standard backtesting convention
- Prevents using the same bar's close as both signal and fill price

### Spread Model

- Fill price includes spread impact
- `fill_price = bar.close + spread_impact`
- Spread impact depends on order side:
  - BUY: `fill_price = mid + spread/2`
  - SELL: `fill_price = mid - spread/2`

### Slippage Model

- Additional price impact beyond spread
- `fill_price += slippage_impact`
- Slippage can be:
  - Fixed (e.g., 1 tick)
  - Proportional (e.g., 0.01% of price)
  - Volume-dependent (larger orders = more slippage)

### Partial Fills

- Large orders may not fill completely in one bar
- Model: `filled_qty = min(order_qty, available_liquidity)`
- Remaining quantity is re-submitted in subsequent bars
- Partial fill price uses same spread/slippage model

### Order Rejection

- Orders can be rejected (insufficient liquidity, etc.)
- Rejected orders do not generate fills
- Strategy must handle rejection gracefully

---

## Position Accounting

### Long Position

```
cash -= fill_price * quantity * multiplier
position.quantity += quantity
position.average_entry_price = weighted_average(position.average_entry_price, fill_price, quantity)
```

### Short Position

```
cash += fill_price * quantity * multiplier  (receive proceeds)
position.quantity -= quantity
position.average_entry_price = weighted_average(position.average_entry_price, fill_price, quantity)
```

### Position Close

```
unrealized_pnl = (current_price - average_entry_price) * quantity * multiplier
cash += fill_price * quantity * multiplier + unrealized_pnl
position.quantity = 0
```

### P&L Calculation

```
realized_pnl = Σ(fill_price_i - average_entry_price) * quantity_i * multiplier
unrealized_pnl = (current_price - average_entry_price) * remaining_quantity * multiplier
total_pnl = realized_pnl + unrealized_pnl
equity = initial_cash + total_pnl - total_costs
```

---

## Cost Model Integration

Every backtest MUST apply costs. No cost-free backtests.

### Required Cost Components

| Component | Description |
|-----------|-------------|
| Commission | Fixed per-contract/share cost |
| Exchange Fee | Regulatory/exchange fees |
| Spread | Bid-ask spread impact |
| Slippage | Price impact of execution |
| Market Impact | Large-order price impact (optional) |

### Cost Sensitivity Analysis

Run backtests at multiple cost levels:
- `optimistic`: Minimal realistic costs
- `baseline`: Typical market costs
- `stress`: Elevated costs
- `extreme`: Worst-case costs

A strategy that only works under optimistic costs should be **rejected**.

---

## Missing Data Handling

### Missing Bar

- Gap in the bar series (e.g., holiday, data failure)
- Strategy cannot generate signals during gaps
- Positions held through gaps are marked-to-market using available data

### Duplicate Bar

- Same timestamp appears twice → **INVALID**
- Backtester must detect and reject duplicates

### Out-of-Order Bar

- Bars arrive in wrong temporal order → **INVALID**
- Backtester must sort bars chronologically before processing

---

## Market Closures

- No trading during closed sessions
- Positions held overnight are subject to:
  - Gap risk (next open may differ from last close)
  - Financing costs (for leveraged positions)
  - Corporate actions (splits, dividends)

---

## Backtest Result Identity

Every backtest result MUST be traceable to:

```
Experiment
    ↓
Git commit
    ↓
Dataset version
    ↓
Strategy version
    ↓
Parameter hash
    ↓
Cost model
    ↓
Backtest engine version
    ↓
Risk configuration
    ↓
Execution assumptions (delay, spread, slippage)
    ↓
Results
```

This is enforced through the provenance hash computed by the backtest engine.

---

## Trial Accounting (Mandatory)

Every research experiment MUST be able to answer:

> **How many materially distinct opportunities did we try before selecting this result?**

A final Sharpe of 1.8 means something entirely different if it was the first
hypothesis tested versus the best of 500 parameter/feature/model combinations.
This information must survive permanently in the research ledger.

### Trial Family

All related searches constitute a **trial family**:

```
Trend hypothesis
 ├── lookback 20
 ├── lookback 40
 ├── lookback 60
 ├── lookback 80
 ├── stop 1 ATR
 ├── stop 1.5 ATR
 ├── stop 2 ATR
 └── different universes
```

Each member of a family carries `TrialMetadata` on its experiment record:

| Field | Meaning |
|---|---|
| `trial_group_id` | Identifier of the family/search |
| `trial_index` | 1-based ordinal of this trial within the family |
| `trials_in_family` | Total distinct trials known (None while search is open) |
| `hypothesis_family` | Research family label (trend, momentum, ...) |
| `parameter_search_space` | Declared space searched by the family |
| `selection_method` | How this configuration was chosen from the family |

### Rules

1. **Every experiment that participates in any search carries trial metadata.**
   Single-shot experiments may declare `selection_method = "single_candidate"`
   with `trial_index = 1`.
2. **Trial identity is fixed at registration** (PRE_REGISTERED). It is
   provenance, not a tunable field, and must never be modified post-freeze.
3. **`selection_method` must never claim out-of-sample merit for an
   in-sample selection.** Selecting the best validation-Sharpe config from a
   grid is legitimate; reporting that config's test Sharpe as if it were the
   only attempt is not.
4. **Family size is monotone.** `trials_in_family >= max(trial_index)` over all
   members; closing a family fixes the count permanently.
5. **Candidate promotion requires closed accounting.** An experiment cannot be
   promoted to CANDIDATE while its `trials_in_family` is open (search ongoing)
   — the deflated performance estimate needs the final trial count.
6. **Reported metrics are conditioned on trials.** Any headline result
   (report, tear sheet, paper-trading proposal) must state the trial context:
   `trial i/n`, selection method, and search-space size.

### Rationale

These fields exist to make selection bias quantifiable (e.g., deflated Sharpe
ratio, Bailey & Prado) and to prevent the ledger itself from becoming a
record of survivorship-biased results.

---

## Anti-Patterns (Explicitly Prohibited)

### Look-Ahead Bias

Using information from the future to make decisions at time t.

### Survivorship Bias

Only including instruments that "survived" (e.g., only current constituents of an index).

### Overfitting

Tuning parameters on test data. The experiment framework prevents this through parameter freezing.

### Data Snooping

Testing the same hypothesis multiple times without correction. The hypothesis registry tracks all tests.

### Cost-Free Trading

Running backtests without realistic costs. The cost model is mandatory.

### Silent Data Repair

Automatically fixing suspicious data instead of flagging it. The validation layer prevents this.
