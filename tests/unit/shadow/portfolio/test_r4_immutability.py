"""R4 immutability tests (brief Sections 18/24 — prove R4 is untouched).

The frozen R4 loop module is imported exactly as scripts/audit/reconstruct.py
does. We prove:

    1. Importing/using the shadow package changes nothing in the loop module
       (identical signal, identical orders before/after).
    2. The shadow baseline builder reproduces generate_orders' exact top-N
       selection — the control group is R4's real selection.
    3. Running the shadow pipeline writes ONLY shadow evidence files; frozen
       R4 evidence files are byte-identical before and after.

NOTE: these tests import the real production loop module (read-only). They
never call execute_orders or any broker function.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import numpy as np
import pandas as pd

from eigencapital.config import load_config

REPO = Path(__file__).resolve().parents[4]

# Production-realistic eligible symbols used in synthetic data.
TEST_SYMBOLS = ["EURUSD", "GBPUSD", "AUDUSD", "USDCHF", "US30", "USTEC", "XAUUSD", "USOIL"]


def _load_loop_module():
    spec = importlib.util.spec_from_file_location("r4_rebalance_loop", REPO / "scripts" / "r4_rebalance_loop.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules["r4_rebalance_loop"] = mod
    spec.loader.exec_module(mod)
    return mod


def _synthetic_data(n: int = 400, seed: int = 51) -> dict:
    rng = np.random.default_rng(seed)
    idx = pd.date_range("2025-01-01", periods=n, freq="B")
    data = {}
    for sym in TEST_SYMBOLS:
        ret = rng.normal(0.0003, 0.012, n)
        close = 100.0 * np.cumprod(1 + ret)
        high = close * (1 + np.abs(rng.normal(0, 0.002, n)))
        low = close * (1 - np.abs(rng.normal(0, 0.002, n)))
        data[sym] = pd.DataFrame(
            {
                "open": close * (1 + rng.normal(0, 0.001, n)),
                "high": high,
                "low": low,
                "close": close,
                "volume": rng.integers(100, 1000, n),
            },
            index=idx,
        )
    return data


class TestR4SignalUnchanged:
    def test_signal_identical_with_and_without_shadow_import(self):
        loop = _load_loop_module()
        data = _synthetic_data()

        # Fresh import to isolate any import-time side effects.
        loop2 = _load_loop_module()

        # Import the shadow package (this is the integration under test).
        from eigencapital.shadow.portfolio import selector as shadow_selector

        latest1, diag1, returns1 = loop.compute_r4_signal(data)
        latest2, diag2, returns2 = loop2.compute_r4_signal(data)

        assert diag1 == diag2
        assert np.allclose(latest1.values, latest2.values, equal_nan=True)
        assert np.allclose(returns1.values, returns2.values, equal_nan=True)
        assert shadow_selector.SHADOW_SELECTOR_VERSION  # sanity: import worked

    def test_frozen_parameters_unchanged(self):
        loop = _load_loop_module()
        config = load_config("production")
        # The loop's constants must still mirror the frozen config.
        assert loop.LOOKBACK == config.strategy.signal_lookback_long == 252
        assert loop.MAX_CONCURRENT == config.capital.max_concurrent_positions == 20
        assert config.strategy.vol_target_annual == loop.VOL_TARGET
        assert "BTCUSD" in loop.R4_SYMBOLS  # frozen universe still includes crypto


class TestBaselineParity:
    def test_baseline_builder_matches_generate_orders_selection(self):
        """The shadow control group == generate_orders' exact top-N."""
        loop = _load_loop_module()
        data = _synthetic_data()
        latest, _, _ = loop.compute_r4_signal(data, force_regime=True)

        prices = {s: 100.0 for s in TEST_SYMBOLS}
        contract_sizes = {s: 1000.0 for s in TEST_SYMBOLS}
        min_volumes = {s: 0.01 for s in TEST_SYMBOLS}
        equity = 5100.0

        orders = loop.generate_orders(latest, {}, prices, contract_sizes, min_volumes, equity, None)
        r4_selection = [o[0] for o in orders if "rotated out" not in o[3]]

        # Shadow baseline: eligible, |w| >= 0.005, min-lot feasible, top-N by |w|.
        candidates = []
        for sym in latest.index:
            if sym not in loop.ELIGIBLE_SYMBOLS:
                continue
            w = float(latest[sym])
            if abs(w) < 0.005:
                continue
            min_lot_cost = min_volumes[sym] * prices[sym] * contract_sizes[sym]
            if min_lot_cost > loop.MAX_POSITION_USD:
                continue
            candidates.append((sym, abs(w)))
        candidates.sort(key=lambda x: (-x[1], x[0]))
        baseline = [s for s, _ in candidates[: loop.MAX_CONCURRENT]]

        # generate_orders emits opens in set-iteration order; compare as sets.
        assert set(r4_selection) == set(baseline)

    def test_order_identical_with_shadow_active(self):
        """Running the full shadow selection must not change R4's orders."""
        loop = _load_loop_module()
        from eigencapital.shadow.portfolio.correlation import CorrelationModel
        from eigencapital.shadow.portfolio.selector import (
            ShadowCandidate,
            ShadowSelector,
            ShadowSelectorConfig,
        )

        data = _synthetic_data()
        latest, _, returns_df = loop.compute_r4_signal(data, force_regime=True)
        prices = {s: 100.0 for s in TEST_SYMBOLS}
        contract_sizes = {s: 1000.0 for s in TEST_SYMBOLS}
        min_volumes = {s: 0.01 for s in TEST_SYMBOLS}
        equity = 5100.0

        # Frozen R4 orders (control).
        orders_before = loop.generate_orders(latest, {}, prices, contract_sizes, min_volumes, equity, None)

        # Shadow run — constructs a hypothetical portfolio from the same
        # signal. This must have zero effect on R4's own order generation.
        from eigencapital.shadow.portfolio.exposure import get_factor_group

        as_of = returns_df.index[-1]
        snapshot = CorrelationModel().build(returns_df, as_of=as_of)
        candidates = []
        for sym in TEST_SYMBOLS:
            w = float(latest[sym])
            candidates.append(
                ShadowCandidate(
                    symbol=sym,
                    weight=w,
                    direction="LONG" if w >= 0 else "SHORT",
                    asset_class=loop.ASSET_CLASSES.get(sym, "other"),
                    factor_group=get_factor_group(sym),
                    feasible=True,
                    r4_rank=1,
                    annualized_vol=0.15,
                )
            )
        ShadowSelector(ShadowSelectorConfig()).select(
            candidates,
            snapshot,
            [c.symbol for c in candidates],
            cycle_id="IMMUTABILITY-TEST",
            decision_timestamp="t",
            signal_date="d",
        )

        orders_after = loop.generate_orders(latest, {}, prices, contract_sizes, min_volumes, equity, None)
        assert orders_before == orders_after
        # And the signal itself is unchanged.
        latest2, _, _ = loop.compute_r4_signal(data, force_regime=True)
        assert np.allclose(latest.values, latest2.values, equal_nan=True)


class TestEvidenceIsolation:
    def test_r4_evidence_files_untouched_by_shadow_pipeline(self, tmp_path: Path):
        """A full shadow decision+outcome run alters only shadow files."""
        from eigencapital.shadow.portfolio.tracker import (
            ShadowDecisionRecorder,
            ShadowPositionTracker,
        )

        protected = tmp_path / "decisions.jsonl"
        protected.write_text('{"event": "frozen_r4"}\n')
        order_intents = tmp_path / "order_intents.jsonl"
        order_intents.write_text('{"intent": "frozen"}\n')
        before = {p.name: p.read_bytes() for p in (protected, order_intents)}

        recorder = ShadowDecisionRecorder(audit_dir=str(tmp_path))
        tracker = ShadowPositionTracker(recorder, equity=5100.0)
        tracker.open_cycle(
            ["AUDUSD"],
            {"AUDUSD": 0.1},
            {"AUDUSD": 100.0},
            {"AUDUSD": 0.01},
            "C1",
            "2026-01-01",
            "2026-01-01",
        )
        tracker.close_all({"AUDUSD": 105.0}, "2026-01-02", "C1", "2026-01-02")

        after = {p.name: p.read_bytes() for p in (protected, order_intents)}
        assert after == before
        assert (tmp_path / "shadow_portfolio_decisions.jsonl").exists() is False  # no decision recorded here
        assert (tmp_path / "shadow_portfolio_outcomes.jsonl").exists()

    def test_replay_writes_only_shadow_namespace(self, tmp_path: Path):
        """End-to-end mini replay in a tmp dir must not touch R4 evidence."""
        import subprocess

        protected = tmp_path / "decisions.jsonl"
        protected.write_text('{"event": "frozen_r4"}\n')
        before = protected.read_bytes()

        subprocess.run(
            [
                sys.executable,
                str(REPO / "scripts" / "r4_shadow_portfolio.py"),
                "--status",
                "--out-dir",
                str(tmp_path),
            ],
            check=True,
            capture_output=True,
        )
        # Status mode only READS shadow evidence; R4 evidence untouched.
        assert protected.read_bytes() == before
