"""Engine-level Prometheus metrics — called every state save cycle."""

from pathlib import Path
from paper_trading.metrics.exposition import global_registry

_registry = global_registry()

_cycle_total = _registry.counter("engine_cycles_total", "Total engine cycles executed")
_positions_gauge = _registry.gauge("engine_positions", "Open positions by asset and direction")
_pnl_gauge = _registry.gauge("engine_pnl_usd", "Current unrealized PnL in USD by asset")
_mtm_total_gauge = _registry.gauge("engine_mtm_total_usd", "Total portfolio MTM value")
_drawdown_gauge = _registry.gauge("engine_drawdown_pct", "Current drawdown as percentage of peak")
_gate_blocked = _registry.counter("engine_gate_blocked_total", "Decisions blocked by gate name and asset")
_calibration_prob = _registry.gauge("engine_calibration_prob", "Calibrated probability by asset")
_governance_mult = _registry.gauge("engine_governance_multiplier", "Governance multiplier by asset")
_inference_cycles = _registry.counter("engine_inference_cycles_total", "Inference cycles run by asset")
_slippage_gauge = _registry.gauge("engine_slippage_pct", "Current slippage estimate in percent")


def update_engine_metrics(engine):
    _cycle_total.inc()

    total_pnl = 0.0
    positions_count = {"long": 0, "short": 0}
    mtm_total = 0.0

    for name, asset in engine.assets.items():
        mtm = getattr(asset, "mtm_value", 0.0) or 0.0
        mtm_total += mtm

        pnl = getattr(asset, "unrealized_pnl", None)
        if pnl is not None:
            total_pnl += pnl
            _pnl_gauge.set(pnl, asset=name)

        if hasattr(asset, "position") and asset.position:
            side = asset.position.get("side", "unknown")
            if side in ("long", "short"):
                positions_count[side] += 1
                _positions_gauge.set(1.0, asset=name, direction=side)
        else:
            _positions_gauge.set(0.0, asset=name, direction="flat")

        cal_prob = getattr(asset, "_calibrated_prob", None)
        if cal_prob is not None:
            _calibration_prob.set(cal_prob, asset=name)

        gov_mult = getattr(asset, "_last_governance_mult", None)
        if gov_mult is not None:
            _governance_mult.set(gov_mult, asset=name)

    _positions_gauge.set(positions_count["long"], asset="__portfolio__", direction="long")
    _positions_gauge.set(positions_count["short"], asset="__portfolio__", direction="short")
    _mtm_total_gauge.set(mtm_total)

    # Peak portfolio value moved to HaltState during MAINT-01 refactoring.
    orchestrator = getattr(engine, "_orchestrator", None)
    if orchestrator is not None and hasattr(orchestrator, "_halt_state"):
        peak = orchestrator._halt_state.peak_portfolio_value or mtm_total
    else:
        peak = mtm_total
    if peak > 0:
        drawdown_pct = (mtm_total - peak) / peak * 100
        _drawdown_gauge.set(drawdown_pct)

    # Track blocked gates from per-asset gate counters
    for name, asset in engine.assets.items():
        gate_counts = getattr(asset, "_gate_blocked_counts", {})
        for gate_name, count in gate_counts.items():
            _gate_blocked.inc(count, gate=gate_name, asset=name)

    # Slippage from live Sharpe tracker if available
    try:
        import os

        from paper_trading.performance.live_sharpe import LiveSharpeTracker

        base = str(Path(__file__).resolve().parent.parent.parent)
        tracker = LiveSharpeTracker(base_dir=base)
        data = tracker.compute()
        if data.get("available"):
            _slippage_gauge.set(data.get("model_timing_gap_pct", 0.0))
    except (OSError, ValueError, TypeError, ImportError, AttributeError):
        pass
