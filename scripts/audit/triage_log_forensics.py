"""Phase 1 log forensics (regenerated). Output: triage_log_forensics.json"""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
LOOP = REPO / "reports" / "r4_loop"
OUT = REPO / "reports" / "r4_economics_audit"


def parse_jsonl(path: Path) -> list[dict]:
    records: list[dict] = []
    if not path.exists():
        return records
    for i, line in enumerate(path.read_text().splitlines()):
        line = line.strip()
        if not line:
            continue
        try:
            records.append(json.loads(line))
        except json.JSONDecodeError:
            records.append({"_unparseable": True, "_line_no": i})
    return records


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    result: dict = {}

    decisions = [r for r in parse_jsonl(LOOP / "decisions.jsonl") if not r.get("_unparseable")]
    dec_events = Counter(r.get("event", "?") for r in decisions)
    eq_series = [
        {
            "ts": r.get("timestamp"),
            "equity_before": r.get("equity_before"),
            "equity_after": r.get("equity_after"),
            "filled": r.get("filled"),
            "submitted": r.get("submitted"),
        }
        for r in decisions
        if r.get("event") == "executed"
    ]
    result["decisions"] = {
        "n_records": len(decisions),
        "event_counts": dict(dec_events),
        "first_ts": decisions[0].get("timestamp") if decisions else None,
        "last_ts": decisions[-1].get("timestamp") if decisions else None,
        "executed_equity_series": eq_series,
        "zero_equity_reads": [e for e in eq_series if e["equity_after"] == 0],
    }

    monitor = [r for r in parse_jsonl(LOOP / "monitor.jsonl") if not r.get("_unparseable")]
    titles = Counter(r.get("title", "?") for r in monitor)
    uniq = {t: len({r.get("body", "") for r in monitor if r.get("title") == t}) for t in titles}
    eq_changes = []
    for r in monitor:
        if r.get("title") == "EQUITY CHANGE" and "→" in r.get("body", ""):
            try:
                b = r["body"]
                frm = float(b.split("$")[1].split()[0].replace(",", ""))
                to = float(b.split("$")[2].split()[0].replace(",", ""))
                eq_changes.append({"ts": r["timestamp"], "from": frm, "to": to})
            except (IndexError, ValueError):
                pass
    vals = [c["to"] for c in eq_changes]
    result["monitor"] = {
        "n_records": len(monitor),
        "title_counts": dict(titles),
        "unique_bodies_per_title": uniq,
        "amplification_ratio": {t: round(titles[t] / u, 1) if u else None for t, u in uniq.items()},
        "first_ts": monitor[0].get("timestamp") if monitor else None,
        "last_ts": monitor[-1].get("timestamp") if monitor else None,
        "equity_change_series_count": len(eq_changes),
        "equity_min": min(vals) if vals else None,
        "equity_max": max(vals) if vals else None,
    }

    lp_path = LOOP / "last_positions.json"
    if lp_path.exists():
        lp = json.loads(lp_path.read_text())
        bot = [p for p in lp.values() if p.get("magic") == 20260825]
        man = [p for p in lp.values() if p.get("magic") != 20260825]
        result["last_positions"] = {
            "n_total": len(lp),
            "n_bot": len(bot),
            "n_manual_magic_0": len(man),
            "manual_symbols": sorted({p["symbol"] for p in man}),
            "bot_unrealized_pnl": round(sum(p.get("profit", 0) for p in bot), 2),
            "manual_unrealized_pnl": round(sum(p.get("profit", 0) for p in man), 2),
            "any_sl_set": any(p.get("sl", 0) != 0 for p in lp.values()),
            "any_tp_set": any(p.get("tp", 0) != 0 for p in lp.values()),
        }

    out = OUT / "triage_log_forensics.json"
    out.write_text(json.dumps(result, indent=2, default=str))
    print(f"wrote {out}: titles={dict(titles)}")


if __name__ == "__main__":
    main()
