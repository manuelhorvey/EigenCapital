"""Trade-path metrics: MAE/MFE, time-to-events, underwater, oscillation.

All metrics are computed from the realized D1 bar path between entry fill
and exit fill of a PathTrade — descriptive reconstruction of history, not
a signal. Definitions (frozen in config, never tuned):

  direction d            +1 LONG / -1 SHORT
  u_t                    d * (px_t / entry_px - 1)   unrealized asset return
  path points            entry_px, closes of bars in [entry, exit), exit_px
                         (open-of-bar exits); terminal exits use the final
                         close. Exit-bar intrabar extremes are included in
                         MAE/MFE (daily granularity limitation, documented).
  MAE / MFE              max adverse / max favorable unrealized move (>=0)
  time_to_first_profit   first bar index (1-based) with u > 0; None sentinel
                          NO_PROFIT_BEFORE_EXIT if never
  underwater             u < 0 at path closes (price path, pre-cost;
                          net variant uses u > 2*one_way cost to profit)
  oscillation            entry crossings = sign changes of non-zero
                          (px - entry); P&L sign changes on non-zero u
  path_efficiency        |exit - entry| / path_length (np.nan if no motion)

Entry regime is labeled from RV information through the SIGNAL date only
(regimes.shift so bars < entry_ts are used — PIT).
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass

import pandas as pd

from research.volatility import config as C
from research.volatility import features as F
from research.volatility import regimes as R
from research.volatility.trade_stream import PathTrade

NO_PROFIT = "NO_PROFIT_BEFORE_EXIT"


@dataclass(frozen=True)
class TradePathMetrics:
    trade_id: int
    instrument: str
    asset: str
    side: str
    signal_date: str
    entry_ts: str
    exit_ts: str
    holding_bars: int
    holding_days: float
    entry_regime: str | None
    entry_regime_z: str | None
    entry_rv: float
    entry_rv_pctile: float | None
    entry_daily_sigma: float
    entry_weight: float
    # excursions (asset-return space)
    mae_ret: float
    mfe_ret: float
    mae_sigma: float
    mfe_sigma: float
    mae_sigma_period: float
    mfe_sigma_period: float
    time_to_mae: int | None
    time_to_mfe: int | None
    time_to_first_profit: int | None
    time_to_first_profit_str: str | None
    first_profit_bar: int | None
    # underwater
    underwater_bars: int
    max_underwater_run: int
    underwater_fraction: float
    underwater_bars_net: int
    max_underwater_run_net: int
    underwater_fraction_net: float
    # oscillation
    entry_crossings: int
    pl_sign_changes: int
    crossings_per_bar: float
    path_length: float
    net_displacement: float
    path_efficiency: float
    # economics
    net_pnl: float
    costs: float
    gross_pnl: float
    exit_u_ret: float
    # large-move / delayed expansion (pre-specified k)
    large_favorable: bool
    time_to_large_favorable: int | None
    initial_phase_underwater: bool
    delayed_expansion: bool
    # descriptive trade type (deterministic rule)
    trade_type: str


def _sign_changes(nonzero_signs: list[int]) -> int:
    return sum(1 for a, b in zip(nonzero_signs, nonzero_signs[1:]) if a != b)


def _max_run(flags: list[bool]) -> int:
    best = cur = 0
    for v in flags:
        cur = cur + 1 if v else 0
        best = max(best, cur)
    return best


def compute_trade_path(
    trade: PathTrade,
    bars: pd.DataFrame,
    rv: pd.Series,
    rv_pctile: pd.Series,
    regimes_pct: pd.Series,
    regimes_z: pd.Series,
) -> TradePathMetrics | None:
    """Return metrics for one trade, or None if the bar path is missing.

    `rv`, `rv_pctile`, `regimes_*` are full-history series for the trade's
    instrument; only observations strictly before entry_ts are used for
    entry labeling (PIT).
    """
    entry, exit_ = pd.Timestamp(trade.entry_ts), pd.Timestamp(trade.exit_ts)
    if entry not in bars.index or exit_ not in bars.index:
        return None
    seg = bars.loc[entry:exit_]
    if seg.empty:
        return None

    d = 1.0 if trade.side == "LONG" else -1.0
    entry_px = trade.entry_px
    if entry_px <= 0:
        return None

    # ── entry info (PIT: strictly before entry bar) ─────────────────
    prior = rv.index[rv.index < entry]
    entry_rv = float(rv.loc[prior[-1]]) if len(prior) and pd.notna(rv.loc[prior[-1]]) else float("nan")
    entry_pct = float(rv_pctile.loc[prior[-1]]) if len(prior) and pd.notna(rv_pctile.loc[prior[-1]]) else None
    entry_daily_sigma = entry_rv / math.sqrt(C.ANNUALIZATION) if math.isfinite(entry_rv) else float("nan")

    def _reg_before(reg: pd.Series) -> str | None:
        p = reg.index[reg.index < entry]
        if not len(p):
            return None
        v = reg.loc[p[-1]]
        return None if pd.isna(v) else str(v)

    # ── path points ─────────────────────────────────────────────────
    # closes observed after entry: bars in [entry, exit) then exit fill px.
    mid_closes = seg.index[seg.index < exit_]
    points: list[float] = [entry_px]
    for ts in mid_closes:
        points.append(float(bars.at[ts, "close"]))
    points.append(trade.exit_px)
    holding_bars = len(seg)
    holding_days = float((exit_ - entry).days)

    # unrealized returns at path observation points (for time/underwater),
    # evaluated at closes of observed bars (plus terminal exit px).
    obs_ts = list(mid_closes)
    u_obs = [d * (float(bars.at[ts, "close"]) / entry_px - 1.0) for ts in obs_ts]
    u_final = d * (trade.exit_px / entry_px - 1.0)
    u_series = u_obs + [u_final]

    # MAE/MFE over intrabar extremes of every bar in [entry, exit]
    # (side-aware: adverse = against the position, favorable = with it)
    if d > 0:
        adv_ext = float(seg["low"].min())
        fav_ext = float(seg["high"].max())
        mae_ret = max(0.0, (entry_px - adv_ext) / entry_px)
        mfe_ret = max(0.0, (fav_ext - entry_px) / entry_px)
    else:
        adv_ext = float(seg["high"].max())
        fav_ext = float(seg["low"].min())
        mae_ret = max(0.0, (adv_ext - entry_px) / entry_px)
        mfe_ret = max(0.0, (entry_px - fav_ext) / entry_px)

    # time to MAE/MFE: first bar (1-based) whose extreme, measured in
    # RETURN space, reaches the overall adverse/favorable extreme
    def _time_to_extreme(is_adverse: bool) -> int:
        for i, (_, row) in enumerate(seg.iterrows(), start=1):
            if d > 0:
                ext_ret = ((entry_px - row["low"]) if is_adverse else (row["high"] - entry_px)) / entry_px
            else:
                ext_ret = ((row["high"] - entry_px) if is_adverse else (entry_px - row["low"])) / entry_px
            target = mae_ret if is_adverse else mfe_ret
            if target > 0 and ext_ret >= target - 1e-15:
                return i
        return holding_bars

    time_to_mae = _time_to_extreme(True) if mae_ret > 0 else None
    time_to_mfe = _time_to_extreme(False) if mfe_ret > 0 else None

    # time to first profit (u > 0), including same-bar close
    first_profit: int | None = None
    for i, u in enumerate(u_series, start=1):
        if u > 0:
            first_profit = i
            break

    # underwater at observed closes (pre-cost)
    under = [u < 0 for u in u_obs]
    n_obs = max(len(u_obs), 1)
    underwater_bars = int(sum(under))
    max_uw_run = _max_run(under)
    uw_frac = underwater_bars / n_obs if u_obs else 0.0

    # net-of-cost variant: profitable only after both cost legs recovered
    # (asset-space round-trip cost = 2 * one_way, independent of |w|).
    cost_asset = 2.0 * C.R4_COST_ONE_WAY
    under_net = [u < cost_asset for u in u_obs]
    uw_net = int(sum(under_net))
    max_uw_net = _max_run(under_net)
    uw_frac_net = uw_net / n_obs if u_obs else 0.0

    # oscillation: sign sequence of non-zero deviations
    devs = [float(bars.at[ts, "close"]) - entry_px for ts in obs_ts]

    def _nz_signs(vals: list[float]) -> list[int]:
        signs = [int(math.copysign(1, v)) for v in vals if v != 0.0]
        return signs

    entry_crossings = _sign_changes(_nz_signs(devs))
    pl_sign_changes = _sign_changes(_nz_signs(u_obs))

    # path length over points
    deltas = [abs(points[i] - points[i - 1]) for i in range(1, len(points))]
    path_length = float(sum(deltas))
    net_disp = float(abs(points[-1] - points[0]))
    efficiency = (net_disp / path_length) if path_length > 0 else float("nan")

    # large favorable move (pre-specified k, unscaled daily sigma)
    large = bool(math.isfinite(entry_daily_sigma) and mfe_ret > C.LARGE_MOVE_K_SIGMA * entry_daily_sigma)
    time_large = time_to_mfe if large else None

    # initial phase: first min(INITIAL_PHASE_BARS, holding) observations underwater
    n_init = min(C.INITIAL_PHASE_BARS, len(u_obs))
    init_under = n_init > 0 and all(u <= 0 for u in u_obs[:n_init])
    delayed = bool(init_under and large and (time_large or 0) > n_init)

    # descriptive trade type (deterministic first-match rule)
    sigma = entry_daily_sigma if math.isfinite(entry_daily_sigma) and entry_daily_sigma > 0 else float("nan")
    eff = efficiency
    if (
        first_profit is not None
        and first_profit <= 1
        and math.isfinite(sigma)
        and mae_ret <= C.SIGMA_HALF_SIGMA * sigma
        and u_final > 0
        and eff == eff
        and eff >= 0.5
    ):
        ttype = "A_immediate_directional"
    elif u_final < 0 and time_to_mae is not None and time_to_mfe is not None and time_to_mae > time_to_mfe:
        ttype = "D_persistent_adverse"
    elif first_profit is not None and first_profit <= 1 and u_final < 0:
        ttype = "E_immediate_fav_reversal"
    elif (
        math.isfinite(sigma)
        and mae_ret >= C.SIGMA_HALF_SIGMA * sigma
        and time_to_mae is not None
        and holding_bars >= 2
        and time_to_mae <= max(1, holding_bars // 2)
        and u_final > 0
    ):
        ttype = "B_early_adverse_recovery"
    elif entry_crossings >= 3 and math.isfinite(sigma) and mfe_ret >= 1.0 * sigma and u_final > 0:
        ttype = "C_oscillation_expansion"
    elif u_final < 0:
        ttype = "D_persistent_adverse"
    else:
        ttype = "OTHER"

    return TradePathMetrics(
        trade_id=trade.trade_id,
        instrument=trade.instrument,
        asset=trade.asset,
        side=trade.side,
        signal_date=pd.Timestamp(trade.signal_date).strftime("%Y-%m-%d"),
        entry_ts=entry.strftime("%Y-%m-%d"),
        exit_ts=exit_.strftime("%Y-%m-%d"),
        holding_bars=holding_bars,
        holding_days=holding_days,
        entry_regime=_reg_before(regimes_pct),
        entry_regime_z=_reg_before(regimes_z),
        entry_rv=entry_rv,
        entry_rv_pctile=entry_pct,
        entry_daily_sigma=entry_daily_sigma,
        entry_weight=trade.weight,
        mae_ret=mae_ret,
        mfe_ret=mfe_ret,
        mae_sigma=mae_ret / sigma if sigma == sigma and sigma > 0 else float("nan"),
        mfe_sigma=mfe_ret / sigma if sigma == sigma and sigma > 0 else float("nan"),
        mae_sigma_period=(
            mae_ret / (sigma * math.sqrt(max(holding_days, 1.0))) if sigma == sigma and sigma > 0 else float("nan")
        ),
        mfe_sigma_period=(
            mfe_ret / (sigma * math.sqrt(max(holding_days, 1.0))) if sigma == sigma and sigma > 0 else float("nan")
        ),
        time_to_mae=time_to_mae,
        time_to_mfe=time_to_mfe,
        time_to_first_profit=first_profit,
        time_to_first_profit_str=NO_PROFIT if first_profit is None else None,
        first_profit_bar=first_profit,
        underwater_bars=underwater_bars,
        max_underwater_run=max_uw_run,
        underwater_fraction=uw_frac,
        underwater_bars_net=uw_net,
        max_underwater_run_net=max_uw_net,
        underwater_fraction_net=uw_frac_net,
        entry_crossings=entry_crossings,
        pl_sign_changes=pl_sign_changes,
        crossings_per_bar=entry_crossings / holding_bars if holding_bars else float("nan"),
        path_length=path_length,
        net_displacement=net_disp,
        path_efficiency=efficiency,
        net_pnl=trade.net_pnl,
        costs=trade.costs,
        gross_pnl=trade.net_pnl + trade.costs,
        exit_u_ret=u_final,
        large_favorable=large,
        time_to_large_favorable=time_large,
        initial_phase_underwater=init_under,
        delayed_expansion=delayed,
        trade_type=ttype,
    )


def build_path_metrics(
    trades: list[PathTrade],
    ohlc: dict[str, pd.DataFrame],
) -> tuple[pd.DataFrame, dict]:
    """Compute metrics for the whole population. Returns (DataFrame, audit)."""
    rows: list[dict] = []
    skipped = 0
    cache: dict[str, dict] = {}
    for trade in trades:
        stem = trade.instrument
        if stem not in ohlc:
            skipped += 1
            continue
        if stem not in cache:
            df = ohlc[stem]
            rv = F.realized_vol(df["close"], C.PRIMARY_RV)
            cache[stem] = {
                "bars": df,
                "rv": rv,
                # PIT percentile of RV vs all strictly-prior RV values
                "rv_pctile": rv.expanding(min_periods=250).rank(pct=True),
                # entry-regime labels: both variants are PIT by construction
                "reg_pct": R.expanding_percentile_regimes(rv),
                "reg_z": R.zscore_regimes(rv),
            }
        c = cache[stem]
        m = compute_trade_path(trade, c["bars"], c["rv"], c["rv_pctile"], c["reg_pct"], c["reg_z"])
        if m is None:
            skipped += 1
            continue
        rows.append(asdict(m))
    frame = pd.DataFrame(rows)
    audit = {
        "n_trades_in": len(trades),
        "n_metrics": len(frame),
        "n_skipped": skipped,
        "skip_reason": "missing bars for entry/exit timestamps",
    }
    return frame, audit
