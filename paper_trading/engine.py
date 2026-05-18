import logging
import pandas as pd
import numpy as np
import xgboost as xgb
import yfinance as yf
import pickle, os, json, math, yaml
from datetime import datetime
from labels.triple_barrier import apply_triple_barrier

logger = logging.getLogger("quantforge.engine")

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MODEL_DIR = os.path.join(os.path.dirname(__file__), 'models')
STATE_PATH = os.path.join(BASE, 'data', 'live', 'state.json')
TRADE_JOURNAL_PATH = os.path.join(BASE, 'data', 'live', 'trade_journal.parquet')
CONFIDENCE_BUCKET_PATH = os.path.join(BASE, 'data', 'live', 'confidence_buckets.parquet')
CONFIG_PATH = os.path.join(BASE, 'configs', 'paper_trading.yaml')

os.makedirs(MODEL_DIR, exist_ok=True)
os.makedirs(os.path.dirname(STATE_PATH), exist_ok=True)


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

XLF_FEATURES = ['rate_diff', '2y_yield_delta_63', 'xlf_mom_63', 'xlf_vs_spy_63']
BTC_FEATURES = ['rate_diff', '2y_yield_delta_63', 'btc_mom_63', 'btc_vs_spy_63']
NZDJPY_FEATURES = ['vix_ma21', 'vix_delta_5', 'us_jp_10y_spread', 'nzdjpy_mom_21']
USDCAD_FEATURES = ['rate_diff', 'dxy_mom_21', 'vix_ma21', 'usdcad_mom_21']
CADJPY_FEATURES = ['ca_jp_spread_mom_5', 'ca_jp_spread_mom_21', 'cadjpy_mom_21', 'vix_ma21']


def load_macro():
    m = pd.read_parquet(os.path.join(BASE, 'data/processed/macro_factors.parquet'))
    m = m.reindex(pd.date_range(m.index.min(), m.index.max(), freq='D')).ffill()
    m['rate_diff'] = m['fed_funds'] - m['ecb_rate']
    m['2y_yield_delta_63'] = m['us_2y'].diff(63)
    m['dxy_mom_63'] = m['dxy'].pct_change(63)
    m['vix_ma21'] = m['vix'].rolling(21).mean()
    m['vix_delta_5'] = m['vix'].diff(5)
    m['us_jp_10y_spread'] = m['us_10y'] - m['jp_10y']
    return m.iloc[90:]


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


def fetch_live(ticker, min_days=250):
    end = datetime.now()
    start = (end - pd.Timedelta(days=min_days)).strftime('%Y-%m-%d')
    df = yf.download(ticker, start=start, end=end.strftime('%Y-%m-%d'), auto_adjust=True, progress=False)
    if df.empty:
        raise ValueError(f'No live data for {ticker}')
    df = flatten(df)
    df = norm_index(df)
    return df


def fetch_history(ticker, years=10):
    end = datetime.now()
    start = f'{end.year - years}-01-01'
    df = yf.download(ticker, start=start, end=end.strftime('%Y-%m-%d'), auto_adjust=True, progress=False)
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
    def __init__(self, ticker, name, features, allocation, halt_config=None, config=None, expected_prob_conf=0.45):
        self.ticker = ticker
        self.name = name
        self.features = features
        self.allocation = allocation
        self.initial_capital = CONFIG['capital'] * allocation
        self.halt_config = halt_config or HALT
        self.config = config or {}
        self.expected_prob_conf = expected_prob_conf
        self.model = None
        self.signal_data = None
        self.peak_value = self.initial_capital
        self.current_value = self.initial_capital
        self.start_time = datetime.now()
        self.last_signal_date = None
        self.trades = []
        self.prob_history = []
        self.model_path = os.path.join(MODEL_DIR, f'{name}_model.pkl')
        self._trained = False
        self.position = None
        self.trade_log = []
        self.current_price = None

    def _build_features(self, df, ref, macro):
        if self.name == 'CADJPY':
            ret = df['close'].pct_change(60).shift(-60)
            labels = ret.apply(lambda x: 2 if x > 0.02 else (0 if x < -0.02 else 1)).astype(int).dropna()
            pi = pd.DatetimeIndex([pd.Timestamp(x).tz_localize(None) for x in labels.index])
            a = macro.reindex(pi, method='ffill')
            a.index = labels.index
            a['ca_jp_10y_spread'] = a['ca_10y'] - a['jp_10y']
            a['ca_jp_spread_mom_21'] = a['ca_jp_10y_spread'].diff(21)
            a['ca_jp_spread_mom_5'] = a['ca_jp_10y_spread'].diff(5)
            a['cadjpy_mom_21'] = df['close'].pct_change(21)
            a['label'] = labels
        else:
            labeled = apply_triple_barrier(df, pt_sl=[2, 2], vertical_barrier=20)
            pi = pd.DatetimeIndex([pd.Timestamp(x).tz_localize(None) for x in labeled.index])
            a = macro.reindex(pi, method='ffill')
            a.index = labeled.index

            if self.name == 'XLF':
                a['xlf_mom_63'] = df['close'].pct_change(63)
                a['xlf_vs_spy_63'] = a['xlf_mom_63'] - ref['close'].pct_change(63)
            elif self.name == 'BTC':
                a['btc_mom_63'] = df['close'].pct_change(63)
                a['btc_vs_spy_63'] = a['btc_mom_63'] - ref['close'].pct_change(63)
            elif self.name == 'NZDJPY':
                a['nzdjpy_mom_21'] = df['close'].pct_change(21)
            elif self.name == 'USDCAD':
                a['dxy_mom_21'] = a['dxy'].pct_change(21)
                a['usdcad_mom_21'] = df['close'].pct_change(21)

            a['label'] = (labeled.loc[a.index, 'label'] + 1).astype(int)
        return a.dropna(subset=self.features + ['label'])

    def _vol_scalar(self, df, window=30, target_vol=0.30):
        rets = df['close'].pct_change().dropna()
        if len(rets) < window:
            return 1.0
        rv = rets.iloc[-window:].std() * np.sqrt(252)
        scalar = target_vol / (rv + 1e-9)
        return min(scalar, 1.0)

    def _tb_vol(self, df):
        returns = np.log(df['close'] / df['close'].shift(1))
        vol = returns.ewm(span=100).std()
        return vol.iloc[-1] if not vol.isna().all() else 0.01

    def _open_position(self, side, entry_price, entry_date, df=None):
        data = df if df is not None else self.price_data
        vol = self._tb_vol(data)
        if side == 'long':
            sl = entry_price * (1 - vol * 2)
            tp = entry_price * (1 + vol * 2)
        else:
            sl = entry_price * (1 + vol * 2)
            tp = entry_price * (1 - vol * 2)
        self.position = {
            'side': side, 'entry': entry_price,
            'sl': sl, 'tp': tp,
            'entry_date': entry_date,
            'vol': vol,
        }

    def _close_position(self, exit_price, exit_date, reason):
        if self.position is None:
            return
        side = self.position['side']
        entry = self.position['entry']
        ret = (exit_price / entry - 1) if side == 'long' else (entry / exit_price - 1)
        pnl = self.current_value * ret * CONFIG['position_size']
        trade = {
            'asset': self.name, 'side': side, 'entry': entry, 'exit': exit_price,
            'entry_date': self.position['entry_date'], 'exit_date': exit_date,
            'return': ret, 'pnl': pnl, 'reason': reason,
        }
        self.trade_log.append(trade)
        self.current_value += pnl
        self.position = None
        self._save_trade_journal(trade)

    def refresh_price(self):
        try:
            df = yf.download(self.ticker, period='5d', auto_adjust=True, progress=False)
            if not df.empty:
                df = flatten(df)
                self.current_price = float(df['close'].iloc[-1])
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
        macro = load_macro()
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
        if not self._trained:
            self.train()

        df = fetch_live(self.ticker)
        self.price_data = df
        self.current_price = float(df['close'].iloc[-1])
        ref = fetch_ref('SPY')
        macro = load_macro()
        features_df = self._build_features(df, ref, macro)

        X = features_df[self.features]
        if len(X) == 0:
            raise ValueError(f'No valid feature rows after building features for {self.name}')

        proba = self.model.predict_proba(X)
        if proba.shape[1] < 3:
            raise ValueError(f'Model returned {proba.shape[1]} classes, expected 3')

        probs_long = proba[:, 2]
        probs_short = proba[:, 0]
        signals = pd.Series(0, index=X.index)
        signals[probs_long > threshold] = 2
        signals[probs_short > threshold] = 0

        pos_size = self._vol_scalar(df) if self.config.get('vol_scalar') else 1.0

        self.signal_data = pd.DataFrame({
            'close': df['close'].reindex(X.index),
            'signal': signals,
            'prob_long': probs_long,
            'prob_short': probs_short,
            'prob_neutral': proba[:, 1],
            'position_size': pos_size,
        }, index=X.index)

        latest = self.signal_data.iloc[-1]
        self.last_signal_date = latest.name

        signal_type = 'BUY' if latest['signal'] == 2 else ('SELL' if latest['signal'] == 0 else 'FLAT')
        confidence = max(latest['prob_long'], latest['prob_short'])
        confidence_pct = round(float(confidence * 100), 2)

        # Position management: open/close based on signal vs current position
        today = str(latest.name.date())
        current_side = self.position['side'] if self.position else None
        new_side = 'long' if signal_type == 'BUY' else ('short' if signal_type == 'SELL' else None)

        if new_side != current_side:
            if self.position:
                self._close_position(float(latest['close']), today, 'signal_flip')
            if new_side:
                self._open_position(new_side, float(latest['close']), today, df)

        self.prob_history.append({
            'date': today,
            'prob_long': round(float(latest['prob_long'] * 100), 2),
            'prob_short': round(float(latest['prob_short'] * 100), 2),
            'signal': signal_type,
            'confidence': confidence_pct,
            'close_price': round(float(latest['close']), 4),
        })
        self._log_confidence_buckets()

        entry = self.position['entry'] if self.position else None
        sl = self.position['sl'] if self.position else None
        tp = self.position['tp'] if self.position else None
        pos_side = self.position['side'] if self.position else None

        return {
            'asset': self.name,
            'signal': signal_type,
            'confidence': confidence_pct,
            'close_price': round(float(latest['close']), 4),
            'date': today,
            'label': int(latest['signal']),
            'position': {
                'side': pos_side,
                'entry': round(entry, 4) if entry else None,
                'sl': round(sl, 4) if sl else None,
                'tp': round(tp, 4) if tp else None,
                'current_pnl': round(self._position_pnl(float(latest['close'])), 4) if self.position else None,
            } if self.position else None,
        }

    def _position_pnl(self, current_price):
        if self.position is None:
            return 0.0
        if self.position['side'] == 'long':
            return (current_price / self.position['entry'] - 1) * 100
        else:
            return (self.position['entry'] / current_price - 1) * 100

    def update_pnl(self):
        if self.signal_data is None or len(self.signal_data) < 2:
            return
        last_bar = str(self.signal_data.index[-1].date())
        if self.trades and self.trades[-1]['date'] == last_bar:
            return

        close = self.signal_data['close']
        today_close = float(close.iloc[-1])

        # Check SL/TP for open position
        if self.position:
            side = self.position['side']
            sl = self.position['sl']
            tp = self.position['tp']
            hit = None
            if side == 'long':
                if today_close <= sl:
                    hit = ('sl', sl)
                elif today_close >= tp:
                    hit = ('tp', tp)
            else:
                if today_close >= sl:
                    hit = ('sl', sl)
                elif today_close <= tp:
                    hit = ('tp', tp)
            if hit:
                self._close_position(hit[1], last_bar, hit[0])
                if self.current_value > self.peak_value:
                    self.peak_value = self.current_value
                return

        # If a position is open and no SL/TP was hit, track only position-based PnL
        # (entry vs current). The position PnL will be booked on close via
        # _close_position. Skip the signal-based path to avoid double counting.
        if self.position:
            return

        # Daily PnL from previous signal
        sig = self.signal_data['signal'].iloc[-2]
        direction = 1 if sig == 2 else (-1 if sig == 0 else 0)
        pos_size = float(self.signal_data['position_size'].iloc[-2]) if 'position_size' in self.signal_data.columns else 1.0
        ret = close.iloc[-1] / close.iloc[-2] - 1 if len(close) >= 2 else 0
        pnl = self.current_value * direction * ret * CONFIG['position_size'] * pos_size
        self.current_value += pnl
        if self.current_value > self.peak_value:
            self.peak_value = self.current_value
        if direction != 0:
            self.trades.append({
                'date': last_bar,
                'direction': direction,
                'return': float(ret),
                'pnl': float(pnl),
            })

    def get_metrics(self):
        dd = (self.current_value - self.peak_value) / self.peak_value if self.peak_value > 0 else 0
        total_return = (self.current_value - self.initial_capital) / self.initial_capital if self.initial_capital > 0 else 0

        monthly_pfs = []
        if self.trades:
            td = pd.DataFrame(self.trades)
            td['month'] = pd.to_datetime(td['date']).dt.to_period('M')
            for m, g in td.groupby('month'):
                profits = g[g['pnl'] > 0]['pnl'].sum()
                losses = abs(g[g['pnl'] < 0]['pnl'].sum())
                monthly_pfs.append({'month': str(m), 'pf': profits / losses if losses > 0 else float('inf')})
        monthly_pf = monthly_pfs[-1]['pf'] if monthly_pfs else None

        total_profits = sum(t['pnl'] for t in self.trades if t['pnl'] > 0)
        total_losses = abs(sum(t['pnl'] for t in self.trades if t['pnl'] < 0))
        pf = total_profits / total_losses if total_losses > 0 else (float('inf') if total_profits > 0 else 0)

        win_rate = len([t for t in self.trades if t['pnl'] > 0]) / len(self.trades) if self.trades else 0
        sc = {'BUY': 0, 'SELL': 0, 'FLAT': 0}
        for p in self.prob_history:
            sc[p['signal']] = sc.get(p['signal'], 0) + 1
        mean_conf = np.mean([p['confidence'] for p in self.prob_history]) if self.prob_history else 0

        pos_info = None
        if self.position:
            pos_info = {
                'side': self.position['side'],
                'entry': round(self.position['entry'], 4),
                'sl': round(self.position['sl'], 4),
                'tp': round(self.position['tp'], 4),
                'current_vol': round(self.position['vol'], 6),
                'unrealized_pnl': round(self._position_pnl(self.current_price), 2) if self.position and self.current_price is not None else 0.0,
            }

        mean_pl = np.mean([p['prob_long'] for p in self.prob_history]) if self.prob_history else 0
        mean_ps = np.mean([p['prob_short'] for p in self.prob_history]) if self.prob_history else 0

        return {
            'asset': self.name,
            'current_value': round(self.current_value, 2),
            'total_return': round(total_return * 100, 2),
            'drawdown': round(dd * 100, 2),
            'profit_factor': round(pf, 2),
            'win_rate': round(win_rate * 100, 2),
            'n_trades': len(self.trades),
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
        df = pd.DataFrame([trade])
        if os.path.exists(TRADE_JOURNAL_PATH):
            existing = pd.read_parquet(TRADE_JOURNAL_PATH)
            df = pd.concat([existing, df], ignore_index=True)
        df.to_parquet(TRADE_JOURNAL_PATH)

    def _log_confidence_buckets(self):
        bucket = {'asset': self.name, 'date': str(datetime.now().date())}
        for p in self.prob_history[-20:]:
            conf = p['confidence']
            bucket.setdefault(f'count_{int(conf/10)*10}_{int(conf/10+1)*10}', 0)
            bucket[f'count_{int(conf/10)*10}_{int(conf/10+1)*10}'] += 1
        bucket['mean_conf'] = np.mean([p['confidence'] for p in self.prob_history[-20:]]) if self.prob_history else 0
        bucket['n_signals'] = min(20, len(self.prob_history))
        df = pd.DataFrame([bucket])
        if os.path.exists(CONFIDENCE_BUCKET_PATH):
            existing = pd.read_parquet(CONFIDENCE_BUCKET_PATH)
            df = pd.concat([existing, df], ignore_index=True)
        df.to_parquet(CONFIDENCE_BUCKET_PATH)

    def check_halt_conditions(self):
        metrics = self.get_metrics()
        dd = metrics['drawdown'] / 100
        hc = self.halt_config
        reasons = []
        if dd <= hc['drawdown']:
            reasons.append(f'DD {metrics["drawdown"]:.1f}% <= {hc["drawdown"]*100:.0f}%')
        if metrics['monthly_pf'] is not None and metrics['monthly_pf'] < hc['monthly_pf']:
            reasons.append(f'PF {metrics["monthly_pf"]:.2f} < {hc["monthly_pf"]:.2f}')
        # Signal drought: halt if no signal generated within threshold days
        drought_ok = True
        drought_days = hc.get('signal_drought', 30)
        if self.last_signal_date is not None:
            days_since = (datetime.now().date() - pd.Timestamp(self.last_signal_date).date()).days
            if days_since > drought_days:
                reasons.append(f'Signal drought: {days_since}d > {drought_days}d')
                drought_ok = False
        # Prob drift: halt if mean confidence has drifted from expected baseline
        drift_ok = True
        prob_drift_limit = hc.get('prob_drift', 0.15)
        metrics = self.get_metrics()
        mean_conf = metrics.get('mean_confidence', 0) / 100
        drift = abs(mean_conf - self.expected_prob_conf)
        if drift > prob_drift_limit:
            reasons.append(f'Confidence drift: {drift:.3f} > {prob_drift_limit:.2f}')
            drift_ok = False
        return {'halted': len(reasons) > 0, 'reasons': reasons,
                'drawdown_ok': dd > hc['drawdown'],
                'monthly_pf_ok': metrics['monthly_pf'] is None or metrics['monthly_pf'] >= hc['monthly_pf'],
                'drought_ok': drought_ok,
                'drift_ok': drift_ok}


def _build_paper_portfolio():
    assets = _cfg.get('assets', {})
    if assets:
        pf = {}
        for name, spec in assets.items():
            ticker = spec.get('ticker', f'{name}')
            features = spec.get('features', [])
            alloc = spec.get('allocation', 0)
            halt = dict(spec.get('halt', HALT))
            config = spec.get('config', {})
            pf[name] = {'ticker': ticker, 'features': features, 'alloc': alloc,
                        'halt': halt, 'config': config}
        return pf
    return {
        'XLF': {'ticker': 'XLF', 'features': XLF_FEATURES, 'alloc': 0.30,
                'halt': HALT, 'config': {}},
        'BTC': {'ticker': 'BTC-USD', 'features': BTC_FEATURES, 'alloc': 0.25,
                'halt': {'drawdown': -0.15, 'monthly_pf': 0.70, 'signal_drought': 30, 'prob_drift': 0.15}, 'config': {'vol_scalar': True}},
        'NZDJPY': {'ticker': 'NZDJPY=X', 'features': NZDJPY_FEATURES, 'alloc': 0.18,
                   'halt': {'drawdown': -0.06, 'monthly_pf': 0.70, 'signal_drought': 30, 'prob_drift': 0.15}, 'config': {}},
        'USDCAD': {'ticker': 'USDCAD=X', 'features': USDCAD_FEATURES, 'alloc': 0.12,
                   'halt': HALT, 'config': {}},
        'CADJPY': {'ticker': 'CADJPY=X', 'features': CADJPY_FEATURES, 'alloc': 0.15,
                   'halt': HALT, 'config': {}},
    }


PAPER_PORTFOLIO = _build_paper_portfolio()
_total_alloc = sum(v['alloc'] for v in PAPER_PORTFOLIO.values())
assert abs(_total_alloc - 1.0) < 0.01, f"Portfolio allocations sum to {_total_alloc}, must be 1.0"


class PaperTradingEngine:
    def __init__(self):
        self.assets = {}
        self.start_date = datetime.now()
        self.last_update = None
        for name, spec in PAPER_PORTFOLIO.items():
            self.assets[name] = AssetEngine(
                spec['ticker'], name, spec['features'], spec['alloc'],
                halt_config=spec['halt'], config=spec['config'],
            )

    def initialize(self):
        for name, asset in self.assets.items():
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
        self.last_update = datetime.now()
        return results

    def get_state(self):
        ad = {}
        for name, asset in self.assets.items():
            asset.refresh_price()
            metrics = asset.get_metrics()
            halt = asset.check_halt_conditions()
            signal = dict(asset.prob_history[-1]) if asset.prob_history else None
            if signal and metrics.get('current_price'):
                signal['close_price'] = metrics['current_price']
            ad[name] = {'metrics': metrics, 'halt': halt, 'last_signal': signal}

        tv = sum(a.current_value for a in self.assets.values())
        tc = sum(a.initial_capital for a in self.assets.values())
        tr = (tv - tc) / tc * 100 if tc > 0 else 0
        dr = (datetime.now() - self.start_date).days

        return {
            'portfolio': {
                'total_value': round(tv, 2), 'total_return': round(tr, 2),
                'days_running': dr,
                'start_date': self.start_date.strftime('%Y-%m-%d'),
                'last_update': self.last_update.strftime('%Y-%m-%d %H:%M:%S') if self.last_update else None,
                'capital': CONFIG['capital'],
                'allocations': {n: a.allocation for n, a in self.assets.items()},
                'deployment_cleared': True,
            },
            'assets': ad,
            'halt_conditions': HALT,
        }

    def _sanitize(self, obj):
        if isinstance(obj, dict):
            return {k: self._sanitize(v) for k, v in obj.items()}
        elif isinstance(obj, list):
            return [self._sanitize(v) for v in obj]
        elif isinstance(obj, float) and (math.isinf(obj) or math.isnan(obj)):
            return None
        return obj

    def save_state(self, path=None):
        path = path or STATE_PATH
        state = self.get_state()
        state['engine_status'] = {
            'initialized': True,
            'last_update': self.last_update.strftime('%Y-%m-%d %H:%M:%S') if self.last_update else None,
            'start_time': self.start_date.isoformat(),
        }
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, 'w') as f:
            json.dump(self._sanitize(state), f, indent=2, default=str)
        return state
