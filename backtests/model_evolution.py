"""Model evolution tracking — trajectory management for model assessment scoring."""

import json
from datetime import datetime, timezone

import numpy as np
from pathlib import Path

EVOLUTION_DIR = Path(__file__).resolve().parent.parent / "data" / "sandbox" / "evolution"


def compute_mas_velocity(trajectory, window=None):
    """Compute MAS velocity (first difference) from trajectory list.

    Args:
        trajectory: list of dicts with 'mas' key
        window: optional smoothing window size

    Returns:
        list of velocity values (len = max(0, len(traj) - 1))
    """
    if len(trajectory) < 2:
        return []

    mas_values = [t["mas"] for t in trajectory]
    velocities = [mas_values[i] - mas_values[i - 1] for i in range(1, len(mas_values))]

    if window is not None and len(velocities) > 0:
        smoothed = []
        for i in range(len(velocities)):
            lo = max(0, i - window + 1)
            smoothed.append(float(np.mean(velocities[lo : i + 1])))
        return smoothed

    return velocities


def compute_mas_acceleration(trajectory, window=None):
    """Compute MAS acceleration (second difference)."""
    velocities = compute_mas_velocity(trajectory, window=None)
    if len(velocities) < 2:
        return []

    accelerations = [velocities[i] - velocities[i - 1] for i in range(1, len(velocities))]

    if window is not None and len(accelerations) > 0:
        smoothed = []
        for i in range(len(accelerations)):
            lo = max(0, i - window + 1)
            smoothed.append(float(np.mean(accelerations[lo : i + 1])))
        return smoothed

    return accelerations


def compute_subaxis_drift(trajectory, window=5):
    """Compute drift for each sub-axis (sub_scores) over a window."""
    if len(trajectory) < 2:
        return {}

    # Collect all sub-axis keys
    all_keys = set()
    for t in trajectory:
        all_keys.update(t.get("sub_scores", {}).keys())

    if not all_keys:
        return {}

    drift = {}
    for key in all_keys:
        values = [t.get("sub_scores", {}).get(key, 0.0) for t in trajectory]
        if len(values) < 2:
            continue
        current = values[-1]
        previous = values[-window] if window is not None and len(values) > window else values[0]
        drift[key] = round(current - previous, 4)

    return drift


def compute_convergence(asset_trajectories):
    """Compute convergence metrics across assets.

    Calculates the cross-sectional variance and mean of the latest MAS
    values, tracks the variance timeline, and determines whether the
    portfolio is converging, diverging, or stable.

    Args:
        asset_trajectories: dict mapping asset name to list of trajectory
            entries (each entry is a dict with "mas" key).

    Returns:
        dict with keys: current_variance, current_mean,
        convergence_direction ("converging" | "diverging" | "stable" |
        "insufficient_data"), asset_spread, variance_timeline.
    """
    if not asset_trajectories:
        return {
            "current_variance": 0.0,
            "current_mean": 0.0,
            "convergence_direction": "insufficient_data",
            "asset_spread": {},
        }

    # Get latest MAS per asset
    latest = {}
    for asset, traj in asset_trajectories.items():
        if traj:
            latest[asset] = traj[-1]["mas"]

    if len(latest) < 2:
        return {
            "current_variance": 0.0,
            "current_mean": 0.0,
            "convergence_direction": "insufficient_data",
            "asset_spread": {k: 0.0 for k in latest},
        }

    values = np.array(list(latest.values()))
    mean = float(np.mean(values))
    variance = float(np.var(values, ddof=1))

    asset_spread = {asset: round(val - mean, 4) for asset, val in latest.items()}

    # Variance timeline check
    var_timeline = []
    if len(asset_trajectories) > 0:
        max_len = max(len(t) for t in asset_trajectories.values())
        if max_len >= 2:
            for i in range(max_len):
                i_vals = []
                for traj in asset_trajectories.values():
                    if i < len(traj):
                        i_vals.append(traj[i]["mas"])
                if len(i_vals) >= 2:
                    var_timeline.append(float(np.var(i_vals, ddof=1)))

            if len(var_timeline) >= 2:
                if var_timeline[-1] < var_timeline[0] * 0.9:
                    direction = "converging"
                elif var_timeline[-1] > var_timeline[0] * 1.1:
                    direction = "diverging"
                else:
                    direction = "stable"
            else:
                direction = "insufficient_data"
        else:
            direction = "insufficient_data"
    else:
        direction = "insufficient_data"

    return {
        "current_variance": variance,
        "current_mean": mean,
        "convergence_direction": direction,
        "asset_spread": asset_spread,
        "variance_timeline": var_timeline,
    }


def estimate_equilibrium_band(trajectory, window=10):
    """Estimate equilibrium band from recent trajectory values.

    Computes the mean and std of MAS values over the most recent
    ``window`` entries. The band is considered stable if std < 5.0.

    Args:
        trajectory: list of dicts with "mas" key.
        window: Number of recent entries to analyze (default 10).

    Returns:
        dict with keys: mean (float or None), std (float or None),
        stable (bool), n_recent (int).
    """
    if len(trajectory) < window:
        return {
            "mean": None,
            "std": None,
            "stable": False,
            "n_recent": len(trajectory),
        }

    recent = trajectory[-window:]
    values = np.array([t["mas"] for t in recent])
    mean = float(np.mean(values))
    std = float(np.std(values, ddof=1))

    return {
        "mean": mean,
        "std": std,
        "stable": std < 5.0,  # Within ±5 MAS points
        "n_recent": window,
    }


def append_trajectory(asset, mas, delta_mas, decision, sub_scores, forward_result):
    """Append a new entry to the asset's trajectory file."""

    evo_dir = EVOLUTION_DIR
    Path(evo_dir).mkdir(parents=True, exist_ok=True)

    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "mas": mas,
        "delta_mas": delta_mas,
        "decision": decision,
        "sub_scores": sub_scores,
        "forward_result": forward_result,
    }

    fpath = Path(evo_dir) / f"{asset}.json"
    try:
        if Path(fpath).exists():
            with open(fpath) as f:
                data = json.load(f)
        else:
            data = []
    except (json.JSONDecodeError, OSError):
        data = []

    data.append(entry)
    with open(fpath, "w") as f:
        json.dump(data, f, indent=2)

    return entry


def load_trajectory(asset, max_entries=None):
    """Load trajectory entries for an asset."""
    fpath = Path(EVOLUTION_DIR) / f"{asset}.json"
    if not Path(fpath).exists():
        return []

    try:
        with open(fpath) as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError):
        return []

    if max_entries is not None and max_entries > 0:
        data = data[-max_entries:]
    return data


def load_all_trajectories():
    """Load all asset trajectories from the evolution directory."""
    if not Path(EVOLUTION_DIR).is_dir():
        return {}

    trajectories = {}
    for fname in sorted(sorted(Path(EVOLUTION_DIR).iterdir())):
        if fname.suffix == ".json":
            asset = str(fname.stem)  # remove .json
            trajectories[asset] = load_trajectory(asset)
    return trajectories


def print_equilibrium_report(*args, **kwargs):
    """Print equilibrium report. Placeholder."""
    pass
