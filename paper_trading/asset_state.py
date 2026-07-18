"""AssetRuntimeState — typed container for AssetEngine's working state.

All fields match the original self._xxx names so that existing code paths
(including external setters from pipeline.py, entry_service.py, etc.) continue
to work via self.__dict__.update(vars(self.state)) in AssetEngine.__init__.
"""

from dataclasses import dataclass, field


@dataclass
class _AssetRuntimeState:
    """Runtime working state for a single AssetEngine instance.

    Fields are grouped by lifecycle phase.  All defaults mirror the original
    AssetEngine.__init__ assignments.
    """

    # ── Training lifecycle ──────────────────────────────────────────
    trained: bool = False
    window_id_counter: int = 0
    current_window_train_start: str = ""
    current_window_train_end: str = ""
    truncate_inference: bool = False

    # ── Feature / inference tracking ────────────────────────────────
    last_feature_vector: dict | None = None
    last_feature_hash: str = ""
    last_feature_schema: list | None = None
    last_label: int | None = None
    last_confidence: float = 0.0
    last_prob_long: float = 0.0
    last_prob_short: float = 0.0
    last_prob_neutral: float = 0.0
    last_meta_proba: float | None = None
    last_macro_dir: int | None = None
    last_blend_dir: int | None = None
    last_stability: float | None = None
    last_psi_drift: float | None = None
    last_gates_trace: dict | None = None
    last_sizing_chain: dict | None = None
    last_final_signal: str | None = None
    psi_drift_initialized: bool = False
    signal_chain: list = field(default_factory=list)
    last_bar_count: int | None = None
    suppress_until: float = 0.0
    alpha_feature_cols: list | None = None
    regime_feature_names: list = field(default_factory=list)
    ensemble_breakdown: dict = field(default_factory=dict)

    # ── Regime tracking ─────────────────────────────────────────────
    regime_bar_counter: int = 0
    last_regime_row: object | None = None
    last_regime_label: str | None = None
    current_regime: str = "neutral"
    last_regime_raw_probas: tuple | None = None
    last_regime_long_prob: float | None = None
    last_regime_features: dict | None = None

    # ── Entry/exit working state ────────────────────────────────────
    entry_price: float | None = None
    entry_vol: float | None = None
    entry_signal_dir: int = 0
    entry_archetype: str = "UNKNOWN"
    entry_pressure: float | None = None
    entry_validity_state: str = "YELLOW"
    bars_at_entry: int = 0
    last_adjust_bar: int = 0
    initial_sl: float | None = None
    initial_tp: float | None = None
    last_entry_slippage: float = 0.0
    last_policy_hash: str = ""
    regime_adjusted_entry: bool = False
    cooldown_score: float = 0.0
    last_cooldown_update_cycle: int = -999
    last_stop_out_side: str | None = None
    last_stop_out_cycle: int = -999
    last_stop_out_price: float | None = None
    last_signal_flip_cycle: int = -999  # sentinel; runtime computes effective value
    min_flip_interval_bars: int = 3
    churn_ratio_threshold: float = 0.50
    initial_settlement_done: bool = False
    deferred_entry: object | None = None
    pending_entries: dict = field(default_factory=dict)
    last_entry_notional: float = 0.0

    # ── Cycle-level accounting (set by orchestrator each cycle) ─────
    cycle_counter: int = 0
    cycle_total_equity: float = 0.0
    cycle_drawdown_pct: float = 0.0
    leverage_budget_ref: list | None = None
    leverage_lock: object | None = None

    # ── SL/TP & scaling ─────────────────────────────────────────────
    kelly_multiplier: float = 1.0
    scale_out_plan: object | None = None
    last_adjust_bar_sltp: int = 0

    # ── Shadow SL/TP ────────────────────────────────────────────────
    shadow_sltp: object | None = None
    risk_signal: object | None = None
    shadow_action: object | None = None
    shadow_drift_intel: object | None = None
    shadow_learning: object | None = None

    # ── Attribution ─────────────────────────────────────────────────
    attribution_export_dir: str | None = None
    experiment_id: str = ""
    current_trade_id: str | None = None
    attribution_buffer: list = field(default_factory=list)

    # ── MT5 orphan cleanup (moved to PositionService in future) ─────
    mt5_cleanup_queue: list = field(default_factory=list)
    mt5_cleanup_retries: int = 0

    # ── Spread gate ─────────────────────────────────────────────────
    last_spread_bps: float | None = None
    last_spread_time: float = 0.0
    spread_tier: str = "fx_cross"

    # ── Research/experiment ─────────────────────────────────────────
    research_mode: bool = False

    # ── TP reconciliation flag ──────────────────────────────────────
    tp_reconciled: bool = False

    # ── Running MAE/MFE ────────────────────────────────────────────
    running_mae: float = 0.0
    running_mfe: float = 0.0
