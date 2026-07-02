import json
import os
import sqlite3

import pandas as pd
import pytz

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LIVE_DIR = os.path.join(BASE_DIR, "data", "live")
DB_PATH = os.path.join(LIVE_DIR, "state.db")
ATTRIBUTION_PATH = os.path.join(LIVE_DIR, "attribution.parquet")
JOURNAL_PATH = os.path.join(LIVE_DIR, "trade_journal.parquet")
EQUITY_PATH = os.path.join(LIVE_DIR, "equity_history.json")

ET = pytz.timezone("US/Eastern")

def migrate():
    if not os.path.exists(DB_PATH):
        print(f"Error: Database not found at {DB_PATH}")
        return

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row

    # 1. Migrate Attribution
    if os.path.exists(ATTRIBUTION_PATH):
        print(f"Migrating attribution from {ATTRIBUTION_PATH}...")
        df_attr = pd.read_parquet(ATTRIBUTION_PATH)
        for _, row in df_attr.iterrows():
            # Check for duplicates
            exists = conn.execute(
                "SELECT id FROM attribution WHERE asset = ? AND entry_date = ? AND exit_date = ?",
                (row.get("asset"), str(row.get("entry_date", "")), str(row.get("exit_date", "")))
            ).fetchone()

            if not exists:
                conn.execute(
                    """INSERT INTO attribution (
                        asset, trade_id, entry_date, exit_date,
                        side, exit_price, exit_reason,
                        realized_r, realized_return, realized_pnl, theoretical_r,
                        policy_hash, archetype_version, exit_archetype,
                        pred_signal, pred_label, pred_confidence,
                        pred_prob_long, pred_prob_short, pred_prob_neutral, pred_meta_proba,
                        pred_regime_at_entry, pred_archetype_at_entry,
                        exec_entry_type, exec_deferred_bars,
                        exec_entry_price, exec_mid_price_at_signal, exec_entry_slippage_bps,
                        friction_entry_slippage_bps, friction_exit_slippage_bps,
                        exit_mae, exit_mfe, exit_mae_per_bar, exit_mfe_per_bar,
                        exit_realized_r, exit_bars_held, exit_exit_archetype
                    ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (
                        row.get("asset"), row.get("trade_id"), str(row.get("entry_date", "")), str(row.get("exit_date", "")),
                        row.get("side"), row.get("exit_price"), row.get("exit_reason"),
                        row.get("realized_r"), row.get("realized_return"), row.get("realized_pnl"), row.get("theoretical_r"),
                        row.get("policy_hash"), row.get("archetype_version"), row.get("exit_archetype"),
                        row.get("pred_signal"), row.get("pred_label"), row.get("pred_confidence"),
                        row.get("pred_prob_long"), row.get("pred_prob_short"), row.get("pred_prob_neutral"), row.get("pred_meta_proba"),
                        row.get("pred_regime_at_entry"), row.get("pred_archetype_at_entry"),
                        row.get("exec_entry_type"), row.get("exec_deferred_bars"),
                        row.get("exec_entry_price"), row.get("exec_mid_price_at_signal"), row.get("exec_entry_slippage_bps"),
                        row.get("friction_entry_slippage_bps"), row.get("friction_exit_slippage_bps"),
                        row.get("exit_mae"), row.get("exit_mfe"), row.get("exit_mae_per_bar"), row.get("exit_mfe_per_bar"),
                        row.get("exit_realized_r"), row.get("exit_bars_held"), row.get("exit_exit_archetype")
                    )
                )
        print("  Done migrating attribution.")

    # 2. Migrate Trade Journal
    if os.path.exists(JOURNAL_PATH):
        print(f"Migrating trades from {JOURNAL_PATH}...")
        df_journal = pd.read_parquet(JOURNAL_PATH)
        for _, row in df_journal.iterrows():
            exists = conn.execute(
                "SELECT id FROM trades WHERE asset = ? AND entry_date = ? AND exit_date = ?",
                (row.get("asset"), str(row.get("entry_date", "")), str(row.get("exit_date", "")))
            ).fetchone()

            if not exists:
                conn.execute(
                    """INSERT INTO trades (
                        asset, side, entry, exit, entry_date, exit_date,
                        return, pnl, total_pnl, reason, realized_r, bars,
                        conf_at_entry, archetype_at_entry, attribution_trade_id,
                        mae, mfe, mae_per_bar, mfe_per_bar,
                        entry_slippage_bps, exit_slippage_bps, fill_qty_ratio,
                        gap_fill, partial_fill, latency_bars,
                        pred_confidence, pred_archetype, pred_regime
                    ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (
                        row.get("asset"), row.get("side"), row.get("entry"), row.get("exit"),
                        str(row.get("entry_date", "")), str(row.get("exit_date", "")),
                        row.get("return"), row.get("pnl"), row.get("total_pnl"), row.get("reason"),
                        row.get("realized_r"), row.get("bars"), row.get("conf_at_entry"),
                        row.get("archetype_at_entry"), row.get("attribution_trade_id"),
                        row.get("mae"), row.get("mfe"), row.get("mae_per_bar"), row.get("mfe_per_bar"),
                        row.get("entry_slippage_bps"), row.get("exit_slippage_bps"), row.get("fill_qty_ratio"),
                        row.get("gap_fill"), row.get("partial_fill"), row.get("latency_bars"),
                        row.get("pred_confidence"), row.get("pred_archetype"), row.get("pred_regime")
                    )
                )
        print("  Done migrating trades.")

    # 3. Migrate Equity History
    if os.path.exists(EQUITY_PATH):
        print(f"Migrating equity history from {EQUITY_PATH}...")
        try:
            with open(EQUITY_PATH) as f:
                history = json.load(f)
            for record in history:
                exists = conn.execute(
                    "SELECT id FROM equity_history WHERE timestamp = ?",
                    (record.get("timestamp"),)
                ).fetchone()

                if not exists:
                    conn.execute(
                        """INSERT INTO equity_history (
                            timestamp, portfolio_value, portfolio_return, drawdown,
                            gross_exposure, net_exposure
                        ) VALUES (?,?,?,?,?,?)""",
                        (
                            record.get("timestamp"), record.get("portfolio_value"),
                            record.get("portfolio_return"), record.get("drawdown"),
                            record.get("gross_exposure"), record.get("net_exposure")
                        )
                    )
            print("  Done migrating equity history.")
        except Exception as e:
            print(f"  Failed to migrate equity history: {e}")

    conn.commit()
    conn.close()

    # Trigger refresh of analytics
    print("Refreshing analytics snapshots...")
    from paper_trading.state_store import StateStore
    store = StateStore(BASE_DIR)
    store.write_trade_outcomes_cache()
    # Force analytics refresh by resetting counter
    store._analytics_snapshot_counter = store._analytics_snapshot_frequency
    store.write_analytics_snapshot()
    print("Migration complete!")

if __name__ == "__main__":
    migrate()
