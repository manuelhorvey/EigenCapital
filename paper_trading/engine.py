import logging
import pandas as pd
import numpy as np
import xgboost as xgb
import yfinance as yf
import pickle, os, json, math, yaml, fcntl
import copy, time
import pytz
from datetime import datetime
from features.builder import compute_macro_derived, build_features, model_path
from features.registry import FEATURE_REGISTRY
from paper_trading.state_store import StateStore, EngineSnapshot, _SKIP_JOURNAL, sanitize
from paper_trading.decision import TradeDecision, PositionIntent
from paper_trading.position_manager import PositionManager
from monitoring.validity_state_machine import ValidityStateMachine as _ValidityStateMachine, ValidityState as _ValidityState
from enum import Enum
from paper_trading.tracer import trace_decision, shadow_compare_signal, shadow_compare_sizing, shadow_compare_pnl, trace_diagnostic_report
from paper_trading import diagnostics as diag
from paper_trading.shadow_memory import store_event as _shadow_store
from paper_trading.risk_governance import evaluate as _risk_evaluate
from paper_trading.shadow_actions import compute_shadow_actions as _compute_shadow
from paper_trading.drift_scoring import get_shadow_intelligence as _get_drift
from paper_trading.shadow_feedback import record_shadow_feedback as _record_feedback
from paper_trading.shadow_learning import compile_shadow_learning as _compile_learning
from paper_trading import wrappers as _w
from shared.registry import StrategyRegistry


class ExecutionState(Enum):
    ACTIVE = "ACTIVE"
    PAUSED = "PAUSED"
    HALTED = "HALTED"

ET = pytz.timezone('US/Eastern')

logger = logging.getLogger("quantforge.engine")

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_STORE = StateStore(BASE)
STATE_PATH = _STORE.state_path
TRADE_JOURNAL_PATH = _STORE.trade_journal_path
CONFIDENCE_BUCKET_PATH = _STORE.confidence_bucket_path
EQUITY_HISTORY_PATH = _STORE.equity_history_path
CACHE_DIR = _STORE.cache_dir
LOG_PATH = os.path.join(BASE, 'data', 'live', 'engine.log')
MODEL_DIR = os.path.join(os.path.dirname(__file__), 'models')
CONFIG_PATH = os.path.join(BASE, 'configs', 'paper_trading.yaml')

os.makedirs(MODEL_DIR, exist_ok=True)


def _load_config():
    path = CONFIG_PATH
    if os.path.exists(path):
        with open(path) as f:
            cfg = yaml.safe_load(f)
        logger.info("Loaded config from %s", path)
        return cfg
    logger.warning("Config file %s not found; using defaults", path)
    return {}


_cfg = _load_config()

CONFIG = {
    'capital': _cfg.get('capital', 100_000),
    'position_size': _cfg.get('position_size', 0.95),
    'rebalance': _cfg.get('rebalance', 'daily'),
    'retrain_freq': _cfg.get('retrain_freq', 'annual'),
    'retrain_window': _cfg.get('retrain_window', 5),
}

HALT = dict(_cfg.get('halt', {
    'drawdown': -0.08, 'monthly_pf': 0.70, 'signal_drought': 30, 'prob_drift': 0.15,
}))




def flatten(df):
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = [c[0] for c in df.columns]
    return df.rename(columns={'Close': 'close', 'High': 'high', 'Low': 'low', 'Open': 'open', 'Volume': 'volume'})


def norm_index(df):
    if not isinstance(df.index, pd.DatetimeIndex):
        df.index = pd.to_datetime(df.index)
    idx = df.index
    if idx.tz is not None:
        df.index = idx.tz_convert('US/Eastern')
    else:
        df.index = idx.tz_localize('US/Eastern')
    return df


def _cache_path(ticker):
    return _STORE.cache_path(ticker)


def safe_download(ticker, **kwargs):
    delays = [5, 15, 45]
    for attempt, delay in enumerate(delays, 1):
        try:
            df = yf.download(ticker, **kwargs)
            if not df.empty:
                _STORE.save_cache(ticker, df)
                return df
            logger.warning(f"{ticker} empty response attempt {attempt}/3")
        except Exception as e:
            logger.warning(f"{ticker} download error attempt {attempt}/3: {e}")
        if attempt < len(delays):
            time.sleep(delay)
    logger.error(f"{ticker} failed after 3 attempts — using cached data")
    df = _STORE.load_cache(ticker)
    if df is not None:
        logger.info(f"{ticker} using cached data from {_STORE.cache_path(ticker)}")
        return df
    logger.error(f"{ticker} no cached data available")
    return pd.DataFrame()


def fetch_live(ticker, min_days=250):
    end = datetime.now(tz=ET)
    start = (end - pd.Timedelta(days=min_days)).strftime('%Y-%m-%d')
    df = safe_download(ticker, start=start, end=end.strftime('%Y-%m-%d'), auto_adjust=True, progress=False)
    if df.empty:
        raise ValueError(f'No live data for {ticker}')
    df = flatten(df)
    df = norm_index(df)
    return df


def fetch_history(ticker, years=10):
    end = datetime.now(tz=ET)
    start = f'{end.year - years}-01-01'
    df = safe_download(ticker, start=start, end=end.strftime('%Y-%m-%d'), auto_adjust=True, progress=False)
    if df.empty:
        raise ValueError(f'No history for {ticker}')
    df = flatten(df)
    df = norm_index(df)
    return df


def fetch_ref(ticker):
    try:
        return fetch_history(ticker, years=10)
    except Exception:
        return None


class AssetEngine:
    def __init__(self, ticker, name, contract, allocation, halt_config=None, config=None, expected_prob_conf=0.45, state_store=None, journal_path=None, sl_mult=1.0, tp_mult=2.5):
        self.ticker = ticker
        self.name = name
        self.contract = contract
        self.features = list(contract.features)
        self.allocation = allocation
        self.initial_capital = CONFIG['capital'] * allocation
        self.halt_config = halt_config or HALT
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
        self.pos_mgr = PositionManager(self.initial_capital, CONFIG['position_size'])
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
        self._research_mode = _cfg.get("research_mode", False)
        if state_store is not None:
            self.state_store = state_store
        elif journal_path is _SKIP_JOURNAL:
            self.state_store = None
        else:
            self.state_store = _STORE

    def _build_features(self, df, ref, macro):
        return build_features(df, macro, ref, self.contract)

    def _tb_vol(self, df):
        returns = np.log(df['close'] / df['close'].shift(1))
        vol = returns.ewm(span=100).std()
        return vol.iloc[-1] if not pd.isna(vol.iloc[-1]) else 0.01

    def _open_position(self, side, entry_price, entry_date, df=None):
        data = df if df is not None else self.price_data
        vol = self._tb_vol(data)
        if pd.isna(vol) or pd.isna(entry_price) or entry_price == 0:
            logger.error('%s: invalid entry_price=%s or vol=%s', self.name, entry_price, vol)
            return
        intent = PositionIntent.from_price_and_vol(side, entry_price, entry_date, vol, self.sl_mult, self.tp_mult)
        self.pos_mgr.open(intent)
        self.position = {
            'side': intent.side, 'entry': intent.entry_price,
            'sl': intent.stop_loss, 'tp': intent.take_profit,
            'entry_date': intent.entry_date, 'vol': intent.vol,
        }

    def _close_position(self, exit_price, exit_date, reason):
        trade = self.pos_mgr.close(exit_price, exit_date, reason)
        if trade is None:
            return
        trade['asset'] = self.name
        self.position = None
        self.current_value = self.pos_mgr.current_value
        self.trade_log = list(self.pos_mgr.trade_log)
        self._save_trade_journal(trade)

    def refresh_price(self):
        try:
            df = safe_download(self.ticker, period='5d', auto_adjust=True, progress=False)
            if not df.empty:
                df = flatten(df)
                close = float(df['close'].ffill().iloc[-1])
                self.current_price = None if pd.isna(close) else close
        except Exception:
            pass

    def train(self, force=False):
        if os.path.exists(self.model_path) and not force:
            with open(self.model_path, 'rb') as f:
                self.model = pickle.load(f)
                self._trained = True
            return

        logger.info('%s: downloading history...', self.name)
        df = fetch_history(self.ticker)
        ref = fetch_ref('SPY')
        macro = compute_macro_derived(pd.read_parquet(os.path.join(BASE, 'data/processed/macro_factors.parquet')))
        features = self._build_features(df, ref, macro)
        logger.info('%s: %d feature rows', self.name, len(features))

        end_date = features.index[-1]
        start_date = end_date - pd.DateOffset(years=CONFIG['retrain_window'])
        train = features[features.index >= start_date]
        if len(train) < 200:
            train = features

        X = train[self.features]
        y = train['label'].astype(int)
        split = int(len(X) * 0.8)

        model = xgb.XGBClassifier(
            n_estimators=300, max_depth=2, learning_rate=0.02,
            objective='multi:softprob', num_class=3,
            random_state=42, n_jobs=1, tree_method='hist', verbosity=0,
        )
        model.fit(X.iloc[:split], y.iloc[:split],
                  eval_set=[(X.iloc[split:], y.iloc[split:])], verbose=False)
        self.model = model
        self._trained = True
        with open(self.model_path, 'wb') as f:
            pickle.dump(model, f)

    def generate_signal(self, threshold=0.45):
        return self._generate_and_apply(threshold)

    def _generate_and_apply(self, threshold=0.45):
        self._ensure_position_synced()
        if not self._trained:
            self.train()

        df = fetch_live(self.ticker)
        self.price_data = df
        df['close'] = df['close'].ffill()
        if pd.isna(df['close'].iloc[-1]):
            raise ValueError(f'All close prices are NaN for {self.name}')
        self.current_price = float(df['close'].iloc[-1])
        ref = fetch_ref('SPY')
        macro = self._feature_pipeline.macro_derived(pd.read_parquet(os.path.join(BASE, 'data/processed/macro_factors.parquet')))
        features_df = self._feature_pipeline.build(df, macro, ref, self.contract)

        X = features_df[self.features]
        if len(X) == 0:
            raise ValueError(f'No valid feature rows after building features for {self.name}')

        proba = self._model_iface.predict(self.model, X)
        if proba.shape[1] < 3:
            raise ValueError(f'Model returned {proba.shape[1]} classes, expected 3')

        pos_size = self._sizing_strategy.compute(df['close'], self.config)

        result = self._signal_strategy.compute(proba, X.index, threshold, df['close'], pos_size)
        self.signal_data = result.signal_data

        latest = self.signal_data.iloc[-1]
        self.last_signal_date = latest.name

        decision = TradeDecision(
            asset=self.name,
            signal=result.signal_type,
            label=result.label,
            confidence=result.confidence_pct,
            prob_long=round(float(latest['prob_long']), 4),
            prob_short=round(float(latest['prob_short']), 4),
            prob_neutral=round(float(latest['prob_neutral']), 4),
            close_price=round(float(latest['close']), 4),
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
            close_price=float(latest['close']),
            current_side=self.pos_mgr.current_side(),
            halt_flags=self.check_halt_conditions(),
        )

        _shadow_signal_df = _w.compute_signals(proba, X.index, threshold)
        _shadow_latest = _shadow_signal_df.iloc[-1]
        _shadow_stype, _shadow_conf, _shadow_conf_pct = _w.signal_type_and_confidence(
            int(_shadow_latest["signal"]), float(_shadow_latest["prob_long"]), float(_shadow_latest["prob_short"])
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
                _proba_list, threshold,
                decision.signal, decision.confidence,
                _shadow_stype, _shadow_conf_pct,
            )
            _mod_div = diag.analyze_model_distribution(self.name, _proba_list)
            _feat_drivers = diag.analyze_feature_impact(
                self.model, X.iloc[[-1]], self.features, proba[-1:],
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

        self._reg.validate_strategies(self.name, {
            "_model": self._model_iface,
            "_signal": self._signal_strategy,
            "_sizing": self._sizing_strategy,
            "_pnl": self._pnl_strategy,
            "_feature_pipeline": self._feature_pipeline,
        })

        return self._decision_to_dict(decision)

    def _apply_decision(self, decision: TradeDecision, df):
        today = decision.timestamp
        current_side = self.pos_mgr.current_side()
        new_side = 'long' if decision.signal == 'BUY' else ('short' if decision.signal == 'SELL' else None)

        if new_side != current_side:
            if self.pos_mgr.has_position():
                self._close_position(decision.close_price, today, 'signal_flip')
            if new_side:
                self._open_position(new_side, decision.close_price, today, df)

        self.prob_history.append({
            'date': today,
            'prob_long': round(decision.prob_long * 100, 2),
            'prob_short': round(decision.prob_short * 100, 2),
            'signal': decision.signal,
            'confidence': decision.confidence,
            'close_price': decision.close_price,
        })
        self._log_confidence_buckets()

    def _decision_to_dict(self, decision: TradeDecision):
        pos = self.pos_mgr.position
        return {
            'asset': self.name,
            'signal': decision.signal,
            'confidence': decision.confidence,
            'close_price': decision.close_price,
            'date': decision.timestamp,
            'label': decision.label,
            'position': {
                'side': pos.side if pos else None,
                'entry': round(pos.entry_price, 4) if pos else None,
                'sl': round(pos.stop_loss, 4) if pos else None,
                'tp': round(pos.take_profit, 4) if pos else None,
                'current_pnl': round(self._position_pnl(decision.close_price), 4) if pos else None,
            } if pos else None,
        }

    def _position_pnl(self, current_price):
        return self.pos_mgr.position_pnl(current_price)

    def _ensure_position_synced(self):
        if self.position is not None and not self.pos_mgr.has_position():
            intent = PositionIntent(
                side=self.position['side'],
                entry_price=self.position['entry'],
                entry_date=self.position.get('entry_date', ''),
                stop_loss=self.position['sl'],
                take_profit=self.position['tp'],
                vol=self.position.get('vol', 0.01),
            )
            self.pos_mgr.open(intent)

    def update_pnl(self):
        self._ensure_position_synced()
        if self.signal_data is None or len(self.signal_data) < 2:
            return
        last_bar = str(self.signal_data.index[-1].date())
        if self.trades and self.trades[-1]['date'] == last_bar:
            return

        close = self.signal_data['close']
        today_close = float(close.iloc[-1])

        # Check SL/TP for open position
        if self.pos_mgr.has_position():
            hit = self.pos_mgr.check_sl_tp(today_close)
            if hit:
                self._close_position(hit[1], last_bar, hit[0])
                if self.current_value > self.peak_value:
                    self.peak_value = self.current_value
                return

        # If a position is open and no SL/TP was hit, track only position-based PnL
        # (entry vs current). The position PnL will be booked on close via
        # _close_position. Skip the signal-based path to avoid double counting.
        if self.pos_mgr.has_position():
            return

        # Daily PnL from previous signal
        sig = self.signal_data['signal'].iloc[-2]
        direction = 1 if sig == 2 else (-1 if sig == 0 else 0)
        pos_size = float(self.signal_data['position_size'].iloc[-2]) if 'position_size' in self.signal_data.columns else 1.0
        prev_close = float(close.iloc[-2])
        ret = (today_close / prev_close - 1) if len(close) >= 2 and prev_close != 0 and not pd.isna(today_close) and not pd.isna(prev_close) else 0
        if pd.isna(ret) or np.isinf(ret):
            ret = 0
        pnl = self.pos_mgr.compute_daily_pnl(direction, ret, pos_size)
        _shadow_pnl = _w.compute_daily_pnl(
            self.pos_mgr.current_value, direction, ret,
            self.pos_mgr.position_size, pos_size,
        )
        shadow_compare_pnl(asset=self.name, wrapper_pnl=_shadow_pnl, original_pnl=pnl)
        try:
            _pnl_decomp = diag.analyze_pnl_decomposition(
                self.pos_mgr.current_value, direction, ret,
                self.pos_mgr.position_size, pos_size, pnl,
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
            self.trades.append({
                'date': last_bar,
                'direction': direction,
                'return': float(ret),
                'pnl': float(pnl),
            })

    def get_metrics(self):
        self._ensure_position_synced()
        cv = self.current_value if not pd.isna(self.current_value) else self.initial_capital
        pv = self.peak_value if not pd.isna(self.peak_value) else cv
        dd = (cv - pv) / pv if pv > 0 else 0
        total_return = (cv - self.initial_capital) / self.initial_capital if self.initial_capital > 0 else 0

        monthly_pfs = []
        if self.trade_log:
            td = pd.DataFrame(self.trade_log)
            td['month'] = pd.to_datetime(td['exit_date']).dt.to_period('M')
            for m, g in td.groupby('month'):
                profits = g[g['pnl'] > 0]['pnl'].sum()
                losses = abs(g[g['pnl'] < 0]['pnl'].sum())
                monthly_pfs.append({'month': str(m), 'pf': profits / losses if losses > 0 else float('inf')})
        monthly_pf = monthly_pfs[-1]['pf'] if monthly_pfs else None

        total_profits = sum(t['pnl'] for t in self.trade_log if t['pnl'] > 0)
        total_losses = abs(sum(t['pnl'] for t in self.trade_log if t['pnl'] < 0))
        pf = total_profits / total_losses if total_losses > 0 else (float('inf') if total_profits > 0 else 0)

        win_rate = len([t for t in self.trade_log if t['pnl'] > 0]) / len(self.trade_log) if self.trade_log else 0
        sc = {'BUY': 0, 'SELL': 0, 'FLAT': 0}
        for p in self.prob_history:
            sc[p['signal']] = sc.get(p['signal'], 0) + 1
        mean_conf = np.mean([p['confidence'] for p in self.prob_history]) if self.prob_history else 0
        mean_conf = 0 if pd.isna(mean_conf) else mean_conf

        pos_info = None
        if self.pos_mgr.has_position():
            upnl = self._position_pnl(self.current_price) if self.current_price is not None and not pd.isna(self.current_price) else 0.0
            pos_info = {
                'side': self.pos_mgr.position.side,
                'entry': round(self.pos_mgr.position.entry_price, 4),
                'sl': round(self.pos_mgr.position.stop_loss, 4),
                'tp': round(self.pos_mgr.position.take_profit, 4),
                'current_vol': round(self.pos_mgr.position.vol, 6),
                'unrealized_pnl': round(upnl, 2),
            }

        pnl_pct = self._position_pnl(self.current_price) / 100 if self.pos_mgr.has_position() and self.current_price is not None and not pd.isna(self.current_price) else 0
        mtm_value = cv + cv * pnl_pct * CONFIG['position_size']
        mtm_return = (mtm_value - self.initial_capital) / self.initial_capital * 100 if self.initial_capital > 0 else 0

        mean_pl = np.mean([p['prob_long'] for p in self.prob_history]) if self.prob_history else 0
        mean_pl = 0 if pd.isna(mean_pl) else mean_pl
        mean_ps = np.mean([p['prob_short'] for p in self.prob_history]) if self.prob_history else 0
        mean_ps = 0 if pd.isna(mean_ps) else mean_ps

        return {
            'asset': self.name,
            'current_value': round(self.current_value, 2),
            'mtm_value': round(mtm_value, 2),
            'total_return': round(total_return * 100, 2),
            'mtm_return': round(mtm_return, 2),
            'drawdown': round(dd * 100, 2),
            'profit_factor': round(pf, 2),
            'win_rate': round(win_rate * 100, 2),
            'n_trades': len(self.trade_log),
            'n_signals': len(self.prob_history),
            'signal_distribution': sc,
            'mean_confidence': round(float(mean_conf), 2),
            'mean_prob_long': round(float(mean_pl), 2),
            'mean_prob_short': round(float(mean_ps), 2),
            'current_price': round(self.current_price, 4) if self.current_price else None,
            'last_signal_date': str(self.last_signal_date.date()) if self.last_signal_date else None,
            'monthly_pf': round(float(monthly_pf), 2) if monthly_pf else None,
            'position': pos_info,
            'trade_log': self.trade_log[-10:],
        }

    def _save_trade_journal(self, trade):
        if self.state_store is not None:
            self.state_store.append_trade(trade)

    def _log_confidence_buckets(self):
        bucket = {'asset': self.name, 'date': str(datetime.now(tz=ET).date())}
        for p in self.prob_history[-20:]:
            conf = p['confidence']
            bucket.setdefault(f'count_{int(conf/10)*10}_{int(conf/10+1)*10}', 0)
            bucket[f'count_{int(conf/10)*10}_{int(conf/10+1)*10}'] += 1
        bucket['mean_conf'] = np.mean([p['confidence'] for p in self.prob_history[-20:]]) if self.prob_history else 0
        bucket['n_signals'] = min(20, len(self.prob_history))
        if self.state_store is not None:
            self.state_store.append_confidence_bucket(bucket)

    def update_validity(self):
        halt = self.check_halt_conditions()
        score = 0.80
        if not halt['drawdown_ok']:
            score -= 0.25
        if not halt['monthly_pf_ok']:
            score -= 0.20
        if not halt['drought_ok']:
            score -= 0.15
        if not halt['drift_ok']:
            score -= 0.15
        score = max(0.0, min(1.0, score))
        result = self.validity_sm.transition(score, pd.Timestamp.now())
        return result

    def check_halt_conditions(self):
        metrics = self.get_metrics()
        dd = metrics.get('drawdown', 0) / 100
        if pd.isna(dd):
            dd = 0
        hc = self.halt_config
        reasons = []
        if dd <= hc['drawdown']:
            reasons.append(f'DD {metrics["drawdown"]:.1f}% <= {hc["drawdown"]*100:.0f}%')
        mpf = metrics.get('monthly_pf')
        if mpf is not None and not pd.isna(mpf) and mpf < hc['monthly_pf']:
            reasons.append(f'PF {mpf:.2f} < {hc["monthly_pf"]:.2f}')
        # Signal drought: halt if no signal generated within threshold days
        drought_ok = True
        drought_days = hc.get('signal_drought', 30)
        if self.last_signal_date is not None:
            days_since = (datetime.now(tz=ET).date() - pd.Timestamp(self.last_signal_date).date()).days
            if days_since > drought_days:
                reasons.append(f'Signal drought: {days_since}d > {drought_days}d')
                drought_ok = False
        # Prob drift: halt if mean confidence has drifted from expected baseline
        drift_ok = True
        prob_drift_limit = hc.get('prob_drift', 0.15)
        metrics = self.get_metrics()
        mean_conf = metrics.get('mean_confidence', 0) / 100
        if pd.isna(mean_conf):
            mean_conf = 0
        drift = abs(mean_conf - self.expected_prob_conf)
        if drift > prob_drift_limit:
            reasons.append(f'Confidence drift: {drift:.3f} > {prob_drift_limit:.2f}')
            drift_ok = False
        return {'halted': len(reasons) > 0, 'reasons': reasons,
                'drawdown_ok': dd > hc['drawdown'],
                'monthly_pf_ok': mpf is None or pd.isna(mpf) or mpf >= hc['monthly_pf'],
                'drought_ok': drought_ok,
                'drift_ok': drift_ok}


def _build_paper_portfolio():
    assets = _cfg.get('assets', {})
    if assets:
        pf = {}
        for name, spec in assets.items():
            ticker = spec.get('ticker', f'{name}')
            contract = FEATURE_REGISTRY.get(ticker)
            if contract is None:
                logger.warning("No contract for ticker %s; using config features", ticker)
                contract = type('Contract', (), {'features': spec.get('features', [])})()
            alloc = spec.get('allocation', 0)
            user_halt = spec.get('halt', {})
            halt = copy.deepcopy(HALT)
            halt.update(user_halt)
            config = spec.get('config', {})
            sl_mult = spec.get('sl_mult', 1.0)
            tp_mult = spec.get('tp_mult', 2.5)
            pf[name] = {'ticker': ticker, 'contract': contract, 'alloc': alloc,
                        'halt': halt, 'config': config,
                        'sl_mult': sl_mult, 'tp_mult': tp_mult}
        return pf
    return {
        'BTC': {'ticker': 'BTC-USD', 'contract': FEATURE_REGISTRY['BTC-USD'], 'alloc': 0.14,
                'halt': {'drawdown': -0.15, 'monthly_pf': 0.70, 'signal_drought': 30, 'prob_drift': 0.15}, 'config': {'vol_scalar': True}},
        'NZDJPY': {'ticker': 'NZDJPY=X', 'contract': FEATURE_REGISTRY['NZDJPY=X'], 'alloc': 0.11,
                   'halt': {'drawdown': -0.06, 'monthly_pf': 0.70, 'signal_drought': 30, 'prob_drift': 0.15}, 'config': {}},
        'CADJPY': {'ticker': 'CADJPY=X', 'contract': FEATURE_REGISTRY['CADJPY=X'], 'alloc': 0.10,
                   'halt': HALT, 'config': {}},
        'USDCAD': {'ticker': 'USDCAD=X', 'contract': FEATURE_REGISTRY['USDCAD=X'], 'alloc': 0.07,
                   'halt': HALT, 'config': {}},
        'GC': {'ticker': 'GC=F', 'contract': FEATURE_REGISTRY['GC=F'], 'alloc': 0.15,
               'halt': HALT, 'config': {}},
        'EURAUD': {'ticker': 'EURAUD=X', 'contract': FEATURE_REGISTRY['EURAUD=X'], 'alloc': 0.17,
                   'halt': HALT, 'config': {}},
        'AUDJPY': {'ticker': 'AUDJPY=X', 'contract': FEATURE_REGISTRY['AUDJPY=X'], 'alloc': 0.07,
                   'halt': HALT, 'config': {}},
        'GBPJPY': {'ticker': 'GBPJPY=X', 'contract': FEATURE_REGISTRY['GBPJPY=X'], 'alloc': 0.06,
                   'halt': HALT, 'config': {}},
        'USDJPY': {'ticker': 'USDJPY=X', 'contract': FEATURE_REGISTRY['USDJPY=X'], 'alloc': 0.05,
                   'halt': HALT, 'config': {}},
        'USDCHF': {'ticker': 'USDCHF=X', 'contract': FEATURE_REGISTRY['USDCHF=X'], 'alloc': 0.04,
                   'halt': HALT, 'config': {}},
        'GBPUSD': {'ticker': 'GBPUSD=X', 'contract': FEATURE_REGISTRY['GBPUSD=X'], 'alloc': 0.04,
                   'halt': HALT, 'config': {}},
    }


PAPER_PORTFOLIO = _build_paper_portfolio()
_total_alloc = sum(v['alloc'] for v in PAPER_PORTFOLIO.values())
assert abs(_total_alloc - 1.0) < 0.01, f"Portfolio allocations sum to {_total_alloc}, must be 1.0"


class PaperTradingEngine:
    def __init__(self, state_store=None):
        self.state_store = state_store or _STORE
        self.assets = {}
        self.start_date = datetime.now(tz=ET)
        self.last_update = None
        saved_positions = {}
        snapshot = self.state_store.load_snapshot()
        if snapshot is not None:
            eng_status = snapshot.engine_status or {}
            if eng_status.get('start_time'):
                self.start_date = datetime.fromisoformat(eng_status['start_time'])
            saved_positions = snapshot.open_positions or {}
        _reg = StrategyRegistry.get_instance()
        _reg.register_defaults(list(PAPER_PORTFOLIO.keys()))
        for name, spec in PAPER_PORTFOLIO.items():
            self.assets[name] = AssetEngine(
                spec['ticker'], name, spec['contract'], spec['alloc'],
                halt_config=spec['halt'], config=spec['config'],
                sl_mult=spec.get('sl_mult', 1.0), tp_mult=spec.get('tp_mult', 2.5),
                state_store=self.state_store,
            )
        for name, pos_data in saved_positions.items():
            if name in self.assets:
                asset = self.assets[name]
                pos_dict = pos_data.get('position')
                if pos_dict:
                    asset.position = pos_dict
                    intent = PositionIntent(
                        side=pos_dict['side'],
                        entry_price=pos_dict['entry'],
                        entry_date=pos_dict['entry_date'],
                        stop_loss=pos_dict['sl'],
                        take_profit=pos_dict['tp'],
                        vol=pos_dict['vol'],
                    )
                    asset.pos_mgr.open(intent)
                cv = pos_data.get('current_value')
                if cv is not None:
                    asset.current_value = cv
                    asset.pos_mgr.current_value = cv
                pv = pos_data.get('peak_value')
                if pv is not None:
                    asset.peak_value = pv
                    asset.pos_mgr.peak_value = pv
                asset.trade_log = pos_data.get('trade_log', [])
                asset.pos_mgr.trade_log = list(pos_data.get('trade_log', []))
                asset.prob_history = pos_data.get('prob_history', [])

    def initialize(self):
        from features.registry import ASSET_LABEL_PARAMS
        for name, asset in self.assets.items():
            registry_params = ASSET_LABEL_PARAMS.get(name)
            if registry_params is not None:
                assert asset.sl_mult == registry_params['sl'], \
                    f"{name}: runtime sl_mult {asset.sl_mult} != " \
                    f"training sl {registry_params['sl']} — labels misaligned"
                assert asset.tp_mult == registry_params['pt'], \
                    f"{name}: runtime tp_mult {asset.tp_mult} != " \
                    f"training pt {registry_params['pt']} — labels misaligned"
            try:
                asset.train(force=True)
                logger.info('%s: training done', name)
            except Exception as e:
                logger.error('%s: training FAILED - %s', name, e)

    def run_once(self):
        results = {}
        for name, asset in self.assets.items():
            try:
                signal = asset.generate_signal()
                asset.update_pnl()
                results[name] = signal
            except Exception as e:
                results[name] = {'asset': name, 'error': str(e)}
        # Update validity-driven exposure multipliers
        for name, asset in self.assets.items():
            validity = asset.update_validity()
            asset.pos_mgr.exposure_multiplier = validity.get('exposure', 1.0)
        self.last_update = datetime.now(tz=ET)
        return results

    def get_state(self):
        ad = {}
        overall_validity = 0.0
        any_halted = False
        for name, asset in self.assets.items():
            asset.refresh_price()
            metrics = asset.get_metrics()
            halt = asset.check_halt_conditions()
            validity = asset.update_validity()
            overall_validity += validity.get('exposure', 0.0)
            if halt['halted']:
                any_halted = True
            signal = dict(asset.prob_history[-1]) if asset.prob_history else None
            if signal and metrics.get('current_price'):
                signal['close_price'] = metrics['current_price']
            ad[name] = {
                'metrics': metrics,
                'halt': halt,
                'validity_state': validity.get('state', 'YELLOW'),
                'validity_exposure': validity.get('exposure', 0.5),
                'last_signal': signal,
                'execution_state': 'HALTED' if halt['halted'] else 'ACTIVE',
            }
        n = len(self.assets) or 1
        exec_state = ExecutionState.HALTED if any_halted else (
            ExecutionState.PAUSED if (overall_validity / n) < 0.5 else ExecutionState.ACTIVE
        )

        realized_total = sum(
            a.current_value if not pd.isna(a.current_value) else a.initial_capital
            for a in self.assets.values()
        )
        tc = sum(a.initial_capital for a in self.assets.values())

        unrealized_dollars = 0
        open_positions = 0
        closed_trades = 0
        for a in self.assets.values():
            closed_trades += len(a.trade_log)
            if a.pos_mgr.has_position() and a.current_price is not None and not pd.isna(a.current_price):
                open_positions += 1
                pnl_pct = a._position_pnl(a.current_price)
                if not pd.isna(pnl_pct):
                    cv = a.current_value if not pd.isna(a.current_value) else a.initial_capital
                    unrealized_dollars += cv * (pnl_pct / 100) * CONFIG['position_size']

        mtm_total = realized_total + unrealized_dollars
        mtm_return = (mtm_total - tc) / tc * 100 if tc > 0 else 0
        realized_return = (realized_total - tc) / tc * 100 if tc > 0 else 0

        delta = datetime.now(tz=ET) - self.start_date
        dr = delta.days
        runtime_hours = delta.total_seconds() / 3600

        return {
            'portfolio': {
                'total_value': round(mtm_total, 2),
                'mtm_value': round(mtm_total, 2),
                'total_return': round(mtm_return, 2),
                'realized_value': round(realized_total, 2),
                'realized_return': round(realized_return, 2),
                'unrealized_pnl': round(unrealized_dollars, 2),
                'days_running': dr,
                'runtime_hours': round(runtime_hours, 1),
                'start_date': self.start_date.strftime('%Y-%m-%d'),
                'start_datetime': self.start_date.isoformat(),
                'last_update': self.last_update.strftime('%Y-%m-%d %H:%M:%S') if self.last_update else None,
                'capital': CONFIG['capital'],
                'allocations': {n: a.allocation for n, a in self.assets.items()},
                'deployment_cleared': True,
                'open_positions': open_positions,
                'closed_trades': closed_trades,
                'execution_state': exec_state.value,
                'average_validity_exposure': round(overall_validity / n, 4),
            },
            'assets': ad,
            'halt_conditions': HALT,
        }

    def save_state(self):
        state = self.get_state()
        snapshot = EngineSnapshot(
            schema_version=EngineSnapshot.__dataclass_fields__['schema_version'].default,
            timestamp=datetime.now(tz=ET).isoformat(),
            portfolio=state.get('portfolio'),
            assets=state.get('assets'),
            open_positions={},
            engine_status={
                'initialized': True,
                'last_update': self.last_update.strftime('%Y-%m-%d %H:%M:%S') if self.last_update else None,
                'start_time': self.start_date.isoformat(),
            },
            halt_conditions=state.get('halt_conditions'),
            risk_signals={
                name: asset._risk_signal
                for name, asset in self.assets.items()
                if asset._risk_signal is not None
            } or None,
            shadow_actions={
                name: asset._shadow_action
                for name, asset in self.assets.items()
                if asset._shadow_action is not None
            } or None,
        )
        for name, asset in self.assets.items():
            if asset.pos_mgr.has_position():
                pos = asset.pos_mgr.position
                snapshot.open_positions[name] = {
                    'position': {
                        'side': pos.side,
                        'entry': pos.entry_price,
                        'sl': pos.stop_loss,
                        'tp': pos.take_profit,
                        'entry_date': pos.entry_date,
                        'vol': pos.vol,
                    },
                    'current_value': asset.pos_mgr.current_value,
                    'peak_value': asset.pos_mgr.peak_value,
                    'trade_log': asset.pos_mgr.trade_log,
                    'prob_history': asset.prob_history,
                }
        self._append_equity_history(state)
        self.state_store.save_snapshot(snapshot)
        return state

    def _append_equity_history(self, state):
        p = state.get('portfolio', {})
        total_value = p.get('total_value', 0)
        total_return = p.get('total_return', 0)
        gross = sum(
            a.get('metrics', {}).get('current_value', 0) or 0
            for a in state.get('assets', {}).values()
        )
        net_side = sum(
            (a.get('metrics', {}).get('position') or {}).get('side') == 'long'
            for a in state.get('assets', {}).values()
        )
        net = (net_side / len(state.get('assets', {}))) * 2 - 1 if state.get('assets') else 0
        dd_vals = [
            a.get('metrics', {}).get('drawdown', 0) or 0
            for a in state.get('assets', {}).values()
        ]
        drawdown = min(dd_vals) if dd_vals else 0

        record = {
            'timestamp': datetime.now(tz=ET).isoformat(),
            'portfolio_value': total_value,
            'portfolio_return': total_return,
            'drawdown': drawdown,
            'gross_exposure': round(gross / total_value, 4) if total_value else 0,
            'net_exposure': round(net, 4),
            'assets': {
                name: (a.get('metrics', {}).get('current_value') or 0)
                for name, a in state.get('assets', {}).items()
            },
        }
        self.state_store.append_equity_history(record)
