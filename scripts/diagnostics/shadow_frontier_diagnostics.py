"""One-off diagnostic: shadow size frontier — MTM quarterly stability, churn, attribution.

Reads the DEDUPED per-size chains from reports/r4_loop/shadow_portfolio_decisions.jsonl
(keep-last per cycle_id, filtered to the replay window) and replays them on local D1
closes using scripts/r4_shadow_portfolio.py's own universe builder and conventions:

  * rotate at the decision-bar close against that bar's chain symbols (identical to
    _SizeTracker.step in r4_shadow_portfolio.py — no extra lag),
  * weights = decision.selected["weights"] restricted to the chain (no renormalization),
  * 10 bps per side on rotated weight, |w|·equity notional proxy,
  * MTM accrual on every price bar so quarterly P&L lands in the quarter it accrued in
    (unlike shadow_portfolio_size_breakdown.jsonl, which is realized-on-exit).

Sections printed:
  1.  QUARTERLY — net P&L per size per quarter + reconciliation vs the size-breakdown file
  1b. REGIME    — same net P&L bucketed by the frozen gate's vol-ratio (avg_vol / expanding median)
  2.  CHURN     — per-size rotation cost attribution by symbol
  3.  ATTRIB    — per-symbol gross P&L for the N=6 chain (top contributors/detractors)

SHADOW-ONLY / diagnostic. Writes nothing.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "src"))

from eigencapital.config import load_config  # noqa: E402

WINDOW = ("2025-01-01", "2026-09-15")
SIZES = [1, 2, 4, 5, 6, 7, 8]
BASELINE_SIZE = 20
DECISIONS = REPO / "reports/r4_loop/shadow_portfolio_decisions.jsonl"
SIZE_BREAKDOWN = REPO / "reports/r4_loop/shadow_portfolio_size_breakdown.jsonl"

# ── Load the replay script as a module (reuses its universe builder + constants) ──
spec = importlib.util.spec_from_file_location("r4sp", REPO / "scripts" / "r4_shadow_portfolio.py")
r4sp = importlib.util.module_from_spec(spec)
sys.modules["r4sp"] = r4sp
spec.loader.exec_module(r4sp)


def load_decisions() -> dict[str, dict]:
    recs = []
    with open(DECISIONS) as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    recs.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
    recs = [r for r in recs if WINDOW[0] <= str(r.get("signal_date", "")) <= WINDOW[1]]
    by_cycle: dict[str, dict] = {}
    for r in recs:
        by_cycle[r["cycle_id"]] = r  # append-only file: later lines = later runs win
    return by_cycle


def main() -> int:
    config = load_config("production")
    allowed = dict(config.broker.allowed_symbols)
    asset_classes = {s: cls.split("_")[0] for s, cls in allowed.items()}

    decisions = load_decisions()
    sel = {pd.Timestamp(r["signal_date"]): r for r in decisions.values() if r.get("status") == "SELECTED"}
    sel_dates = sorted(sel)
    print(f"window {WINDOW[0]} → {WINDOW[1]}   deduped decisions: {len(decisions)}   SELECTED: {len(sel_dates)}")
    if not sel_dates:
        print("nothing to replay")
        return 1

    # ── Prices: full universe wide-close frame from the replay script's builder ──
    frames = r4sp.build_universe(allowed)
    signal_syms = sorted(s for s in frames if s in allowed)
    cw = pd.DataFrame({s: frames[s]["close"] for s in signal_syms}).sort_index()
    bars = cw.loc[(cw.index >= WINDOW[0]) & (cw.index <= WINDOW[1])].index

    equity = r4sp.EQUITY_FOR_SHADOW
    bps = r4sp.COST_PER_SIDE_BPS / 1e4

    def px(d, sym):
        try:
            v = cw.at[d, sym]
        except KeyError:
            return None
        return float(v) if np.isfinite(v) else None

    # Per-size replay state: open book, completed positions, accrual ledger
    books = {n: {} for n in SIZES}  # n -> sym -> [entry_date, w, entry_px]
    base_book: dict[str, list] = {}
    positions = {n: [] for n in SIZES}  # n -> list of completed position dicts
    base_positions: list[dict] = []
    accrual_daily = defaultdict(float)  # (date, n) -> MTM pnl accrued that bar
    cost_daily = defaultdict(float)  # (date, n) -> rotation cost paid that bar
    churn = defaultdict(lambda: [0.0, 0.0])  # (n, sym) -> [cost_paid, one_way_turnover]
    prev_px: dict[tuple[int, str], float] = {}  # (n, sym) -> last accrual price (daily-diff telescoping)

    # Vol-ratio series (same formula as the frozen regime gate) for bucketing.
    returns_df = cw.pct_change().dropna(how="all").ffill().fillna(0)
    avg_vol_series = returns_df.rolling(20).std().mean(axis=1) * np.sqrt(252)
    risk_median_series = avg_vol_series.expanding().median()
    vol_ratio_series = avg_vol_series / risk_median_series

    def rotate(d, book, target_syms, weights, done_list, n_key):
        """Close what left the target, open what entered. Mirrors _SizeTracker.step."""
        turnover = 0.0
        for sym in list(book):
            if sym in target_syms:
                continue
            p = px(d, sym)
            if p is None:
                continue  # mirror _SizeTracker: defer close until a price exists
            entry_date, w, _ep = book.pop(sym)
            prev_px.pop((n_key, sym), None)
            done_list.append(
                {
                    "sym": sym,
                    "entry": entry_date,
                    "exit": d,
                    "w": w,
                    "pnl": (1.0 if w > 0 else -1.0) * (p / _ep - 1.0) * abs(w) * equity,
                }
            )
            c = bps * abs(w) * equity
            churn[(n_key, sym)][0] += c
            churn[(n_key, sym)][1] += abs(w)
            cost_daily[(d, n_key)] += c
            turnover += abs(w)
        for sym in target_syms:
            if sym in book:
                continue
            p = px(d, sym)
            w = float(weights.get(sym, 0.0))
            if p is None or w == 0.0:
                continue
            book[sym] = [d, w, p]
            prev_px[(n_key, sym)] = p
            c = bps * abs(w) * equity
            churn[(n_key, sym)][0] += c
            churn[(n_key, sym)][1] += abs(w)
            cost_daily[(d, n_key)] += c
            turnover += abs(w)
        return turnover

    sel_set = set(sel_dates)
    for d in bars:
        if d in sel_set:
            rec = sel[d]
            weights = rec["selected"]["weights"]
            chain = rec.get("chain_by_n") or {}
            for n in SIZES:
                entry = chain.get(str(n)) or chain.get(n)
                if entry is not None:
                    rotate(d, books[n], entry["symbols"], weights, positions[n], n)
            rotate(d, base_book, rec["baseline"]["symbols"], rec["baseline"]["weights"], base_positions, BASELINE_SIZE)
        # Daily MTM accrual for every open book: the DAILY diff vs the previous
        # accrual price (telescopes to the entry→exit move; just-opened = 0).
        for n in SIZES:
            for sym, (_ed, w, ep) in books[n].items():
                p = px(d, sym)
                if p is None:
                    continue
                pp = prev_px.get((n, sym), ep)
                accrual_daily[(d, n)] += (1.0 if w > 0 else -1.0) * (p / pp - 1.0) * abs(w) * equity
                prev_px[(n, sym)] = p
        for sym, (_ed, w, ep) in base_book.items():
            p = px(d, sym)
            if p is not None:
                pp = prev_px.get((BASELINE_SIZE, sym), ep)
                accrual_daily[(d, BASELINE_SIZE)] += (1.0 if w > 0 else -1.0) * (p / pp - 1.0) * abs(w) * equity
                prev_px[(BASELINE_SIZE, sym)] = p

    # Final liquidation at the last price bar (mirrors _SizeTracker.close_all: cost, no extra pnl).
    last = bars[-1]
    for n in SIZES:
        rotate(last, books[n], [], {}, positions[n], n)
    rotate(last, base_book, [], {}, base_positions, BASELINE_SIZE)

    all_positions = {n: positions[n] for n in SIZES}
    all_positions[BASELINE_SIZE] = base_positions

    # ── Section 1: quarterly net table ────────────────────────────────────
    print("\n" + "█" * 78)
    print("1. QUARTERLY MTM STABILITY  (net of 10 bps/side, accrual basis)")
    print("█" * 78)
    cols = SIZES + [BASELINE_SIZE]
    daily_rows = [{"date": d, "n": n, "pnl": v} for (d, n), v in accrual_daily.items()]
    daily_rows += [{"date": d, "n": n, "pnl": -v} for (d, n), v in cost_daily.items()]
    daily = pd.DataFrame(daily_rows)
    daily["q"] = daily["date"].map(lambda x: pd.Period(x, freq="Q"))
    piv = daily.pivot_table(index="q", columns="n", values="pnl", aggfunc="sum").reindex(columns=cols).fillna(0.0)
    quarters = list(piv.index)

    hdr = "quarter    " + "".join(f"{n:>8}" for n in SIZES) + f"{BASELINE_SIZE:>9}   best-shadow"
    print(hdr)
    print("─" * len(hdr))
    for q in quarters:
        row = piv.loc[q]
        best = row[SIZES].idxmax()
        flag = "yes" if row[best] > row[BASELINE_SIZE] else "NO"
        print(
            f"{q!s:<10} "
            + "".join(f"{row[n]:>+8.0f}" for n in SIZES)
            + f"{row[BASELINE_SIZE]:>+9.0f}   N={best} ({flag} vs R4)"
        )

    n6_beats = sum(piv.at[q, 6] > piv.at[q, BASELINE_SIZE] for q in quarters)
    n6_pos = sum(piv.at[q, 6] > 0 for q in quarters)
    print(f"\nN=6 beats R4-20 in {n6_beats}/{len(quarters)} quarters; positive in {n6_pos}/{len(quarters)}")

    years = (bars[-1] - bars[0]).days / 365.25
    print(f"\n{'size':>6}{'net':>10}{'net ret':>9}{'ann ret':>9}{'positions':>10}{'win rate':>9}")
    for n in cols:
        gross = sum(p["pnl"] for p in all_positions[n])
        cost = sum(v for (_d, k), v in cost_daily.items() if k == n)
        net = gross - cost
        wp = (
            sum(1 for p in all_positions[n] if p["pnl"] > 0) / len(all_positions[n])
            if all_positions[n]
            else float("nan")
        )
        print(
            f"{n:>6}{net:>+10.0f}{100 * net / equity:>8.1f}%{100 * net / equity / years:>8.1f}%{len(all_positions[n]):>10}{100 * wp:>8.1f}%"
        )

    # Reconciliation vs the realized-basis file (same events, different attribution).
    if SIZE_BREAKDOWN.exists():
        sb = pd.read_json(SIZE_BREAKDOWN, lines=True)  # incl. END liquidation rows: same events as our replay
        print("\nreconciliation vs shadow_portfolio_size_breakdown.jsonl (gross / cost / net):")
        for n in cols:
            g_sb = sb[sb["size"] == n].gross_pnl.sum()
            c_sb = sb[sb["size"] == n].cost.sum()
            g_my = sum(p["pnl"] for p in all_positions[n])
            c_my = sum(v for (_d, k), v in cost_daily.items() if k == n)
            print(
                f"  size {n:>2}: gross {g_my:>+9.2f} vs {g_sb:>+9.2f} (Δ{g_my - g_sb:+.2f})   "
                f"cost {c_my:>7.2f} vs {c_sb:>7.2f} (Δ{c_my - c_sb:+.2f})"
            )

    # ── Section 1b: vol-ratio regime buckets ─────────────────────────
    print("\n" + "█" * 78)
    print("1b. VOL-RATIO REGIME BUCKETS  (net MTM, same accrual basis as above)")
    print("█" * 78)

    def vr_bucket(r: float) -> str:
        if pd.isna(r):
            return "n/a"
        if r >= 1.0:
            return "off (≥1.00)"
        if r >= 0.90:
            return "0.90–1.00"
        if r >= 0.75:
            return "0.75–0.90"
        return "<0.75"

    daily["vr"] = daily["date"].map(lambda x: float(vol_ratio_series.get(x, np.nan)))
    daily["bucket"] = daily["vr"].map(vr_bucket)
    bpiv = daily.pivot_table(index="bucket", columns="n", values="pnl", aggfunc="sum").reindex(columns=cols).fillna(0.0)
    bars_per_bucket = daily[daily["n"] == 6].groupby("bucket")["date"].nunique()
    dec_days = pd.Series(
        {b: sum(1 for dd in sel_dates if vr_bucket(float(vol_ratio_series.get(dd, np.nan))) == b) for b in bpiv.index}
    )

    order = [b for b in ["<0.75", "0.75–0.90", "0.90–1.00", "off (≥1.00)", "n/a"] if b in bpiv.index]
    hdr = f"{'vol-ratio bucket':<16}{'bars':>5}{'dec.d':>6}"
    hdr += "".join(f"{n:>8}" for n in SIZES) + f"{BASELINE_SIZE:>9}   best-shadow"
    print(hdr)
    print("─" * len(hdr))
    for b in order:
        row = bpiv.loc[b]
        best = row[SIZES].idxmax()
        flag = "yes" if row[best] > row[BASELINE_SIZE] else "NO"
        print(
            f"{b:<16}{int(bars_per_bucket.get(b, 0)):>5}{int(dec_days.get(b, 0)):>6}"
            + "".join(f"{row[n]:>+8.0f}" for n in SIZES)
            + f"{row[BASELINE_SIZE]:>+9.0f}"
            + f"   N={best} ({flag} vs R4)"
        )

    # Sanity: recomputed vol-ratio vs the recorded gate on decision days.
    diffs = [
        abs(float(vol_ratio_series.get(dd, np.nan)) - float(sel[dd].get("regime", {}).get("vol_ratio", np.nan)))
        for dd in sel_dates
    ]
    diffs = [x for x in diffs if np.isfinite(x)]
    if diffs:
        print(
            f"\nsanity: recomputed vs recorded vol_ratio on {len(diffs)}/{len(sel_dates)} decision days: "
            f"max |Δ| {max(diffs):.2e}, mean |Δ| {np.mean(diffs):.2e}"
        )

    # ── Section 2: churn attribution ──────────────────────────────────────
    print("\n" + "█" * 78)
    print("2. CHURN ATTRIBUTION  (10 bps/side rotation cost by symbol)")
    print("█" * 78)
    for n in (6, 7, 8, BASELINE_SIZE):
        rows = sorted(((s, c, t) for (k, s), (c, t) in churn.items() if k == n), key=lambda x: -x[1])
        total_cost = sum(c for _s, c, _t in rows)
        top = rows[:5]
        tops = ", ".join(f"{s} {100 * c / total_cost:.0f}% ({c:.0f})" for s, c, _t in top)
        holds = [(p["exit"] - p["entry"]).days for p in all_positions[n]]
        med_hold = int(np.median(holds)) if holds else 0
        print(
            f"  size {n:>2}: rotation cost {total_cost:>7.0f} over {len(rows)} symbols rotated | "
            f"median hold {med_hold:>3}d | top-5: {tops}"
        )

    # ── Section 3: per-symbol P&L for N=6 ─────────────────────────────────
    print("\n" + "█" * 78)
    print("3. PER-SYMBOL GROSS P&L — N=6 CHAIN")
    print("█" * 78)
    by_sym = defaultdict(lambda: [0.0, 0, 0])
    for p in positions[6]:
        by_sym[p["sym"]][0] += p["pnl"]
        by_sym[p["sym"]][1] += 1
        by_sym[p["sym"]][2] += 1 if p["pnl"] > 0 else 0
    ranked = sorted(by_sym.items(), key=lambda kv: -kv[1][0])
    total_gross = sum(v[0] for v in by_sym.values())
    print(f"{'symbol':<10}{'gross pnl':>11}{'trades':>8}{'win%':>7}{'class':>10}{'share':>8}")
    for s, (pnl, ntr, nw) in ranked:
        print(
            f"{s:<10}{pnl:>+11.1f}{ntr:>8}{100 * nw / ntr:>6.0f}%{asset_classes.get(s, '?'):>10}{100 * pnl / total_gross:>7.1f}%"
        )
    top3 = sum(v[0] for _s, v in ranked[:3])
    print(f"\ntotal gross {total_gross:+.1f}; top-3 symbols contribute {100 * top3 / total_gross:.0f}% of it")
    neg = sum(v[0] for _s, v in ranked if v[0] < 0)
    print(f"detractors: {sum(1 for _s, v in ranked if v[0] < 0)} symbols, {neg:+.1f} combined")

    # Cross-check vs the recommended-portfolio outcomes (different book, same signal).
    outcomes_path = REPO / "reports/r4_loop/shadow_portfolio_outcomes.jsonl"
    if outcomes_path.exists():
        o_recs = []
        with open(outcomes_path) as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        r = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if WINDOW[0] <= str(r.get("signal_date", "")) <= WINDOW[1]:
                        o_recs.append(r)
        seen, o_dedup = set(), []
        for r in o_recs:
            key = (r["cycle_id"], r["symbol"], r["entry_close_time"], r["exit_time"])
            if key not in seen:
                seen.add(key)
                o_dedup.append(r)
        o_sym = defaultdict(list)
        for r in o_dedup:
            if r.get("shadow_r") is not None:
                o_sym[r["symbol"]].append(r["shadow_r"])
        print("\ncross-check — avg shadow_r per symbol (recommended book, deduped outcomes):")
        line = []
        for s, _v in ranked[:8]:
            rs = o_sym.get(s, [])
            line.append(f"{s} {np.mean(rs):+.3f} (n={len(rs)})" if rs else f"{s} n/a")
        print("  " + " | ".join(line))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
