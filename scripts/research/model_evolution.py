import json
import logging
import os
from datetime import datetime

import numpy as np

logger = logging.getLogger("eigencapital.model_evolution")

BASE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "sandbox")
EVOLUTION_DIR = os.path.join(BASE, "evolution")


def _ensure_dir(asset: str):
    d = os.path.join(EVOLUTION_DIR, asset)
    os.makedirs(d, exist_ok=True)
    return d


def append_trajectory(
    asset: str,
    mas: float,
    delta_mas: float,
    decision: str,
    sub_scores: dict,
    forward_result: dict,
    model_id: str | None = None,
):
    _ensure_dir(asset)
    entry = {
        "timestamp": datetime.now().isoformat(),
        "model_id": model_id or f"{asset}_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
        "mas": round(mas, 2),
        "delta_mas": round(delta_mas, 2),
        "decision": decision,
        "sub_scores": {k: round(v, 4) for k, v in (sub_scores or {}).items()},
        "forward_metrics": {
            "sharpe_baseline": forward_result.get("baseline", {}).get("sharpe"),
            "sharpe_new": forward_result.get("new", {}).get("sharpe"),
            "hit_rate_baseline": forward_result.get("baseline", {}).get("hit_rate"),
            "hit_rate_new": forward_result.get("new", {}).get("hit_rate"),
            "stability_baseline": forward_result.get("baseline", {}).get("stability"),
            "stability_new": forward_result.get("new", {}).get("stability"),
        },
        "regime_metrics": {
            "baseline": forward_result.get("baseline_regime"),
            "new": forward_result.get("new_regime"),
        },
    }
    path = os.path.join(EVOLUTION_DIR, asset, "trajectory.jsonl")
    with open(path, "a") as f:
        f.write(json.dumps(entry, default=str) + "\n")
    return entry


def load_trajectory(asset: str, max_entries: int | None = None) -> list[dict]:
    path = os.path.join(EVOLUTION_DIR, asset, "trajectory.jsonl")
    if not os.path.exists(path):
        return []
    entries = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line:
                entries.append(json.loads(line))
    if max_entries and len(entries) > max_entries:
        entries = entries[-max_entries:]
    return entries


def load_all_trajectories() -> dict[str, list[dict]]:
    if not os.path.exists(EVOLUTION_DIR):
        return {}
    result = {}
    for asset_dir in sorted(os.listdir(EVOLUTION_DIR)):
        traj_path = os.path.join(EVOLUTION_DIR, asset_dir, "trajectory.jsonl")
        if os.path.isfile(traj_path):
            result[asset_dir] = load_trajectory(asset_dir)
    return result


def compute_mas_velocity(trajectory: list[dict], window: int = 3) -> list[float]:
    if len(trajectory) < 2:
        return []
    mas_vals = [e["mas"] for e in trajectory]
    velocities = []
    for i in range(1, len(mas_vals)):
        velocities.append(mas_vals[i] - mas_vals[i - 1])
    if window and len(velocities) > window:
        smoothed = []
        for i in range(len(velocities)):
            lo = max(0, i - window + 1)
            smoothed.append(sum(velocities[lo : i + 1]) / (i - lo + 1))
        return smoothed
    return velocities


def compute_mas_acceleration(trajectory: list[dict], window: int = 3) -> list[float]:
    velocities = compute_mas_velocity(trajectory, window=window)
    if len(velocities) < 2:
        return []
    accelerations = []
    for i in range(1, len(velocities)):
        accelerations.append(velocities[i] - velocities[i - 1])
    return accelerations


def compute_subaxis_drift(trajectory: list[dict], window: int = 3) -> dict[str, float]:
    if len(trajectory) < 2:
        return {}
    axes = list(trajectory[0].get("sub_scores", {}).keys())
    drifts = {}
    for axis in axes:
        vals = [e.get("sub_scores", {}).get(axis, 0) for e in trajectory[-window:]]
        if len(vals) >= 2:
            drifts[axis] = round(vals[-1] - vals[0], 4)
        else:
            drifts[axis] = 0.0
    return drifts


def compute_convergence(all_trajectories: dict[str, list[dict]]) -> dict:
    result = {"variance_across_assets": {}, "convergence_trend": {}}
    recent_mas = {}
    for asset, traj in all_trajectories.items():
        if traj:
            recent_mas[asset] = traj[-1]["mas"]
    if len(recent_mas) >= 2:
        mas_vals = list(recent_mas.values())
        result["current_variance"] = round(float(np.var(mas_vals)), 4)
        result["current_std"] = round(float(np.std(mas_vals)), 4)
        result["current_mean"] = round(float(np.mean(mas_vals)), 2)
        result["asset_spread"] = {k: round(v - result["current_mean"], 2) for k, v in recent_mas.items()}
    else:
        result["current_variance"] = 0.0
        result["current_std"] = 0.0
        result["current_mean"] = 0.0
        result["asset_spread"] = {}

    variance_over_time = {}
    min_len = min(len(t) for t in all_trajectories.values()) if all_trajectories else 0
    if min_len >= 2:
        for i in range(min_len):
            mas_at_step = [t[i]["mas"] for t in all_trajectories.values() if len(t) > i]
            if len(mas_at_step) >= 2:
                variance_over_time[f"step_{i}"] = round(float(np.var(mas_at_step)), 4)
    result["variance_timeline"] = variance_over_time
    if variance_over_time:
        v_vals = list(variance_over_time.values())
        result["convergence_direction"] = (
            "converging"
            if len(v_vals) >= 2 and v_vals[-1] < v_vals[0]
            else "diverging"
            if len(v_vals) >= 2
            else "stable"
        )  # noqa: E501
    else:
        result["convergence_direction"] = "insufficient_data"

    return result


def estimate_equilibrium_band(trajectory: list[dict], window: int = 10) -> dict:
    if len(trajectory) < 3:
        return {"mean": None, "std": None, "lower": None, "upper": None, "stable": False}
    mas_vals = [e["mas"] for e in trajectory[-window:]]
    mu = float(np.mean(mas_vals))
    sigma = float(np.std(mas_vals))
    return {
        "mean": round(mu, 2),
        "std": round(sigma, 4),
        "lower": round(mu - sigma, 2),
        "upper": round(mu + sigma, 2),
        "stable": sigma < 2.0,
    }


def compute_system_evolution() -> dict:
    all_traj = load_all_trajectories()
    result = {
        "timestamp": datetime.now().isoformat(),
        "n_assets": len(all_traj),
        "total_runs": sum(len(t) for t in all_traj.values()),
        "assets": {},
        "system": {},
    }
    for asset, traj in all_traj.items():
        if not traj:
            continue
        latest = traj[-1]
        velocities = compute_mas_velocity(traj, window=3)
        accelerations = compute_mas_acceleration(traj, window=3)
        drift = compute_subaxis_drift(traj, window=3)
        equilibrium = estimate_equilibrium_band(traj, window=10)
        result["assets"][asset] = {
            "n_runs": len(traj),
            "latest_mas": latest["mas"],
            "latest_delta_mas": latest["delta_mas"],
            "latest_decision": latest["decision"],
            "latest_sub_scores": latest.get("sub_scores"),
            "velocity_latest": velocities[-1] if velocities else None,
            "velocity_mean": round(float(np.mean(velocities)), 4) if velocities else None,
            "velocity_std": round(float(np.std(velocities)), 4) if velocities else None,
            "acceleration_latest": accelerations[-1] if accelerations else None,
            "subaxis_drift": drift,
            "equilibrium": equilibrium,
        }
    convergence = compute_convergence(all_traj)
    result["system"] = convergence
    path = os.path.join(EVOLUTION_DIR, "system_evolution.json")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        json.dump(result, f, indent=2, default=str)
    return result


def print_equilibrium_report():
    system = compute_system_evolution()
    print("\n" + "=" * 80)
    print("MODEL EVOLUTION REPORT")
    print("=" * 80)
    print(f"Assets tracked: {system['n_assets']}  |  Total retrain runs: {system['total_runs']}")
    print()
    for asset, info in sorted(system["assets"].items()):
        eq = info.get("equilibrium", {})
        eq_str = f"band [{eq.get('lower', '?')}, {eq.get('upper', '?')}]" if eq.get("mean") else "N/A"
        vel = info.get("velocity_latest")
        vel_str = f"{vel:+.4f}" if vel is not None else "N/A"
        print(
            f"  {asset:10s}  MAS={info['latest_mas']:6.2f}  ∇={vel_str:>8s}  "
            f"decision={info['latest_decision']:16s}  eq={eq_str}"
        )
    conv = system.get("system", {})
    print(
        f"\n  Cross-asset variance: {conv.get('current_variance', 'N/A')}  "
        f"std={conv.get('current_std', 'N/A')}  "
        f"direction={conv.get('convergence_direction', 'N/A')}"
    )
    print("=" * 80)
    return system
