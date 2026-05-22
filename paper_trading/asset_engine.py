import logging
import os
import pickle
from datetime import datetime

import numpy as np
import pandas as pd
import pytz
import xgboost as xgb

from features.builder import build_features, compute_macro_derived, model_path
from monitoring.importance_tracker import ImportanceStore, StabilityResult
from monitoring.validity_state_machine import (
    ValidityStateMachine as _ValidityStateMachine,
)
from paper_trading import diagnostics as diag
from paper_trading import wrappers as _w
from paper_trading.config_manager import get_config
from paper_trading.data_fetcher import fetch_history, fetch_live, fetch_ref, flatten, safe_download
from paper_trading.decision import PositionIntent, TradeDecision
from paper_trading.drift_scoring import get_shadow_intelligence as _get_drift
from paper_trading.position_manager import PositionManager
from paper_trading.risk_governance import evaluate as _risk_evaluate
from paper_trading.shadow_actions import compute_shadow_actions as _compute_shadow
from paper_trading.shadow_feedback import record_shadow_feedback as _record_feedback
from paper_trading.shadow_learning import compile_shadow_learning as _compile_learning
from paper_trading.shadow_memory import store_event as _shadow_store
from paper_trading.state_store import _SKIP_JOURNAL, StateStore
from paper_trading.tracer import (
    shadow_compare_pnl,
    shadow_compare_signal,
    shadow_compare_sizing,
    trace_decision,
    trace_diagnostic_report,
)
from shared.meta_labeling import (
    MetaModel,
    build_inference_features,
    build_meta_training_data,
)
from shared.registry import StrategyRegistry

logger = logging.getLogger("quantforge.asset_engine")

ET = pytz.timezone("US/Eastern")

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_STORE = StateStore(BASE)


class AssetEngine:
    def __init__(
        self,
        ticker,
        name,
        contract,
        allocation,
        halt_config=None,
        config=None,
        expected_prob_conf=0.45,
        state_store=None,
        journal_path=None,
        sl_mult=1.0,
        tp_mult=2.5,
        regime_geometry=None,
        initial_capital=None,
        position_size=None,
        retrain_window=None,
    ):
        self.ticker = ticker
        self.name = name
        self.contract = contract
        self.features = list(contract.features)
        self.allocation = allocation
        engine_cfg = get_config()
        self.initial_capital = initial_capital if initial_capital is not None else engine_cfg.capital * allocation
        self.halt_config = halt_config or dict(engine_cfg.halt)
        self.config = config or {}
        self.expected_prob_conf = expected_prob_conf
        self.model = None
        self.signal_data = None
        self.peak_value = self.initial_capital
        self.current_value = self.initial_capital
        self.start_time = datetime.now(tz=ET)
        self.last_signal_date = None
        self.trades = []
        self.prob_history = []
        self.model_path = model_path(ticker)
        self._trained = False
        self.position = None
        self.trade_log = []
        self.current_price = None
        self.pos_mgr = PositionManager(
            self.initial_capital,
            position_size if position_size is not None else engine_cfg.position_size,
        )
        self.validity_sm = _ValidityStateMachine()
        self._reg = StrategyRegistry.get_instance()
        self._model_iface = self._reg.get_model(self.name)
        self._signal_strategy = self._reg.get_signal(self.name)
        self._sizing_strategy = self._reg.get_sizing(self.name)
        self._pnl_strategy = self._reg.get_pnl(self.name)
        self._feature_pipeline = self._reg.get_features(self.name)
        self._risk_signal = None
        self._shadow_action = None
        self._shadow_drift_intel = None
        self._shadow_learning = None
        self.sl_mult = sl_mult
        self.tp_mult = tp_mult
        self.regime_geometry = regime_geometry or {}
        self._research_mode = engine_cfg.research_mode
        self._retrain_window = retrain_window if retrain_window is not None else engine_cfg.retrain_window
        if state_store is not None:
            self.state_store = state_store
        elif journal_path is _SKIP_JOURNAL:
            self.state_store = None
        else:
            self.state_store = _STORE
        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        self._importance_store = ImportanceStore(base_dir)
        self._window_id_counter = 0
        self._current_window_train_start = ""
        self._current_window_train_end = ""
        self._last_stability: StabilityResult | None = None
        self._meta_model = MetaModel()
        self._meta_inference: dict | None = None

    def _build_features(self, df, ref, macro):
        return build_features(df, macro, ref, self.contract)

    def _tb_vol(self, df):
        returns = np.log(df["close"] / df["close"].shift(1))
        vol = returns.ewm(span=100).std()
        return vol.iloc[-1] if not pd.isna(vol.iloc[-1]) else 0.01

    def _open_position(self, side, entry_price, entry_date, df=None):
        data = df if df is not None else self.price_data
        vol = self._tb_vol(data)
        if pd.isna(vol) or pd.isna(entry_price) or entry_price == 0:
            logger.error("%s: invalid entry_price=%s or vol=%s", self.name, entry_price, vol)
            return

        # Regime-conditional geometry selection
        state = self.validity_sm.current_state.value if self.validity_sm else "YELLOW"
        geom = self.regime_geometry.get(state, {"sl_mult": self.sl_mult, "tp_mult": self.tp_mult})
        sl_mult = geom.get("sl_mult", self.sl_mult)
        tp_mult = geom.get("tp_mult", self.tp_mult)

        if self.regime_geometry:
            logger.info(
                "%s: using regime-conditional geometry for %s: sl=%.2f, tp=%.2f",
                self.name,
                state,
                sl_mult,
                tp_mult,
            )

        intent = PositionIntent.from_price_and_vol(side, entry_price, entry_date, vol, sl_mult, tp_mult)
        self.pos_mgr.open(intent)
        self.position = {
            "side": intent.side,
            "entry": intent.entry_price,
            "sl": intent.stop_loss,
            "tp": intent.take_profit,
            "entry_date": intent.entry_date,
            "vol": intent.vol,
            "sl_mult": sl_mult,
            "tp_mult": tp_mult,
        }

    def _close_position(self, exit_price, exit_date, reason):
        trade = self.pos_mgr.close(exit_price, exit_date, reason)
        if trade is None:
            return
        trade["asset"] = self.name
        self.position = None
        self.current_value = self.pos_mgr.current_value
        self.trade_log = list(self.pos_mgr.trade_log)
        self._save_trade_journal(trade)

    def refresh_price(self):
        try:
            df = safe_download(self.ticker, period="5d", auto_adjust=True, progress=False)
            if not df.empty:
                df = flatten(df)
                close = float(df["close"].ffill().iloc[-1])
                self.current_price = None if pd.isna(close) else close
        except Exception:
            pass

    def train(self, force=False):
        if os.path.exists(self.model_path) and not force:
            with open(self.model_path, "rb") as f:
                self.model = pickle.load(f)
                self._trained = True
            return

        logger.info("%s: downloading history...", self.name)
        df = fetch_history(self.ticker)
        ref = fetch_ref("SPY")
        macro = compute_macro_derived(pd.read_parquet(os.path.join(BASE, "data/processed/macro_factors.parquet")))
        features = self._build_features(df, ref, macro)
        logger.info("%s: %d feature rows", self.name, len(features))

        end_date = features.index[-1]
        start_date = end_date - pd.DateOffset(years=self._retrain_window)
        train = features[features.index >= start_date]
        if len(train) < 200:
            train = features

        X = train[self.features]
        y = train["label"].astype(int)
        split = int(len(X) * 0.8)

        model = xgb.XGBClassifier(
            n_estimators=300,
            max_depth=2,
            learning_rate=0.02,
            objective="multi:softprob",
            num_class=3,
            random_state=42,
            n_jobs=1,
            tree_method="hist",
            verbosity=0,
        )
        model.fit(
            X.iloc[:split],
            y.iloc[:split],
            eval_set=[(X.iloc[split:], y.iloc[split:])],
            verbose=False,
        )
        self.model = model
        self._trained = True
        with open(self.model_path, "wb") as f:
            pickle.dump(model, f)

        # Log feature importances
        self._window_id_counter += 1
        self._current_window_train_start = start_date.strftime("%Y-%m-%d")
        self._current_window_train_end = end_date.strftime("%Y-%m-%d")
        window_id = f"w{self._window_id_counter}_{self._current_window_train_end}"
        try:
            self._importance_store.log_snapshot(
                asset=self.name,
                feature_names=self.features,
                importances=model.feature_importances_,
                window_id=window_id,
                train_start=self._current_window_train_start,
                train_end=self._current_window_train_end,
                model_type="xgboost",
            )
            stability = self._importance_store.compute_stability(self.name)
            if stability is not None:
                self._last_stability = stability
                logger.info(
                    "%s stability — jaccard=%.3f spearman=%.3f penalty=%.3f",
                    self.name,
                    stability.jaccard_top_10,
                    stability.spearman_rank_corr,
                    stability.penalty,
                )
        except Exception as e:
            logger.warning("%s: failed to log feature importances: %s", self.name, e)

    def generate_signal(self, threshold=0.45):
        return self._generate_and_apply(threshold)

    def _generate_and_apply(self, threshold=0.45):
        self._ensure_position_synced()
        if not self._trained:
            self.train()

        df = fetch_live(self.ticker)

        # Sync with latest price (same as dashboard) to ensure responsive SL/TP
        self.refresh_price()
        if self.current_price is not None:
            # Update the last row's close with the real-time price
            df.loc[df.index[-1], "close"] = self.current_price

        self.price_data = df
        df["close"] = df["close"].ffill()
        ref = fetch_ref("SPY")
        macro = self._feature_pipeline.macro_derived(
            pd.read_parquet(os.path.join(BASE, "data/processed/macro_factors.parquet"))
        )
        features_df = self._feature_pipeline.build(df, macro, ref, self.contract)

        X = features_df[self.features]
        if len(X) == 0:
            raise ValueError(f"No valid feature rows after building features for {self.name}")

        proba = self._model_iface.predict(self.model, X)
        if proba.shape[1] < 3:
            raise ValueError(f"Model returned {proba.shape[1]} classes, expected 3")

        pos_size = self._sizing_strategy.compute(df["close"], self.config)

        # Meta-model: train on accumulated trades if enough data
        self._maybe_train_meta_model(df)

        # Meta-model inference
        if self._meta_model.is_trained:
            validity_state = self.validity_sm.current_state.value if self.validity_sm else "YELLOW"
            periods_in_state = self.validity_sm.periods_in_current_state if self.validity_sm else 0
            stability_penalty = self._last_stability.penalty if self._last_stability else 0.0
            primary_conf = float(max(proba[-1]))
            inf_features = build_inference_features(
                primary_confidence=primary_conf,
                regime_state=validity_state,
                periods_in_state=periods_in_state,
                feature_stability_penalty=stability_penalty,
                close=df["close"],
            )
            meta_result = self._meta_model.predict(inf_features)
            pos_size *= meta_result.scale_factor
            self._meta_inference = {
                "meta_confidence": meta_result.meta_confidence,
                "meta_decision": meta_result.meta_decision,
            }
        else:
            self._meta_inference = None

        result = self._signal_strategy.compute(proba, X.index, threshold, df["close"], pos_size)
        self.signal_data = result.signal_data

        latest = self.signal_data.iloc[-1]
        self.last_signal_date = latest.name

        decision = TradeDecision(
            asset=self.name,
            signal=result.signal_type,
            label=result.label,
            confidence=result.confidence_pct,
            prob_long=round(float(latest["prob_long"]), 4),
            prob_short=round(float(latest["prob_short"]), 4),
            prob_neutral=round(float(latest["prob_neutral"]), 4),
            close_price=round(float(latest["close"]), 4),
            timestamp=str(latest.name.date()),
            position_size=float(pos_size),
        )

        self._apply_decision(decision, df)

        trace_decision(
            asset=self.name,
            features={k: round(float(v), 6) for k, v in X.iloc[-1].items()},
            proba=[float(proba[-1, 0]), float(proba[-1, 1]), float(proba[-1, 2])],
            threshold=threshold,
            signal=decision.signal,
            confidence=decision.confidence,
            pos_size=float(pos_size),
            close_price=float(latest["close"]),
            current_side=self.pos_mgr.current_side(),
            halt_flags=self.check_halt_conditions(),
        )

        _shadow_signal_df = _w.compute_signals(proba, X.index, threshold)
        _shadow_latest = _shadow_signal_df.iloc[-1]
        _shadow_stype, _shadow_conf, _shadow_conf_pct = _w.signal_type_and_confidence(
            int(_shadow_latest["signal"]),
            float(_shadow_latest["prob_long"]),
            float(_shadow_latest["prob_short"]),
        )
        shadow_compare_signal(
            asset=self.name,
            proba_produced=[float(proba[-1, 0]), float(proba[-1, 1]), float(proba[-1, 2])],
            wrapper_signal=_shadow_stype,
            wrapper_confidence=_shadow_conf_pct,
            original_signal=decision.signal,
            original_confidence=decision.confidence,
        )

        _shadow_size = _w.compute_vol_scalar(df["close"]) if self.config.get("vol_scalar") else 1.0
        shadow_compare_sizing(
            asset=self.name,
            wrapper_size=_shadow_size,
            original_size=float(pos_size),
        )

        try:
            _proba_list = [float(proba[-1, 0]), float(proba[-1, 1]), float(proba[-1, 2])]
            _sig_div = diag.analyze_signal_divergence(
                _proba_list,
                threshold,
                decision.signal,
                decision.confidence,
                _shadow_stype,
                _shadow_conf_pct,
            )
            _mod_div = diag.analyze_model_distribution(self.name, _proba_list)
            _feat_drivers = diag.analyze_feature_impact(
                self.model,
                X.iloc[[-1]],
                self.features,
                proba[-1:],
            )
            _regime = diag.analyze_regime_context(df["close"])
            _report = diag.build_shadow_report(
                asset=self.name,
                timestamp=str(latest.name.date()),
                signal_match=_sig_div["match"],
                signal_divergence=_sig_div,
                model_divergence=_mod_div,
                feature_drivers=_feat_drivers,
                regime_context=_regime,
            )
            trace_diagnostic_report(_report)
            _shadow_store(self.name, _report)
            self._risk_signal = _risk_evaluate(self.name)
            self._shadow_drift_intel = _get_drift(self.name)
            self._shadow_action = _compute_shadow(
                asset=self.name,
                state=None,
                drift_report=self._shadow_drift_intel,
                risk_signal=self._risk_signal,
            )
            _record_feedback(
                asset=self.name,
                signal_data={"signal": decision.signal, "confidence": decision.confidence},
                drift=self._shadow_drift_intel,
                risk=self._risk_signal,
                action=self._shadow_action,
            )
            self._shadow_learning = _compile_learning(
                asset=self.name,
                feedback_logs=None,
                drift_history=self._shadow_drift_intel,
                risk_history=self._risk_signal,
            )
        except Exception:
            pass

        self._reg.validate_strategies(
            self.name,
            {
                "_model": self._model_iface,
                "_signal": self._signal_strategy,
                "_sizing": self._sizing_strategy,
                "_pnl": self._pnl_strategy,
                "_feature_pipeline": self._feature_pipeline,
            },
        )

        return self._decision_to_dict(decision)

    def _apply_decision(self, decision: TradeDecision, df):
        today = decision.timestamp
        current_side = self.pos_mgr.current_side()
        new_side = "long" if decision.signal == "BUY" else ("short" if decision.signal == "SELL" else None)

        if new_side != current_side:
            if self.pos_mgr.has_position():
                self._close_position(decision.close_price, today, "signal_flip")
            if new_side:
                self._open_position(new_side, decision.close_price, today, df)

        self.prob_history.append(
            {
                "date": today,
                "prob_long": round(decision.prob_long * 100, 2),
                "prob_short": round(decision.prob_short * 100, 2),
                "signal": decision.signal,
                "confidence": decision.confidence,
                "close_price": decision.close_price,
            }
        )
        self._log_confidence_buckets()

    def _decision_to_dict(self, decision: TradeDecision):
        pos = self.pos_mgr.position
        return {
            "asset": self.name,
            "signal": decision.signal,
            "confidence": decision.confidence,
            "close_price": decision.close_price,
            "date": decision.timestamp,
            "label": decision.label,
            "position": (
                {
                    "side": pos.side if pos else None,
                    "entry": round(pos.entry_price, 4) if pos else None,
                    "sl": round(pos.stop_loss, 4) if pos else None,
                    "tp": round(pos.take_profit, 4) if pos else None,
                    "current_pnl": (round(self._position_pnl(decision.close_price), 4) if pos else None),
                }
                if pos
                else None
            ),
        }

    def _position_pnl(self, current_price):
        return self.pos_mgr.position_pnl(current_price)

    def _ensure_position_synced(self):
        if self.position is not None and not self.pos_mgr.has_position():
            intent = PositionIntent(
                side=self.position["side"],
                entry_price=self.position["entry"],
                entry_date=self.position.get("entry_date", ""),
                stop_loss=self.position["sl"],
                take_profit=self.position["tp"],
                vol=self.position.get("vol", 0.01),
            )
            self.pos_mgr.open(intent)

    def update_pnl(self):
        self._ensure_position_synced()

        # 1. Intraday SL/TP Check - ALWAYS run this on every refresh using real-time price
        if self.pos_mgr.has_position() and self.current_price is not None:
            hit = self.pos_mgr.check_sl_tp(self.current_price)
            if hit:
                last_bar = str(datetime.now(tz=ET).date())
                if self.signal_data is not None and len(self.signal_data) > 0:
                    last_bar = str(self.signal_data.index[-1].date())

                logger.info("%s: SL/TP HIT: %s at %s (Current: %s)", self.name, hit[0].upper(), hit[1], self.current_price)
                self._close_position(hit[1], last_bar, hit[0])
                if self.current_value > self.peak_value:
                    self.peak_value = self.current_value
                return

        # 2. Daily P&L Settlement - Only run if signal_data is available (historical context)
        if self.signal_data is None or len(self.signal_data) < 2:
            return

        close = self.signal_data["close"]
        today_close = float(close.iloc[-1])
        last_bar = str(self.signal_data.index[-1].date())

        if self.trades and self.trades[-1]["date"] == last_bar:
            return
        # (Existing daily pnl logic continues...)
        sig = self.signal_data["signal"].iloc[-2]
        direction = 1 if sig == 2 else (-1 if sig == 0 else 0)
        pos_size = (
            float(self.signal_data["position_size"].iloc[-2]) if "position_size" in self.signal_data.columns else 1.0
        )
        prev_close = float(close.iloc[-2])
        ret = (
            (today_close / prev_close - 1)
            if len(close) >= 2 and prev_close != 0 and not pd.isna(today_close) and not pd.isna(prev_close)
            else 0
        )
        if pd.isna(ret) or np.isinf(ret):
            ret = 0
        pnl = self.pos_mgr.compute_daily_pnl(direction, ret, pos_size)
        _shadow_pnl = _w.compute_daily_pnl(
            self.pos_mgr.current_value,
            direction,
            ret,
            self.pos_mgr.position_size,
            pos_size,
        )
        shadow_compare_pnl(asset=self.name, wrapper_pnl=_shadow_pnl, original_pnl=pnl)
        try:
            _pnl_decomp = diag.analyze_pnl_decomposition(
                self.pos_mgr.current_value,
                direction,
                ret,
                self.pos_mgr.position_size,
                pos_size,
                pnl,
            )
            _regime = diag.analyze_regime_context(close)
            _report = diag.build_shadow_report(
                asset=self.name,
                timestamp=last_bar,
                signal_match=True,
                pnl_match=_pnl_decomp["match"],
                regime_context=_regime,
                pnl_decomposition=_pnl_decomp,
            )
            trace_diagnostic_report(_report)
            _shadow_store(self.name, _report)
        except Exception:
            pass
        self.pos_mgr.apply_pnl(pnl)
        self.current_value = self.pos_mgr.current_value
        self.peak_value = self.pos_mgr.peak_value
        if direction != 0:
            self.trades.append(
                {
                    "date": last_bar,
                    "direction": direction,
                    "return": float(ret),
                    "pnl": float(pnl),
                }
            )

    def get_metrics(self):
        self._ensure_position_synced()
        cv = self.current_value if not pd.isna(self.current_value) else self.initial_capital
        pv = self.peak_value if not pd.isna(self.peak_value) else cv
        dd = (cv - pv) / pv if pv > 0 else 0
        total_return = (cv - self.initial_capital) / self.initial_capital if self.initial_capital > 0 else 0

        monthly_pfs = []
        if self.trade_log:
            td = pd.DataFrame(self.trade_log)
            td["month"] = pd.to_datetime(td["exit_date"]).dt.to_period("M")
            for m, g in td.groupby("month"):
                profits = g[g["pnl"] > 0]["pnl"].sum()
                losses = abs(g[g["pnl"] < 0]["pnl"].sum())
                monthly_pfs.append({"month": str(m), "pf": profits / losses if losses > 0 else float("inf")})
        monthly_pf = monthly_pfs[-1]["pf"] if monthly_pfs else None

        total_profits = sum(t["pnl"] for t in self.trade_log if t["pnl"] > 0)
        total_losses = abs(sum(t["pnl"] for t in self.trade_log if t["pnl"] < 0))
        pf = total_profits / total_losses if total_losses > 0 else (float("inf") if total_profits > 0 else 0)

        win_rate = len([t for t in self.trade_log if t["pnl"] > 0]) / len(self.trade_log) if self.trade_log else 0
        sc = {"BUY": 0, "SELL": 0, "FLAT": 0}
        for p in self.prob_history:
            sc[p["signal"]] = sc.get(p["signal"], 0) + 1
        mean_conf = np.mean([p["confidence"] for p in self.prob_history]) if self.prob_history else 0
        mean_conf = 0 if pd.isna(mean_conf) else mean_conf

        pos_info = None
        if self.pos_mgr.has_position():
            upnl = (
                self._position_pnl(self.current_price)
                if self.current_price is not None and not pd.isna(self.current_price)
                else 0.0
            )
            pos_info = {
                "side": self.pos_mgr.position.side,
                "entry": round(self.pos_mgr.position.entry_price, 4),
                "sl": round(self.pos_mgr.position.stop_loss, 4),
                "tp": round(self.pos_mgr.position.take_profit, 4),
                "current_vol": round(self.pos_mgr.position.vol, 6),
                "unrealized_pnl": round(upnl, 2),
                "sl_mult": self.position.get("sl_mult") if self.position else None,
                "tp_mult": self.position.get("tp_mult") if self.position else None,
            }

        pnl_pct = (
            self._position_pnl(self.current_price) / 100
            if self.pos_mgr.has_position() and self.current_price is not None and not pd.isna(self.current_price)
            else 0
        )
        pos_size_config = get_config().position_size
        mtm_value = cv + cv * pnl_pct * pos_size_config
        mtm_return = (mtm_value - self.initial_capital) / self.initial_capital * 100 if self.initial_capital > 0 else 0

        mean_pl = np.mean([p["prob_long"] for p in self.prob_history]) if self.prob_history else 0
        mean_pl = 0 if pd.isna(mean_pl) else mean_pl
        mean_ps = np.mean([p["prob_short"] for p in self.prob_history]) if self.prob_history else 0
        mean_ps = 0 if pd.isna(mean_ps) else mean_ps

        # Current regime-based multipliers (even if no position)
        state = self.validity_sm.current_state.value if self.validity_sm else "YELLOW"
        geom = self.regime_geometry.get(state, {"sl_mult": self.sl_mult, "tp_mult": self.tp_mult})

        return {
            "asset": self.name,
            "current_value": round(self.current_value, 2),
            "mtm_value": round(mtm_value, 2),
            "total_return": round(total_return * 100, 2),
            "mtm_return": round(mtm_return, 2),
            "drawdown": round(dd * 100, 2),
            "profit_factor": round(pf, 2),
            "win_rate": round(win_rate * 100, 2),
            "n_trades": len(self.trade_log),
            "n_signals": len(self.prob_history),
            "signal_distribution": sc,
            "mean_confidence": round(float(mean_conf), 2),
            "mean_prob_long": round(float(mean_pl), 2),
            "mean_prob_short": round(float(mean_ps), 2),
            "current_price": round(self.current_price, 4) if self.current_price else None,
            "last_signal_date": str(self.last_signal_date.date()) if self.last_signal_date else None,
            "monthly_pf": round(float(monthly_pf), 2) if monthly_pf else None,
            "position": pos_info,
            "current_sl_mult": geom.get("sl_mult", self.sl_mult),
            "current_tp_mult": geom.get("tp_mult", self.tp_mult),
            "trade_log": self.trade_log[-10:],
            "feature_stability": {
                "jaccard_top_10": self._last_stability.jaccard_top_10 if self._last_stability else None,
                "spearman_rank_corr": self._last_stability.spearman_rank_corr if self._last_stability else None,
                "penalty": self._last_stability.penalty if self._last_stability else 0.0,
                "window_id": self._last_stability.window_id if self._last_stability else None,
            },
            "meta_model": self._meta_model.get_state(),
            "meta_inference": self._meta_inference,
        }

    def _maybe_train_meta_model(self, df: pd.DataFrame) -> None:
        if len(self.trade_log) < 50:
            return
        if self._meta_model.is_trained:
            return
        try:
            stability_penalty = self._last_stability.penalty if self._last_stability else 0.0
            validity_history = [t for t in getattr(self.validity_sm, "state_history", [])]
            X, y = build_meta_training_data(
                trade_log=self.trade_log,
                prob_history=self.prob_history,
                validity_history=validity_history,
                feature_stability_penalty=stability_penalty,
                close=df["close"],
            )
            if X is not None and y is not None:
                self._meta_model.train(X, y)
        except Exception as e:
            logger.warning("%s: meta-model training failed: %s", self.name, e)

    def _save_trade_journal(self, trade):
        if self.state_store is not None:
            self.state_store.append_trade(trade)

    def _log_confidence_buckets(self):
        bucket = {"asset": self.name, "date": str(datetime.now(tz=ET).date())}
        for p in self.prob_history[-20:]:
            conf = p["confidence"]
            bucket.setdefault(f"count_{int(conf / 10) * 10}_{int(conf / 10 + 1) * 10}", 0)
            bucket[f"count_{int(conf / 10) * 10}_{int(conf / 10 + 1) * 10}"] += 1
        bucket["mean_conf"] = np.mean([p["confidence"] for p in self.prob_history[-20:]]) if self.prob_history else 0
        bucket["n_signals"] = min(20, len(self.prob_history))
        if self.state_store is not None:
            self.state_store.append_confidence_bucket(bucket)

    def update_validity(self):
        halt = self.check_halt_conditions()
        score = 0.80
        if not halt["drawdown_ok"]:
            score -= 0.25
        if not halt["monthly_pf_ok"]:
            score -= 0.20
        if not halt["drought_ok"]:
            score -= 0.15
        if not halt["drift_ok"]:
            score -= 0.15

        if self._last_stability is not None:
            penalty = self._last_stability.penalty
            if penalty < 0:
                logger.info(
                    "%s stability penalty: %.3f (jaccard=%.3f, spearman=%.3f)",
                    self.name,
                    penalty,
                    self._last_stability.jaccard_top_10,
                    self._last_stability.spearman_rank_corr,
                )
                score += penalty

        score = max(0.0, min(1.0, score))
        result = self.validity_sm.transition(score, pd.Timestamp.now())
        result["feature_stability"] = {
            "jaccard_top_10": self._last_stability.jaccard_top_10 if self._last_stability else None,
            "spearman_rank_corr": self._last_stability.spearman_rank_corr if self._last_stability else None,
            "penalty_applied": self._last_stability.penalty if self._last_stability else 0.0,
        }
        return result

    def check_halt_conditions(self):
        metrics = self.get_metrics()
        dd = metrics.get("drawdown", 0) / 100
        if pd.isna(dd):
            dd = 0
        hc = self.halt_config
        reasons = []
        if dd <= hc["drawdown"]:
            reasons.append(f"DD {metrics['drawdown']:.1f}% <= {hc['drawdown'] * 100:.0f}%")
        mpf = metrics.get("monthly_pf")
        if mpf is not None and not pd.isna(mpf) and mpf < hc["monthly_pf"]:
            reasons.append(f"PF {mpf:.2f} < {hc['monthly_pf']:.2f}")
        drought_ok = True
        drought_days = hc.get("signal_drought", 30)
        if self.last_signal_date is not None:
            days_since = (datetime.now(tz=ET).date() - pd.Timestamp(self.last_signal_date).date()).days
            if days_since > drought_days:
                reasons.append(f"Signal drought: {days_since}d > {drought_days}d")
                drought_ok = False
        drift_ok = True
        prob_drift_limit = hc.get("prob_drift", 0.15)
        metrics = self.get_metrics()
        mean_conf = metrics.get("mean_confidence", 0) / 100
        if pd.isna(mean_conf):
            mean_conf = 0
        drift = abs(mean_conf - self.expected_prob_conf)
        if drift > prob_drift_limit:
            reasons.append(f"Confidence drift: {drift:.3f} > {prob_drift_limit:.2f}")
            drift_ok = False
        return {
            "halted": len(reasons) > 0,
            "reasons": reasons,
            "drawdown_ok": dd > hc["drawdown"],
            "monthly_pf_ok": mpf is None or pd.isna(mpf) or mpf >= hc["monthly_pf"],
            "drought_ok": drought_ok,
            "drift_ok": drift_ok,
        }
