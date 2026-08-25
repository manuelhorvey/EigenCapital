# RESEARCH ACCOUNTING CONTRACT

**Status:** Authoritative. Research code that violates this contract is wrong.

## Rule 1 — Costs live inside the return series

For any strategy evaluation where turnover is material (rule of thumb:
> 1,000 position changes per instrument-year), net performance MUST be
computed per bar:

```
signal → position(t) → gross_return(t)
       → flip(t) = |position(t) − position(t−1)|
       → net_return(t) = gross_return(t) − flip(t) × cost_one_way
       → Sharpe / DD / expectancy computed on net_return
```

Reporting a "net Sharpe" derived from gross per-bar returns with costs
applied only to total return is **forbidden as evidence**. (This was the
Campaigns 4–7 engine defect; see the intraday ledger.)

The reference implementation is:

```python
from eigencapital.research.intraday.campaign8_tf003_confirmation import (
    bt_corrected,          # NetResult: gross/net Sharpe, flips, exposure,
                           # cost drag, net DD, worst bar
    COST_ONE_WAY_BASE,     # 6.5 bps
    COST_ONE_WAY_ADVERSE,  # 11 bps
)
```

Its behavior is locked by `tests/unit/research/intraday/test_campaign8.py`
(hand-computed flip accounting; cost monotonicity; perfect-foresight
economics). Do not weaken those tests.

## Rule 2 — Permutation significance must be family-corrected

No hypothesis may be reported SUPPORTED on a raw permutation p-value when it
was evaluated inside a family. Bonferroni (or exact max-statistic) correction
over the pre-registered family size is required, and the program-wide
cumulative trial ledger carries forward across campaigns.

Reference implementation:
`eigencapital.research.intraday.campaign7_rerun_hardened`
(`family_adjust`, `cumulative_adjust`, `PRIOR_EVALUATIONS`).

## Rule 3 — Turnover economics are part of the verdict

A signal whose per-trade edge is smaller than its round-trip cost is
REJECTED regardless of gross Sharpe. Gross predictiveness without net
viability is recorded as forensic knowledge, never as an alpha candidate.

## Rule 4 — Fail-closed defaults

Missing corrections default to rejection (`INCONCLUSIVE`/`REJECTED`),
never to a pass. Loosening any gate to make a result pass violates the
project's core contract.
