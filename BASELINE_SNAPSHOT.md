# LIVE SYSTEM BASELINE SNAPSHOT

DO NOT EDIT. Generated for regression testing before any refactoring.
Date: 2026-05-19
Source: paper_trading/engine.py, paper_trading/decision.py,
        paper_trading/position_manager.py, features/builder.py,
        labels/triple_barrier.py, configs/paper_trading.yaml

---

## 1. EXECUTION PATH

Entry: `paper_trading/monitor.py:main()`
Loop: `while not _shutdown.wait(1800)` at line 64
Each iteration: `engine.run_once()` then `engine.save_state()`

## 2. MODEL

**Type:** `xgboost.XGBClassifier`
**Constructor args (engine.py:251-255):**
```
n_estimators=300
max_depth=2
learning_rate=0.02
objective='multi:softprob'
num_class=3
random_state=42
n_jobs=1
tree_method='hist'
verbosity=0
```
**Call:** `proba = self.model.predict_proba(X)` at engine.py:285
**Output shape:** `(N, 3)`, dtype float64
**Class indices:** `0=short, 1=neutral, 2=long`
**Serialization:** `pickle.dump/load` to `paper_trading/models/{name}_model.pkl`
**Training split:** 80/20 chronological, last 5 years of data (or all if <200 rows)
**Training set:** last {retrain_window} years of feature rows, min 200 rows

## 3. SIGNAL THRESHOLD LOGIC (engine.py:289-293)

```
threshold = 0.45  (default param of generate_signal() and _generate_and_apply())

probs_long  = proba[:, 2]    # class index 2
probs_short = proba[:, 0]    # class index 0

signals = pd.Series(0, index=X.index)   # default 0 = neutral/FLAT
signals[probs_short > threshold] = 0    # SELL → assignment order matters
signals[probs_long > threshold] = 2     # BUY  → overwrites if both true
```

**Result:**
| Condition | signal | label |
|---|---|---|
| prob_long > 0.45 AND prob_short <= 0.45 | 2 | BUY |
| prob_short > 0.45 AND prob_long <= 0.45 | 0 | SELL |
| BOTH > 0.45 | 2 | BUY (long wins due to order) |
| BOTH <= 0.45 | 0 | FLAT (neutral) |

**Signal string mapping (engine.py:309):**
```
signal_type = 'BUY'  if latest_signal == 2
            = 'SELL' if latest_signal == 0
            = 'FLAT' otherwise
```

**Confidence (engine.py:310):**
```
confidence = max(prob_long, prob_short)
confidence_pct = round(confidence * 100, 2)
```

## 4. POSITION SIZING (engine.py:178-186, 295)

```
def _vol_scalar(df, window=30, target_vol=0.30):
    rets = df['close'].pct_change().dropna()
    if len(rets) < window: return 1.0
    rv = rets.iloc[-window:].std() * sqrt(252)
    if isnan(rv) or isinf(rv): return 1.0
    scalar = target_vol / (rv + 1e-9)
    return min(scalar, 1.0)

pos_size = _vol_scalar(df) if config.get('vol_scalar') else 1.0
```

Applied only when `config.vol_scalar = true` (currently BTC only).
All others: `pos_size = 1.0`.

## 5. POSITION ENTRY / SL / TP

**Volatility for SL/TP (engine.py:188-191):**
```
returns = log(close / close.shift(1))
vol = returns.ewm(span=100).std()
vol = last_value if not nan else 0.01
```

**SL/TP formula (decision.py:37-44):**
```
sl_mult_effective = sl_mult * validity_sl_mult
tp_mult_effective = tp_mult * validity_tp_mult

if side == "long":
    sl = entry_price * (1 - vol * sl_mult_effective)
    tp = entry_price * (1 + vol * tp_mult_effective)
else:  # short
    sl = entry_price * (1 + vol * sl_mult_effective)
    tp = entry_price * (1 - vol * tp_mult_effective)
```

**Multipliers (from configs/paper_trading.yaml):**
- Base: sl_mult ≈ 0.30 (research-optimized, sweep-derived), tp_mult per-asset (1.00–1.75)
- Validity adjustment: GREEN=1.0×, YELLOW=0.85× (TP only), RED=0.70× (TP only)

## 6. POSITION MANAGEMENT

**Open (position_manager.py:26-27):**
```
def open(self, intent): self.position = intent
```

**Close (position_manager.py:29-55):**
```
side = position.side
entry = position.entry_price
ret = (exit/entry - 1) if long else (entry/exit - 1)
pnl = current_value * ret * position_size  # position_size = 0.95
current_value += pnl
peak_value = max(current_value, peak_value)
```

**SL/TP check (position_manager.py:57-75):**
```
if long:
    current_price <= sl → stop loss hit, return ("sl", sl)
    current_price >= tp → take profit hit, return ("tp", tp)
if short:
    current_price >= sl → stop loss hit, return ("sl", sl)
    current_price <= tp → take profit hit, return ("tp", tp)
```

**Position flip (engine.py:334-338):**
```
if new_side != current_side:
    if has_position(): close with reason 'signal_flip'
    if new_side: open new position
```

## 7. DAILY PnL (engine.py:383-427)

```
if has_position():
    check SL/TP:
        hit → close_position() and return
    if still has_position → return  # position-tracked, no signal PnL

# Signal-based PnL (only when no open position)
sig = signal_data['signal'].iloc[-2]
direction = 1 if sig==2 else -1 if sig==0 else 0
prev_close = close.iloc[-2]
today_close = close.iloc[-1]
ret = today_close / prev_close - 1
pnl = current_value * direction * ret * 0.95 * pos_size
```

## 8. FEATURE ENGINEERING

**Macro derived features (builder.py:20-35):**
```
rate_diff = fed_funds - ecb_rate
2y_yield_delta_63 = us_2y.diff(63)
dxy_mom_63 = dxy.pct_change(63)
dxy_mom_21 = dxy.pct_change(21)
vix_ma21 = vix.rolling(21).mean()
vix_delta_5 = vix.diff(5)
us_jp_10y_spread = us_10y - jp_10y
ca_jp_10y_spread = ca_10y - jp_10y
ca_jp_spread_mom_21 = ca_jp_10y_spread.diff(21)
ca_jp_spread_mom_5 = ca_jp_10y_spread.diff(5)
real_yield_delta_63 = real_yield_10y.diff(63)
breakeven_delta_63 = breakeven_10y.diff(63)
```


**Asset-specific features (builder.py:59-66):**
```
for w in contract.price_mom_windows:
    a[f'{slug}_mom_{w}'] = df['close'].pct_change(w)

for w in contract.vs_spy_windows:
    mom = df['close'].pct_change(w)
    spy_mom = ref['close'].pct_change(w)
    a[f'{slug}_vs_spy_{w}'] = mom - spy_mom
```

**Label computation (builder.py:38-46):**
```
if label_type == 'fwd60':
    ret = close.pct_change(60).shift(-60)
    label = 2 if ret > 0.02 else (0 if ret < -0.02 else 1)
else:  # tb20
    labeled = apply_triple_barrier(df, pt_sl=[2,2], vertical_barrier=20)
    label = labeled['label'] + 1  # {-1,0,1} → {0,1,2}
```

## 9. HALT CONDITIONS (engine.py:530-565)

Default thresholds from config:
```
drawdown: -0.08    # halt if drawdown <= -8%
monthly_pf: 0.70   # halt if monthly profit factor < 0.70
signal_drought: 30  # halt if no signal in 30 days
prob_drift: 0.15    # halt if |mean_conf - 0.45| > 0.15
```

Per-asset overrides (BTC: -0.15 drawdown, NZDJPY: -0.06 drawdown).

**Validity state (engine.py:515-528):**
```
score = 0.80 (starting)
score -= 0.25 if drawdown_not_ok
score -= 0.20 if monthly_pf_not_ok
score -= 0.15 if drought_not_ok
score -= 0.15 if drift_not_ok
score = clip(0.0, 1.0, score)
→ ValidityStateMachine.transition(score)
```

## 10. PORTFOLIO ALLOCATION (engine.py:587-599)

| Asset | Allocation | Ticker | Vol Scalar |
|---|---|---|---|
| BTC | 0.20 | BTC-USD | yes |
| NZDJPY | 0.15 | NZDJPY=X | no |
| CADJPY | 0.13 | CADJPY=X | no |
| USDCAD | 0.10 | USDCAD=X | no |
| GC | 0.20 | GC=F | no |
| EURAUD | 0.22 | EURAUD=X | no |

Capital: $100,000 (from config)
Position size fraction: 0.95 (from config)
Initial per-asset capital = $100,000 * allocation

## 11. STATE PERSISTENCE

**Save path:** `data/live/`
**State file:** `state.json` (EngineSnapshot dataclass → JSON)
**Trade journal:** `trade_journal.parquet` (appended)
**Confidence buckets:** `confidence_buckets.parquet` (appended)
**Equity history:** `equity_history.json` (JSON list, last 2000 entries)
**Cache dir:** `data/live/cache/` (yfinance data per ticker as parquet)
