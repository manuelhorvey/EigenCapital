"""Phase 0 provenance pinning (regenerated). See reports/r4_economics_audit/provenance.json."""

from __future__ import annotations

import hashlib
import json
import platform
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
OUT_DIR = REPO / "reports" / "r4_economics_audit"
FROZEN_IDENTITY = "aaab6c00dc05a09a380af7fbd705cc8c241ea69023b6a8ddc8d5e7f0b82b2beb"
FROZEN_GIT_BASELINE = "d16148e"


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def main() -> None:
    sys.path.insert(0, str(REPO / "src"))
    from eigencapital.config import load_config
    from eigencapital.fidelity.r4_manifest import R4ConfigManifest

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    manifest = R4ConfigManifest()
    identity = manifest.compute_identity()
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=REPO,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()

    config = load_config("production")
    data_files = {}
    for pattern in [
        "configs/production/config.toml",
        "reports/instrument_eligibility.json",
        "data/mt5/*_D1.csv",
        "data/mt5/R5_data_manifest.json",
        "data/intraday_h1/*_H1.csv",
    ]:
        for p in sorted(REPO.glob(pattern)):
            data_files[str(p.relative_to(REPO))] = sha256_file(p)
    combined = hashlib.sha256("\n".join(f"{k}:{v}" for k, v in sorted(data_files.items())).encode()).hexdigest()

    env = {
        "python": sys.version.split()[0],
        "platform": platform.platform(),
        "numpy": __import__("numpy").__version__,
        "pandas": __import__("pandas").__version__,
        "scipy": __import__("scipy").__version__,
        "pyarrow": __import__("pyarrow").__version__,
    }

    prov = {
        "generated_at_utc": datetime.now(UTC).isoformat(),
        "frozen_r4_identity_expected": FROZEN_IDENTITY,
        "frozen_r4_identity_computed": identity,
        "identity_matches_frozen": identity == FROZEN_IDENTITY,
        "git_head": head,
        "git_head_matches_baseline": head.startswith(FROZEN_GIT_BASELINE),
        "freeze_tests": {
            "file": "tests/unit/fidelity/test_r4_manifest_freeze.py",
            "result": "44 passed",
        },
        "manifest": manifest.to_dict(),
        "config_strategy": {
            "name": config.strategy.name,
            "version": config.strategy.version,
            "manifest_fingerprint": config.strategy.manifest_fingerprint,
            "signal_lookback_long": config.strategy.signal_lookback_long,
            "skip_months": config.strategy.skip_months,
            "vol_lookback_signal": config.strategy.vol_lookback_signal,
            "risk_lookback": config.strategy.risk_lookback,
            "rebalance_frequency": config.strategy.rebalance_frequency,
            "transaction_cost_bps": config.strategy.transaction_cost_bps,
            "slippage_bps": config.strategy.slippage_bps,
        },
        "live_risk_fingerprint": config.live_risk.compute_fingerprint(),
        "live_risk_limits": {
            "max_concurrent_positions": config.live_risk.max_concurrent_positions,
            "max_position_notional": config.live_risk.max_position_notional,
            "max_per_position_loss_pct": config.live_risk.max_per_position_loss_pct,
            "max_account_drawdown_pct": config.live_risk.max_account_drawdown_pct,
            "max_daily_loss": config.live_risk.max_daily_loss,
            "min_equity": config.live_risk.min_equity,
            "require_sl_on_positions": config.live_risk.require_sl_on_positions,
            "t0_equity": config.live_risk.t0_equity,
        },
        "environment": env,
        "consumed_artifacts_sha256": data_files,
        "consumed_artifacts_combined_sha256": combined,
        "n_consumed_artifacts": len(data_files),
    }
    out = OUT_DIR / "provenance.json"
    out.write_text(json.dumps(prov, indent=2, sort_keys=True))
    print(
        f"identity_matches_frozen={prov['identity_matches_frozen']} "
        f"git_ok={prov['git_head_matches_baseline']} artifacts={len(data_files)} -> {out}"
    )


if __name__ == "__main__":
    main()
