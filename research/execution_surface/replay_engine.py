"""Phase A.2 — Replay frozen signals with OHLC-driven lifecycle simulation.

Given frozen OOS predictions (with OHLC bars) and candidate (sl_mult, tp_mult),
simulate trade lifecycle using High/Low for barrier checks.

Trade policy (explicit):
- Single active position per asset
- Hard close before reversal (no flipping without closing first)
- No pyramiding
- OHLC bars drive lifecycle simulation (not prediction frequency)

Extended replay functions:
  - replay() — fixed sl_mult/tp_mult for all trades
  - replay_regime() — regime-dependent sl_mult/tp_mult per trade
  - replay_meta_geometry() — meta-model adjusts geometry per trade
"""

import pandas as pd
import numpy as np
from dataclasses import dataclass, field
from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from shared.meta_labeling import MetaModel


@dataclass
class ReplayConfig:
    sl_mult: float = 1.0
    tp_mult: float = 2.5


@dataclass
class ReplayRegimeConfig:
    """Regime-conditional geometry configuration.

    Maps regime labels (from predictions['regime']) to (sl_mult, tp_mult).
    Unknown regimes fall back to default_geom.
    """
    regime_geom: dict = field(default_factory=lambda: {
        'low_vol':    {'sl_mult': 0.52, 'tp_mult': 1.96},
        'transition': {'sl_mult': 0.65, 'tp_mult': 1.65},
        'high_vol':   {'sl_mult': 0.75, 'tp_mult': 1.50},
    })
    default_geom: dict = field(default_factory=lambda: {'sl_mult': 0.65, 'tp_mult': 1.65})


@dataclass
class PositionState:
    side: str
    entry_price: float
    entry_time: pd.Timestamp
    sl_price: float
    tp_price: float
    vol_at_entry: float
    conf_at_entry: float
    entry_idx: int  # row index in the predictions DataFrame


def check_barrier_hit(row: pd.Series, pos: PositionState) -> Optional[tuple[str, float]]:
    """Check if High/Low breached SL/TP for a given bar.

    Returns ('sl', exit_price) or ('tp', exit_price) or None.
    Uses high for TP triggers (long) and SL triggers (short).
    Uses low for SL triggers (long) and TP triggers (short).
    """
    high = float(row['high'])
    low = float(row['low'])

    if pos.side == 'long':
        if low <= pos.sl_price:
            return ('sl', pos.sl_price)
        if high >= pos.tp_price:
            return ('tp', pos.tp_price)
    else:
        if high >= pos.sl_price:
            return ('sl', pos.sl_price)
        if low <= pos.tp_price:
            return ('tp', pos.tp_price)
    return None


def compute_trade_return(side: str, entry: float, exit_price: float) -> float:
    if side == 'long':
        return exit_price / entry - 1.0
    else:
        return entry / exit_price - 1.0


def replay(predictions: pd.DataFrame, config: ReplayConfig) -> pd.DataFrame:
    """Replay frozen predictions through lifecycle simulation.

    Args:
        predictions: DataFrame with columns [open, high, low, close, signal,
                     prob_long, prob_short, prob_neutral, confidence,
                     volatility, atr, year, regime]
        config: ReplayConfig with sl_mult and tp_mult

    Returns:
        DataFrame of trade records with columns:
        entry_time, exit_time, side, entry_price, exit_price,
        sl_price, tp_price, reason, hold_bars, return_pct,
        vol_at_entry, conf_at_entry, year, regime
    """
    trades = []
    pos: Optional[PositionState] = None

    for idx, (timestamp, row) in enumerate(predictions.iterrows()):
        signal = int(row['signal'])
        close = float(row['close'])

        # 1. Check existing position for SL/TP hit (using H/L)
        if pos is not None:
            hit = check_barrier_hit(row, pos)
            if hit is not None:
                reason, exit_price = hit
                ret = compute_trade_return(pos.side, pos.entry_price, exit_price)
                trades.append({
                    'entry_time': pos.entry_time,
                    'exit_time': timestamp,
                    'side': pos.side,
                    'entry_price': pos.entry_price,
                    'exit_price': exit_price,
                    'sl_price': pos.sl_price,
                    'tp_price': pos.tp_price,
                    'reason': reason,
                    'hold_bars': idx - pos.entry_idx,
                    'return_pct': ret,
                    'vol_at_entry': pos.vol_at_entry,
                    'conf_at_entry': pos.conf_at_entry,
                    'initial_risk_pct': round(abs(pos.entry_price - pos.sl_price) / pos.entry_price, 6),
                    'realized_r': round(ret / (abs(pos.entry_price - pos.sl_price) / pos.entry_price), 4) if pos.sl_price != pos.entry_price else 0.0,
                    'year': int(row['year']),
                    'regime': str(row['regime']),
                })
                pos = None

        # 2. Determine desired side from signal
        if signal == 2:
            desired = 'long'
        elif signal == 0:
            desired = 'short'
        else:
            continue  # FLAT — no action

        # 3. Position management
        if pos is None:
            vol = float(row.get('volatility', 0.01))
            if pd.isna(vol) or vol <= 0:
                vol = 0.01
            sl = close * (1 - vol * config.sl_mult) if desired == 'long' else close * (1 + vol * config.sl_mult)
            tp = close * (1 + vol * config.tp_mult) if desired == 'long' else close * (1 - vol * config.tp_mult)
            pos = PositionState(
                side=desired, entry_price=close, entry_time=timestamp,
                sl_price=sl, tp_price=tp,
                vol_at_entry=vol, conf_at_entry=float(row['confidence']),
                entry_idx=idx,
            )
        elif pos.side != desired:
            # Hard close before reversal
            ret = compute_trade_return(pos.side, pos.entry_price, close)
            trades.append({
                'entry_time': pos.entry_time,
                'exit_time': timestamp,
                'side': pos.side,
                'entry_price': pos.entry_price,
                'exit_price': close,
                'sl_price': pos.sl_price,
                'tp_price': pos.tp_price,
                'reason': 'flip',
                'hold_bars': idx - pos.entry_idx,
                'return_pct': ret,
                'vol_at_entry': pos.vol_at_entry,
                'conf_at_entry': pos.conf_at_entry,
                'initial_risk_pct': round(abs(pos.entry_price - pos.sl_price) / pos.entry_price, 6),
                'realized_r': round(ret / (abs(pos.entry_price - pos.sl_price) / pos.entry_price), 4) if pos.sl_price != pos.entry_price else 0.0,
                'year': int(row['year']),
                'regime': str(row['regime']),
            })
            vol = float(row.get('volatility', 0.01))
            if pd.isna(vol) or vol <= 0:
                vol = 0.01
            sl = close * (1 - vol * config.sl_mult) if desired == 'long' else close * (1 + vol * config.sl_mult)
            tp = close * (1 + vol * config.tp_mult) if desired == 'long' else close * (1 - vol * config.tp_mult)
            pos = PositionState(
                side=desired, entry_price=close, entry_time=timestamp,
                sl_price=sl, tp_price=tp,
                vol_at_entry=vol, conf_at_entry=float(row['confidence']),
                entry_idx=idx,
            )
        # else: same side as current position — HOLD (no action)

    # Close any open position at end of data
    if pos is not None:
        last_row = predictions.iloc[-1]
        ret = compute_trade_return(pos.side, pos.entry_price, float(last_row['close']))
        trades.append({
            'entry_time': pos.entry_time,
            'exit_time': predictions.index[-1],
            'side': pos.side,
            'entry_price': pos.entry_price,
            'exit_price': float(last_row['close']),
            'sl_price': pos.sl_price,
            'tp_price': pos.tp_price,
            'reason': 'expiry',
            'hold_bars': len(predictions) - 1 - pos.entry_idx,
            'return_pct': ret,
            'vol_at_entry': pos.vol_at_entry,
            'conf_at_entry': pos.conf_at_entry,
            'initial_risk_pct': round(abs(pos.entry_price - pos.sl_price) / pos.entry_price, 6),
            'realized_r': round(ret / (abs(pos.entry_price - pos.sl_price) / pos.entry_price), 4) if pos.sl_price != pos.entry_price else 0.0,
            'year': int(last_row['year']),
            'regime': str(last_row['regime']),
        })

    if not trades:
        return pd.DataFrame(columns=[
            'entry_time', 'exit_time', 'side', 'entry_price', 'exit_price',
            'sl_price', 'tp_price', 'reason', 'hold_bars', 'return_pct',
            'vol_at_entry', 'conf_at_entry', 'initial_risk_pct', 'realized_r', 'year', 'regime',
        ])
    return pd.DataFrame(trades)


def _get_geom(regime: str, config: ReplayRegimeConfig) -> dict:
    """Look up geometry for a regime, falling back to default."""
    if regime in config.regime_geom:
        return config.regime_geom[regime]
    return config.default_geom


def replay_regime(predictions: pd.DataFrame, config: ReplayRegimeConfig) -> pd.DataFrame:
    """Replay with regime-dependent SL/TP geometry.

    Args:
        predictions: DataFrame with columns [open, high, low, close, signal,
                     prob_long, prob_short, prob_neutral, confidence,
                     volatility, atr, year, regime]
        config: ReplayRegimeConfig mapping regime labels to (sl_mult, tp_mult)

    Returns:
        DataFrame of trade records (same schema as replay()).
    """
    trades = []
    pos: Optional[PositionState] = None

    for idx, (timestamp, row) in enumerate(predictions.iterrows()):
        signal = int(row['signal'])
        close = float(row['close'])
        regime = str(row.get('regime', 'unknown'))

        # 1. Check existing position for SL/TP hit (using H/L)
        if pos is not None:
            hit = check_barrier_hit(row, pos)
            if hit is not None:
                reason, exit_price = hit
                ret = compute_trade_return(pos.side, pos.entry_price, exit_price)
                trades.append({
                    'entry_time': pos.entry_time,
                    'exit_time': timestamp,
                    'side': pos.side,
                    'entry_price': pos.entry_price,
                    'exit_price': exit_price,
                    'sl_price': pos.sl_price,
                    'tp_price': pos.tp_price,
                    'reason': reason,
                    'hold_bars': idx - pos.entry_idx,
                    'return_pct': ret,
                    'vol_at_entry': pos.vol_at_entry,
                    'conf_at_entry': pos.conf_at_entry,
                    'initial_risk_pct': round(abs(pos.entry_price - pos.sl_price) / pos.entry_price, 6),
                    'realized_r': round(ret / (abs(pos.entry_price - pos.sl_price) / pos.entry_price), 4) if pos.sl_price != pos.entry_price else 0.0,
                    'year': int(row['year']),
                    'regime': regime,
                })
                pos = None

        # 2. Determine desired side from signal
        if signal == 2:
            desired = 'long'
        elif signal == 0:
            desired = 'short'
        else:
            continue

        # 3. Look up geometry for current regime
        geom = _get_geom(regime, config)

        # 4. Position management
        if pos is None:
            vol = float(row.get('volatility', 0.01))
            if pd.isna(vol) or vol <= 0:
                vol = 0.01
            sl = close * (1 - vol * geom['sl_mult']) if desired == 'long' else close * (1 + vol * geom['sl_mult'])
            tp = close * (1 + vol * geom['tp_mult']) if desired == 'long' else close * (1 - vol * geom['tp_mult'])
            pos = PositionState(
                side=desired, entry_price=close, entry_time=timestamp,
                sl_price=sl, tp_price=tp,
                vol_at_entry=vol, conf_at_entry=float(row['confidence']),
                entry_idx=idx,
            )
        elif pos.side != desired:
            # Hard close before reversal
            ret = compute_trade_return(pos.side, pos.entry_price, close)
            trades.append({
                'entry_time': pos.entry_time,
                'exit_time': timestamp,
                'side': pos.side,
                'entry_price': pos.entry_price,
                'exit_price': close,
                'sl_price': pos.sl_price,
                'tp_price': pos.tp_price,
                'reason': 'flip',
                'hold_bars': idx - pos.entry_idx,
                'return_pct': ret,
                'vol_at_entry': pos.vol_at_entry,
                'conf_at_entry': pos.conf_at_entry,
                'initial_risk_pct': round(abs(pos.entry_price - pos.sl_price) / pos.entry_price, 6),
                'realized_r': round(ret / (abs(pos.entry_price - pos.sl_price) / pos.entry_price), 4) if pos.sl_price != pos.entry_price else 0.0,
                'year': int(row['year']),
                'regime': regime,
            })
            vol = float(row.get('volatility', 0.01))
            if pd.isna(vol) or vol <= 0:
                vol = 0.01
            sl = close * (1 - vol * geom['sl_mult']) if desired == 'long' else close * (1 + vol * geom['sl_mult'])
            tp = close * (1 + vol * geom['tp_mult']) if desired == 'long' else close * (1 - vol * geom['tp_mult'])
            pos = PositionState(
                side=desired, entry_price=close, entry_time=timestamp,
                sl_price=sl, tp_price=tp,
                vol_at_entry=vol, conf_at_entry=float(row['confidence']),
                entry_idx=idx,
            )

    # Close any open position at end of data
    if pos is not None:
        last_row = predictions.iloc[-1]
        ret = compute_trade_return(pos.side, pos.entry_price, float(last_row['close']))
        trades.append({
            'entry_time': pos.entry_time,
            'exit_time': predictions.index[-1],
            'side': pos.side,
            'entry_price': pos.entry_price,
            'exit_price': float(last_row['close']),
            'sl_price': pos.sl_price,
            'tp_price': pos.tp_price,
            'reason': 'expiry',
            'hold_bars': len(predictions) - 1 - pos.entry_idx,
            'return_pct': ret,
            'vol_at_entry': pos.vol_at_entry,
            'conf_at_entry': pos.conf_at_entry,
            'initial_risk_pct': round(abs(pos.entry_price - pos.sl_price) / pos.entry_price, 6),
            'realized_r': round(ret / (abs(pos.entry_price - pos.sl_price) / pos.entry_price), 4) if pos.sl_price != pos.entry_price else 0.0,
            'year': int(last_row['year']),
            'regime': str(last_row.get('regime', 'unknown')),
        })

    if not trades:
        return pd.DataFrame(columns=[
            'entry_time', 'exit_time', 'side', 'entry_price', 'exit_price',
            'sl_price', 'tp_price', 'reason', 'hold_bars', 'return_pct',
            'vol_at_entry', 'conf_at_entry', 'initial_risk_pct', 'realized_r', 'year', 'regime',
        ])
    return pd.DataFrame(trades)


def replay_meta_geometry(predictions: pd.DataFrame,
                          regime_config: ReplayRegimeConfig,
                          meta_model) -> pd.DataFrame:
    """Replay with meta-model geometry adjustments on top of regime base geometry.

    For each trade entry, runs meta-model inference.  If meta-model says SKIP, the
    trade is skipped.  If REDUCED, base sl/tp are tightened by 0.8x.  If FULL,
    base geometry is used as-is.

    Args:
        predictions: DataFrame with OHLC and signals (same as replay())
        regime_config: ReplayRegimeConfig for per-regime base geometry
        meta_model: trained MetaModel instance (from shared.meta_labeling)

    Returns:
        DataFrame of trade records (same schema as replay()).
    """
    from shared.meta_labeling import build_inference_features

    trades = []
    pos: Optional[PositionState] = None

    for idx, (timestamp, row) in enumerate(predictions.iterrows()):
        signal = int(row['signal'])
        close = float(row['close'])
        regime = str(row.get('regime', 'unknown'))

        if pos is not None:
            hit = check_barrier_hit(row, pos)
            if hit is not None:
                reason, exit_price = hit
                ret = compute_trade_return(pos.side, pos.entry_price, exit_price)
                trades.append({
                    'entry_time': pos.entry_time,
                    'exit_time': timestamp,
                    'side': pos.side,
                    'entry_price': pos.entry_price,
                    'exit_price': exit_price,
                    'sl_price': pos.sl_price,
                    'tp_price': pos.tp_price,
                    'reason': reason,
                    'hold_bars': idx - pos.entry_idx,
                    'return_pct': ret,
                    'vol_at_entry': pos.vol_at_entry,
                    'conf_at_entry': pos.conf_at_entry,
                    'initial_risk_pct': round(abs(pos.entry_price - pos.sl_price) / pos.entry_price, 6),
                    'realized_r': round(ret / (abs(pos.entry_price - pos.sl_price) / pos.entry_price), 4) if pos.sl_price != pos.entry_price else 0.0,
                    'year': int(row['year']),
                    'regime': regime,
                })
                pos = None

        if signal == 2:
            desired = 'long'
        elif signal == 0:
            desired = 'short'
        else:
            continue

        base_geom = _get_geom(regime, regime_config)
        inf_features = build_inference_features(
            primary_confidence=float(row.get('confidence', 50)) / 100.0,
            regime_state=regime,
            periods_in_state=1,
            feature_stability_penalty=0.0,
            close=predictions['close'],
        )
        meta_result = meta_model.predict(inf_features)

        if meta_result.meta_decision == 'SKIP':
            continue

        adj_sl = base_geom['sl_mult'] * meta_result.sl_adjust
        adj_tp = base_geom['tp_mult'] * meta_result.tp_adjust

        if pos is None:
            vol = float(row.get('volatility', 0.01))
            if pd.isna(vol) or vol <= 0:
                vol = 0.01
            sl = close * (1 - vol * adj_sl) if desired == 'long' else close * (1 + vol * adj_sl)
            tp = close * (1 + vol * adj_tp) if desired == 'long' else close * (1 - vol * adj_tp)
            pos = PositionState(
                side=desired, entry_price=close, entry_time=timestamp,
                sl_price=sl, tp_price=tp,
                vol_at_entry=vol, conf_at_entry=float(row['confidence']),
                entry_idx=idx,
            )
        elif pos.side != desired:
            ret = compute_trade_return(pos.side, pos.entry_price, close)
            trades.append({
                'entry_time': pos.entry_time,
                'exit_time': timestamp,
                'side': pos.side,
                'entry_price': pos.entry_price,
                'exit_price': close,
                'sl_price': pos.sl_price,
                'tp_price': pos.tp_price,
                'reason': 'flip',
                'hold_bars': idx - pos.entry_idx,
                'return_pct': ret,
                'vol_at_entry': pos.vol_at_entry,
                'conf_at_entry': pos.conf_at_entry,
                'initial_risk_pct': round(abs(pos.entry_price - pos.sl_price) / pos.entry_price, 6),
                'realized_r': round(ret / (abs(pos.entry_price - pos.sl_price) / pos.entry_price), 4) if pos.sl_price != pos.entry_price else 0.0,
                'year': int(row['year']),
                'regime': regime,
            })
            vol = float(row.get('volatility', 0.01))
            if pd.isna(vol) or vol <= 0:
                vol = 0.01
            sl = close * (1 - vol * adj_sl) if desired == 'long' else close * (1 + vol * adj_sl)
            tp = close * (1 + vol * adj_tp) if desired == 'long' else close * (1 - vol * adj_tp)
            pos = PositionState(
                side=desired, entry_price=close, entry_time=timestamp,
                sl_price=sl, tp_price=tp,
                vol_at_entry=vol, conf_at_entry=float(row['confidence']),
                entry_idx=idx,
            )

    if pos is not None:
        last_row = predictions.iloc[-1]
        ret = compute_trade_return(pos.side, pos.entry_price, float(last_row['close']))
        trades.append({
            'entry_time': pos.entry_time,
            'exit_time': predictions.index[-1],
            'side': pos.side,
            'entry_price': pos.entry_price,
            'exit_price': float(last_row['close']),
            'sl_price': pos.sl_price,
            'tp_price': pos.tp_price,
            'reason': 'expiry',
            'hold_bars': len(predictions) - 1 - pos.entry_idx,
            'return_pct': ret,
            'vol_at_entry': pos.vol_at_entry,
            'conf_at_entry': pos.conf_at_entry,
            'initial_risk_pct': round(abs(pos.entry_price - pos.sl_price) / pos.entry_price, 6),
            'realized_r': round(ret / (abs(pos.entry_price - pos.sl_price) / pos.entry_price), 4) if pos.sl_price != pos.entry_price else 0.0,
            'year': int(last_row['year']),
            'regime': str(last_row.get('regime', 'unknown')),
        })

    if not trades:
        return pd.DataFrame(columns=[
            'entry_time', 'exit_time', 'side', 'entry_price', 'exit_price',
            'sl_price', 'tp_price', 'reason', 'hold_bars', 'return_pct',
            'vol_at_entry', 'conf_at_entry', 'initial_risk_pct', 'realized_r', 'year', 'regime',
        ])
    return pd.DataFrame(trades)
