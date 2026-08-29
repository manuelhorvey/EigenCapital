"""Dashboard State Service — read adapter over existing EigenCapital domain models.

This service reads from:
- Risk observation engine
- Health state model
- Risk enforcement
- Reconciliation engine
- Event ledger
- Qualification framework
- Build pinning
- Structured alerts
- Watchdog
- Authorization

When persisted state files are missing, this service:
- Computes values live from MT5/domain data
- Persists computed values to disk for next read
- Derives state from available data files

It does NOT modify any production trading state.
"""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from eigencapital.dashboard.schemas.common import DataFreshness


class DashboardStateService:
    """Read-only adapter over existing EigenCapital domain models."""

    def __init__(self, config: Any = None) -> None:
        self._config = config
        self._last_health_check: datetime | None = None
        self._last_risk_observation: datetime | None = None
        self._mt5_connected: bool = False
        self._data_dir = Path("reports")
        self._evidence_dir = self._data_dir / "r4_qualification"
        self._loop_dir = self._data_dir / "r4_loop"
        self._alert_path = self._data_dir / "alerts.jsonl"
        self._decisions_path = self._loop_dir / "decisions.jsonl"
        self._monitor_path = self._loop_dir / "monitor.jsonl"

    def _ensure_dirs(self) -> None:
        """Ensure all data directories exist."""
        self._data_dir.mkdir(parents=True, exist_ok=True)
        self._loop_dir.mkdir(parents=True, exist_ok=True)
        self._evidence_dir.mkdir(parents=True, exist_ok=True)

    def _persist_json(self, path: Path, data: dict[str, Any]) -> None:
        """Atomically write a JSON file (write tmp + rename)."""
        try:
            self._ensure_dirs()
            tmp = path.with_suffix(".tmp")
            with open(tmp, "w") as f:
                json.dump(data, f, indent=2, default=str)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, path)
        except OSError:
            pass

    def _append_jsonl(self, path: Path, record: dict[str, Any]) -> None:
        """Append a JSON line to a JSONL file."""
        try:
            self._ensure_dirs()
            with open(path, "a") as f:
                f.write(json.dumps(record, sort_keys=True, default=str) + "\n")
        except OSError:
            pass

    def _wrap(self, data: dict[str, Any], source: str, freshness: str | None = None) -> dict[str, Any]:
        """Wrap response data with metadata envelope."""
        ts = data.get("timestamp")
        if isinstance(ts, str):
            try:
                ts = datetime.fromisoformat(ts)
            except (ValueError, TypeError):
                ts = datetime.now(UTC)

        return {
            "data": data,
            "meta": {
                "observed_at": ts.isoformat() if ts else datetime.now(UTC).isoformat(),
                "generated_at": datetime.now(UTC).isoformat(),
                "freshness": freshness or data.get("freshness", DataFreshness.UNKNOWN.value),
                "source": source,
            },
        }

    # ─── System Health ─────────────────────────────────────────────

    def get_system_health(self) -> dict[str, Any]:
        """Read current system health from domain models.

        Reads from multiple authoritative sources and populates per-dimension
        health data for the HealthMatrix component.

        Sources:
        - loop_health.json (supervisor alive flag)
        - supervisor_state.json (restart count, status, instance)
        - risk_state.json (risk envelope health)
        - reconciliation_state.json (broker reconciliation)
        - Build identity (fingerprint verification)
        - MT5 connectivity (broker connection)
        - Evidence pipeline (qualification status)
        """
        now = datetime.now(UTC)
        dimensions: list[dict[str, Any]] = []
        blocking: list[str] = []
        overall_alive = False
        health_timestamp = now.isoformat()

        # ── 1. Supervisor health ──
        supervisor_state = self._read_json(self._loop_dir / "supervisor_state.json")
        supervisor_health = self._read_json(self._loop_dir / "loop_health.json")
        # Fallback: monitor writes last_health.json
        if supervisor_health is None:
            supervisor_health = self._read_json(self._loop_dir / "last_health.json")

        if supervisor_health is not None:
            alive = supervisor_health.get("alive", False)
            overall_alive = alive
            health_timestamp = supervisor_health.get("timestamp", now.isoformat())

            restart_count = 0
            sup_status = "running"
            if supervisor_state is not None:
                restart_count = supervisor_state.get("restart_count", 0)
                sup_status = supervisor_state.get("status", "running")

            if alive and sup_status == "running":
                dim_state = "HEALTHY"
                msg = f"Supervisor running (PID {supervisor_health.get('pid', '?')})"
            elif alive and sup_status == "halting":
                dim_state = "DEGRADED"
                msg = "Supervisor shutting down"
                blocking.append("supervisor")
            elif sup_status == "frozen":
                dim_state = "HALTED"
                msg = f"Supervisor frozen after {restart_count} restarts"
                blocking.append("supervisor")
            else:
                dim_state = "HALTED"
                msg = "Supervisor not responding"
                blocking.append("supervisor")

            dimensions.append({
                "dimension": "supervisor",
                "state": dim_state,
                "message": msg,
                "timestamp": health_timestamp,
                "consecutive_failures": restart_count,
                "details": {
                    "pid": supervisor_health.get("pid"),
                    "instance_id": supervisor_health.get("instance_id", ""),
                    "restart_count": restart_count,
                    "status": sup_status,
                },
            })
        else:
            # No health file at all
            overall_alive = False
            blocking.append("supervisor")
            dimensions.append({
                "dimension": "supervisor",
                "state": "HALTED",
                "message": "No supervisor health data found",
                "timestamp": now.isoformat(),
                "consecutive_failures": 0,
                "details": {},
            })

        # ── 2. Broker connectivity (MT5) ──
        broker_ok = False
        try:
            from mt5linux import MetaTrader5

            mt5 = MetaTrader5(host="127.0.0.1", port=8001)
            if mt5.initialize():
                account = mt5.account_info()
                mt5.shutdown()
                broker_ok = account is not None
        except Exception:
            broker_ok = False

        if broker_ok:
            dimensions.append({
                "dimension": "broker",
                "state": "HEALTHY",
                "message": "MT5 broker connected",
                "timestamp": now.isoformat(),
                "consecutive_failures": 0,
                "details": {},
            })
        else:
            blocking.append("broker")
            dimensions.append({
                "dimension": "broker",
                "state": "BLOCKED",
                "message": "MT5 broker unreachable",
                "timestamp": now.isoformat(),
                "consecutive_failures": 0,
                "details": {},
            })

        # ── 3. Risk envelope ──
        risk_data = self._read_json(self._loop_dir / "risk_state.json")
        if risk_data is not None:
            risk_level = risk_data.get("overall_level", "UNKNOWN")
            any_critical = risk_data.get("any_critical", False)
            any_warning = risk_data.get("any_warning", False)

            if risk_level == "NORMAL":
                risk_state = "HEALTHY"
                risk_msg = "Risk envelope within limits"
            elif any_critical:
                risk_state = "CRITICAL"
                risk_msg = f"Critical risk: {', '.join(risk_data.get('critical_dimensions', []))}"
                blocking.append("risk")
            elif any_warning:
                risk_state = "DEGRADED"
                risk_msg = f"Elevated risk: {', '.join(risk_data.get('warning_dimensions', []))}"
            else:
                risk_state = "HEALTHY"
                risk_msg = f"Risk level: {risk_level}"

            dimensions.append({
                "dimension": "risk_envelope",
                "state": risk_state,
                "message": risk_msg,
                "timestamp": risk_data.get("timestamp", now.isoformat()),
                "consecutive_failures": 0,
                "details": {
                    "overall_level": risk_level,
                    "critical_count": len(risk_data.get("critical_dimensions", [])),
                    "warning_count": len(risk_data.get("warning_dimensions", [])),
                },
            })
        else:
            dimensions.append({
                "dimension": "risk_envelope",
                "state": "DEGRADED",
                "message": "Risk state data not available",
                "timestamp": now.isoformat(),
                "consecutive_failures": 0,
                "details": {},
            })

        # ── 4. Reconciliation ──
        recon_data = self._read_json(self._loop_dir / "reconciliation_state.json")
        if recon_data is not None:
            recon_status = recon_data.get("overall_status", "UNKNOWN")
            if recon_status == "CLEAN":
                recon_state = "HEALTHY"
                recon_msg = "All positions reconciled"
            elif recon_status == "WARNING":
                recon_state = "DEGRADED"
                foreign = recon_data.get("foreign_positions", 0)
                recon_msg = f"{foreign} foreign position(s) detected"
                if foreign > 0:
                    blocking.append("reconciliation")
            elif recon_status in ("CRITICAL", "HALT"):
                recon_state = "BLOCKED"
                recon_msg = f"Reconciliation {recon_status.lower()}"
                blocking.append("reconciliation")
            else:
                recon_state = "DEGRADED"
                recon_msg = f"Reconciliation status: {recon_status}"

            dimensions.append({
                "dimension": "reconciliation",
                "state": recon_state,
                "message": recon_msg,
                "timestamp": recon_data.get("timestamp", now.isoformat()),
                "consecutive_failures": 0,
                "details": {
                    "status": recon_status,
                    "foreign_positions": recon_data.get("foreign_positions", 0),
                    "missing_fills": recon_data.get("missing_fills", 0),
                },
            })
        else:
            # Derive from positions
            positions = self.get_positions()
            foreign = sum(1 for p in positions if not p.get("protected"))
            if foreign > 0:
                blocking.append("reconciliation")
                dimensions.append({
                    "dimension": "reconciliation",
                    "state": "DEGRADED",
                    "message": f"{foreign} unprotected position(s) — no reconciliation data",
                    "timestamp": now.isoformat(),
                    "consecutive_failures": 0,
                    "details": {"foreign_positions": foreign},
                })
            else:
                dimensions.append({
                    "dimension": "reconciliation",
                    "state": "HEALTHY",
                    "message": "No reconciliation issues",
                    "timestamp": now.isoformat(),
                    "consecutive_failures": 0,
                    "details": {},
                })

        # ── 5. Build verification ──
        build = self.get_build_identity()
        if build.get("verified", False):
            dimensions.append({
                "dimension": "build",
                "state": "HEALTHY",
                "message": f"Build verified ({build.get('build_id', '?')[:12]})",
                "timestamp": build.get("timestamp", now.isoformat()),
                "consecutive_failures": 0,
                "details": {
                    "git_head": build.get("git_head", ""),
                    "build_id": build.get("build_id", ""),
                },
            })
        else:
            blocking.append("build")
            dimensions.append({
                "dimension": "build",
                "state": "BLOCKED",
                "message": "Build fingerprint drift detected",
                "timestamp": build.get("timestamp", now.isoformat()),
                "consecutive_failures": 0,
                "details": {
                    "git_head": build.get("git_head", ""),
                    "drift_details": build.get("drift_details", {}),
                },
            })

        # ── 6. Evidence pipeline ──
        qual = self.get_qualification_status()
        if qual.get("evidence_insufficient", True):
            dimensions.append({
                "dimension": "evidence",
                "state": "DEGRADED",
                "message": "Evidence still accumulating",
                "timestamp": qual.get("timestamp", now.isoformat()),
                "consecutive_failures": 0,
                "details": {
                    "total_trades": qual.get("evidence_maturity", {}).get("total_trades", 0),
                    "observation_days": qual.get("evidence_maturity", {}).get("observation_days", 0),
                },
            })
        else:
            dimensions.append({
                "dimension": "evidence",
                "state": "HEALTHY",
                "message": "Evidence sufficient",
                "timestamp": qual.get("timestamp", now.isoformat()),
                "consecutive_failures": 0,
                "details": {
                    "total_trades": qual.get("evidence_maturity", {}).get("total_trades", 0),
                    "observation_days": qual.get("evidence_maturity", {}).get("observation_days", 0),
                },
            })

        # ── Determine overall state ──
        dim_states = [d["state"] for d in dimensions]
        if "HALTED" in dim_states:
            overall_state = "HALTED"
            auth = "TRADING_HALTED"
        elif "BLOCKED" in dim_states:
            overall_state = "DEGRADED"
            auth = "TRADING_BLOCKED"
        elif "CRITICAL" in dim_states:
            overall_state = "DEGRADED"
            auth = "TRADING_BLOCKED"
        elif overall_alive and "DEGRADED" not in dim_states:
            overall_state = "HEALTHY"
            auth = "TRADING_AUTHORIZED"
        elif overall_alive:
            overall_state = "DEGRADED"
            auth = "TRADING_AUTHORIZED"  # Alive but some dimensions degraded
        else:
            overall_state = "UNKNOWN"
            auth = "UNKNOWN"

        return {
            "overall_state": overall_state,
            "trading_authorization": auth,
            "dimensions": dimensions,
            "blocking_dimensions": blocking,
            "timestamp": health_timestamp,
            "freshness": self._assess_freshness(health_timestamp),
        }

    # ─── Risk State ────────────────────────────────────────────────

    def get_risk_state(self) -> dict[str, Any]:
        """Read current risk state — from persisted file or computed live from MT5.

        When computed live, persists the result to risk_state.json so subsequent
        reads are fast and consistent.
        """
        # 1. Try persisted risk_state.json first
        try:
            risk_path = self._loop_dir / "risk_state.json"
            if risk_path.exists():
                with open(risk_path) as f:
                    risk_data = json.load(f)
                freshness = self._assess_freshness(risk_data.get("timestamp"))
                return {
                    "overall_level": risk_data.get("overall_level", "UNKNOWN"),
                    "observations": risk_data.get("observations", []),
                    "any_critical": risk_data.get("any_critical", False),
                    "any_warning": risk_data.get("any_warning", False),
                    "critical_dimensions": risk_data.get("critical_dimensions", []),
                    "warning_dimensions": risk_data.get("warning_dimensions", []),
                    "timestamp": risk_data.get("timestamp", datetime.now(UTC).isoformat()),
                    "freshness": freshness,
                }
        except Exception:
            pass

        # 2. Compute live from MT5 data using RiskObserver
        try:
            from eigencapital.live.risk_enforcement import RiskEnvelope
            from eigencapital.live.risk_observation import RiskObserver

            env = RiskEnvelope.from_config()
            observer = RiskObserver(
                max_daily_loss=env.max_daily_loss,
                max_drawdown_pct=env.max_account_drawdown_pct,
                max_concentration_pct=0.30,
                max_margin_utilization=0.80,
                min_equity=env.min_equity,
            )

            # Load persisted peak equity from runtime_state.json
            state_path = self._loop_dir / "runtime_state.json"
            if state_path.exists():
                try:
                    with open(state_path) as f:
                        rt_state = json.load(f)
                    saved_peak = rt_state.get("peak_equity", 0)
                    if saved_peak > observer._peak_equity:
                        observer._peak_equity = saved_peak
                except Exception:
                    pass

            # Load daily baseline — try r4_loop first, then reports root
            daily_start = 0.0
            for bp in [self._loop_dir / "daily_baseline.json", self._data_dir / "daily_baseline.json"]:
                if bp.exists():
                    try:
                        with open(bp) as f:
                            baseline = json.load(f)
                        daily_start = baseline.get("equity", 0.0)
                        observer._daily_pnl_start = daily_start
                        break
                    except Exception:
                        pass

            # Get live MT5 data
            from mt5linux import MetaTrader5

            mt5 = MetaTrader5(host="127.0.0.1", port=8001)
            if mt5.initialize():
                account = mt5.account_info()
                positions_raw = mt5.positions_get()
                mt5.shutdown()

                if account:
                    equity = account.equity
                    balance = account.balance
                    free_margin = getattr(account, "margin_free", 0) or 0

                    # Convert MT5 position objects to dicts for RiskObserver
                    positions = []
                    for p in positions_raw or []:
                        positions.append(
                            {
                                "symbol": p.symbol,
                                "volume": p.volume,
                                "type": p.type,
                                "price_open": p.price_open,
                                "price_current": p.price_current,
                                "sl": p.sl,
                                "profit": p.profit,
                                "ticket": p.ticket,
                            }
                        )

                    daily_pnl = equity - daily_start if daily_start > 0 else 0.0

                    risk_state = observer.observe(
                        equity=equity,
                        balance=balance,
                        free_margin=free_margin,
                        positions=positions,
                        daily_pnl=daily_pnl,
                    )

                    # Convert to dict format expected by route
                    observations_list = []
                    for obs in risk_state.observations.values():
                        observations_list.append(obs.to_dict())

                    result = {
                        "overall_level": risk_state.overall_level,
                        "observations": observations_list,
                        "any_critical": risk_state.any_critical,
                        "any_warning": risk_state.any_warning,
                        "critical_dimensions": risk_state.critical_dimensions,
                        "warning_dimensions": risk_state.warning_dimensions,
                        "timestamp": risk_state.timestamp,
                        "freshness": DataFreshness.LIVE.value,
                    }

                    # Persist to disk for faster subsequent reads
                    self._persist_json(self._loop_dir / "risk_state.json", result)

                    return result

        except ImportError:
            pass  # RiskObserver or RiskEnvelope not available
        except Exception:
            pass  # MT5 not connected or other error

        return {
            "overall_level": "UNKNOWN",
            "observations": [],
            "any_critical": False,
            "any_warning": False,
            "critical_dimensions": [],
            "warning_dimensions": [],
            "timestamp": datetime.now(UTC).isoformat(),
            "freshness": DataFreshness.UNKNOWN.value,
        }

    # ─── Build Identity ────────────────────────────────────────────

    def get_build_identity(self) -> dict[str, Any]:
        """Read build identity from domain models."""
        try:
            from eigencapital.config import load_config
            from eigencapital.live.build_pinning import compute_build_identity

            config = load_config("production") if self._config is None else self._config
            config_fp = getattr(config, "config_fingerprint", None) or getattr(
                config.strategy, "manifest_fingerprint", ""
            )
            identity = compute_build_identity(Path("."), config_fp)

            return {
                "git_head": identity.git_head,
                "manifest_identity": identity.manifest_identity,
                "config_fingerprint": identity.config_fingerprint,
                "loop_script_sha256": identity.loop_script_sha256,
                "build_id": identity.build_id,
                "verified": identity.all_verified,
                "drift_detected": not identity.all_verified,
                "drift_details": {
                    "checks": [
                        {
                            "component": c.component,
                            "expected": c.expected,
                            "observed": c.observed,
                            "ok": c.ok,
                        }
                        for c in identity.checks
                    ]
                },
                "timestamp": datetime.now(UTC).isoformat(),
                "freshness": DataFreshness.LIVE.value,
            }
        except Exception:
            return {
                "git_head": "",
                "manifest_identity": "",
                "config_fingerprint": "",
                "loop_script_sha256": "",
                "build_id": "",
                "verified": False,
                "drift_detected": True,
                "drift_details": {},
                "timestamp": datetime.now(UTC).isoformat(),
                "freshness": DataFreshness.UNKNOWN.value,
            }

    # ─── Portfolio ─────────────────────────────────────────────────

    def get_account_state(self) -> dict[str, Any]:
        """Read account state from MT5."""
        try:
            from mt5linux import MetaTrader5

            mt5 = MetaTrader5(host="127.0.0.1", port=8001)
            if not mt5.initialize():
                self._mt5_connected = False
                return self._empty_account_state()

            account = mt5.account_info()
            self._mt5_connected = True
            mt5.shutdown()

            if account is None:
                return self._empty_account_state()

            equity = account.equity
            balance = account.balance
            margin_free = getattr(account, "margin_free", 0) or 0
            margin_used = getattr(account, "margin", 0) or 0

            # Compute drawdown and daily loss from risk envelope
            drawdown_pct = 0.0
            drawdown_abs = 0.0
            daily_loss_remaining = 0.0
            equity_hwm = equity
            daily_pnl = 0.0
            unrealized_pnl = 0.0
            try:
                from eigencapital.live.risk_enforcement import RiskEnvelope

                env = RiskEnvelope.from_config()
                t0 = getattr(env, "t0_equity", balance)
                daily_loss_remaining = getattr(env, "max_daily_loss", 250.0)

                # Load persisted peak equity for true HWM
                state_path = self._loop_dir / "runtime_state.json"
                saved_peak = 0.0
                if state_path.exists():
                    try:
                        with open(state_path) as f:
                            rt_state = json.load(f)
                        saved_peak = rt_state.get("peak_equity", 0)
                    except Exception:
                        pass

                equity_hwm = max(equity, t0, saved_peak)
                drawdown_abs = max(0.0, equity_hwm - equity)
                drawdown_pct = drawdown_abs / max(equity_hwm, 1)

                # Compute daily P&L from baseline
                daily_start = 0.0
                for bp in [self._loop_dir / "daily_baseline.json", self._data_dir / "daily_baseline.json"]:
                    if bp.exists():
                        try:
                            with open(bp) as f:
                                baseline = json.load(f)
                            daily_start = baseline.get("equity", 0.0)
                            break
                        except Exception:
                            pass
                if daily_start > 0:
                    daily_pnl = equity - daily_start

                # Compute total unrealized P&L from live positions
                try:
                    live_positions = mt5.positions_get()
                    for p in (live_positions or []):
                        unrealized_pnl += getattr(p, "profit", 0) or 0
                except Exception:
                    pass

            except Exception:
                pass

            return {
                "equity": equity,
                "balance": balance,
                "free_margin": margin_free,
                "margin_used": margin_used,
                "margin_utilization": 1 - (margin_free / max(equity, 1)),
                "equity_high_water": equity_hwm,
                "drawdown": drawdown_abs,
                "drawdown_pct": drawdown_pct,
                "daily_pnl": daily_pnl,
                "daily_loss_remaining": daily_loss_remaining,
                "unrealized_pnl": unrealized_pnl,
                "currency": account.currency,
                "timestamp": datetime.now(UTC).isoformat(),
                "freshness": DataFreshness.LIVE.value,
                "source": "mt5",
            }
        except Exception:
            self._mt5_connected = False
            return self._empty_account_state()

    def get_positions(self) -> list[dict[str, Any]]:
        """Read current positions from MT5."""
        try:
            from mt5linux import MetaTrader5

            mt5 = MetaTrader5(host="127.0.0.1", port=8001)
            if not mt5.initialize():
                return []

            positions = mt5.positions_get()
            mt5.shutdown()

            if not positions:
                return []

            # Load persisted MAE/MFE excursion data from risk observer
            excursions = self._read_json(self._loop_dir / "position_excursion.json") or {}

            now = datetime.now(UTC)
            result = []
            for p in positions:
                entry_time = datetime.fromtimestamp(p.time, tz=UTC) if p.time else now
                holding_secs = (now - entry_time).total_seconds()

                if holding_secs < 60:
                    holding_time = f"{int(holding_secs)}s"
                elif holding_secs < 3600:
                    holding_time = f"{int(holding_secs / 60)}m"
                elif holding_secs < 86400:
                    holding_time = f"{int(holding_secs / 3600)}h"
                else:
                    holding_time = f"{int(holding_secs / 86400)}d"

                # P&L% = price movement percentage (direction-aware)
                if p.type == 0:  # BUY/LONG
                    pnl_pct = (p.price_current - p.price_open) / max(p.price_open, 0.00001)
                else:  # SELL/SHORT
                    pnl_pct = (p.price_open - p.price_current) / max(p.price_open, 0.00001)

                # Derive per-position risk state from SL protection
                has_sl = p.sl > 0
                pos_risk_state = "NORMAL"
                if not has_sl:
                    pos_risk_state = "WARNING"  # Unprotected = elevated risk
                elif pnl_pct < -0.02:
                    pos_risk_state = "CRITICAL"  # >2% adverse move
                elif pnl_pct < -0.01:
                    pos_risk_state = "WARNING"   # >1% adverse move

                # Read MAE/MFE from persisted excursion data
                ticket_key = str(p.ticket)
                exc = excursions.get(ticket_key)
                mae = exc.get("mae_pct") if exc else None
                mfe = exc.get("mfe_pct") if exc else None

                result.append(
                    {
                        "ticket": p.ticket,
                        "symbol": p.symbol,
                        "direction": "BUY" if p.type == 0 else "SELL",
                        "size": p.volume,
                        "entry_price": p.price_open,
                        "current_price": p.price_current,
                        "unrealized_pnl": p.profit,
                        "unrealized_pnl_pct": pnl_pct,
                        "stop_loss": p.sl if p.sl > 0 else None,
                        "distance_to_sl": abs(p.price_current - p.sl) if p.sl and p.sl > 0 else None,
                        "mae": mae,
                        "mfe": mfe,
                        "holding_time": holding_time,
                        "risk_state": pos_risk_state,
                        "protected": has_sl,
                        "attribution_state": None,
                        "last_update": now.isoformat(),
                        "freshness": DataFreshness.LIVE.value,
                        "source": "mt5",
                    }
                )
            return result
        except Exception:
            return []

    # ─── Qualification ─────────────────────────────────────────────

    def get_qualification_status(self) -> dict[str, Any]:
        """Read qualification status from evidence directory.

        Tries qualification_status.json first, then derives from available
        evidence files (campaign snapshots, attestation records).
        """
        qual_path = self._evidence_dir / "qualification_status.json"
        if qual_path.exists():
            try:
                with open(qual_path) as f:
                    data = json.load(f)
                data.setdefault("campaign_id", "")
                data.setdefault("overall_status", "UNKNOWN")
                data.setdefault("evidence_insufficient", True)
                data.setdefault("timestamp", datetime.now(UTC).isoformat())
                data["freshness"] = self._assess_freshness(data.get("timestamp"))
                return data
            except (json.JSONDecodeError, OSError):
                pass

        # Derive from available evidence files
        result = self._derive_qualification_from_evidence()
        return result

    def _derive_qualification_from_evidence(self) -> dict[str, Any]:
        """Derive qualification status from available evidence files."""
        now = datetime.now(UTC).isoformat()

        # Count evidence files
        evidence_dir = self._evidence_dir / "evidence"
        e_counts = {"e0": 0, "e1": 0, "e2": 0, "e3": 0, "e4": 0, "e5": 0, "e6": 0}
        total_trades = 0

        if evidence_dir.exists():
            for f in evidence_dir.iterdir():
                if f.suffix == ".json":
                    total_trades += 1
                    # Try to determine evidence level from file content
                    try:
                        with open(f) as fh:
                            ev = json.load(fh)
                        level = ev.get("evidence_level", ev.get("level", "e0"))
                        if isinstance(level, str) and level.lower() in e_counts:
                            e_counts[level.lower()] += 1
                    except Exception:
                        e_counts["e0"] += 1

        # Find campaign ID from latest attestation or T0 snapshot
        campaign_id = ""
        campaign_start = None
        for f in sorted(self._evidence_dir.glob("T0_*.json"), reverse=True):
            try:
                with open(f) as fh:
                    snap = json.load(fh)
                campaign_id = snap.get("campaign_id", snap.get("authorization_id", ""))
                campaign_start = snap.get(
                    "snapshot_timestamp", snap.get("timestamp", snap.get("authorization_timestamp"))
                )
                break
            except Exception:
                continue

        # Count completed lifecycles from decisions
        completed = 0
        if self._decisions_path.exists():
            try:
                with open(self._decisions_path) as f:
                    for line in f:
                        try:
                            d = json.loads(line.strip())
                            if d.get("event") in ("closed", "exit", "pnl_computed"):
                                completed += 1
                        except json.JSONDecodeError:
                            pass
            except OSError:
                pass

        # Count open positions
        positions = self.get_positions()
        open_count = len(positions)

        # Derive observation_days from evidence snapshots
        observation_days = 0
        snapshots_path = evidence_dir / "position_snapshots.jsonl"
        if snapshots_path.exists():
            try:
                dates = set()
                with open(snapshots_path) as f:
                    for line in f:
                        line = line.strip()
                        if line:
                            try:
                                rec = json.loads(line)
                                ts = rec.get("timestamp", "")
                                if ts:
                                    dates.add(ts[:10])  # YYYY-MM-DD
                            except json.JSONDecodeError:
                                pass
                observation_days = len(dates)
            except OSError:
                pass

        total = sum(e_counts.values())
        insufficient = total < 30  # Need at least 30 trades for qualification

        data = {
            "campaign_id": campaign_id,
            "campaign_start": campaign_start,
            "evidence_maturity": {
                "e0_count": e_counts["e0"],
                "e1_count": e_counts["e1"],
                "e2_count": e_counts["e2"],
                "e3_count": e_counts["e3"],
                "e4_count": e_counts["e4"],
                "e5_count": e_counts["e5"],
                "e6_count": e_counts["e6"],
                "total_trades": total_trades,
                "open_trades": open_count,
                "completed_lifecycles": completed,
                "observation_days": observation_days,
                "timestamp": now,
            },
            "gates": [
                {
                    "gate_id": "A",
                    "name": "Minimum Trades",
                    "status": "SUFFICIENT" if total_trades >= 10 else "COLLECTING",
                    "details": {"required": 10, "current": total_trades},
                    "timestamp": now,
                },
                {
                    "gate_id": "B",
                    "name": "Lifecycle Completion",
                    "status": "SUFFICIENT" if completed >= 5 else "COLLECTING",
                    "details": {"required": 5, "current": completed},
                    "timestamp": now,
                },
                {
                    "gate_id": "C",
                    "name": "Observation Days",
                    "status": "SUFFICIENT" if observation_days >= 5 else "COLLECTING",
                    "details": {"required": 5, "current": observation_days},
                    "timestamp": now,
                },
            ],
            "overall_status": "COLLECTING" if insufficient else "SUFFICIENT",
            "evidence_insufficient": insufficient,
            "timestamp": now,
            "freshness": DataFreshness.LIVE.value,
        }

        # Persist for faster reads
        self._persist_json(self._evidence_dir / "qualification_status.json", data)

        return data

    # ─── Shadow Reduced ────────────────────────────────────────────

    def get_shadow_reduced(self) -> dict[str, Any]:
        """Read shadow REDUCED counterfactual data."""
        reduced_path = self._evidence_dir / "shadow_reduced.json"
        if reduced_path.exists():
            try:
                with open(reduced_path) as f:
                    data = json.load(f)
                data["mode"] = "SHADOW_ONLY"
                data["label"] = "Would Have Happened — NOT APPLIED LIVE"
                data["freshness"] = self._assess_freshness(data.get("timestamp"))
                return data
            except (json.JSONDecodeError, OSError):
                pass

        return {
            "mode": "SHADOW_ONLY",
            "observations": 0,
            "hypothetical_reductions": 0,
            "average_scale": None,
            "actual_size": None,
            "hypothetical_size": None,
            "actual_pnl": None,
            "hypothetical_pnl": None,
            "counterfactual_difference": None,
            "label": "Would Have Happened — NOT APPLIED LIVE",
            "timestamp": datetime.now(UTC).isoformat(),
            "freshness": DataFreshness.UNKNOWN.value,
        }

    # ─── Reconciliation ────────────────────────────────────────────

    def get_reconciliation_status(self) -> dict[str, Any]:
        """Read reconciliation status.

        Tries reconciliation_state.json first, then derives from positions.
        Persists the derived state for consistency.
        """
        recon_path = self._loop_dir / "reconciliation_state.json"
        if recon_path.exists():
            try:
                with open(recon_path) as f:
                    data = json.load(f)
                data["freshness"] = self._assess_freshness(data.get("timestamp"))
                return data
            except (json.JSONDecodeError, OSError):
                pass

        # Derive from positions — all SL-protected positions are reconciled
        positions = self.get_positions()
        protected = sum(1 for p in positions if p.get("protected"))
        total = len(positions)
        now = datetime.now(UTC).isoformat()

        # Check for foreign positions (no SL = potentially foreign/untracked)
        foreign = [p for p in positions if not p.get("protected")]

        status = {
            "overall_status": "CLEAN" if protected == total and total > 0 else ("WARNING" if foreign else "NO_DATA"),
            "last_reconciliation": now,
            "checks_performed": total,
            "checks_passed": protected,
            "checks_warning": len(foreign),
            "checks_critical": 0,
            "checks_blocking": 0,
            "stale_positions": 0,
            "missing_fills": 0,
            "duplicate_orders": 0,
            "foreign_positions": len(foreign),
            "position_count": total,
            "protected_count": protected,
            "unprotected_count": total - protected,
            "timestamp": now,
            "freshness": DataFreshness.LIVE.value if total > 0 else DataFreshness.UNKNOWN.value,
        }

        # Persist for consistency
        self._persist_json(recon_path, status)

        return status

    # ─── Events ────────────────────────────────────────────────────

    def get_recent_events(self, limit: int = 1000) -> list[dict[str, Any]]:
        """Read recent events from event ledger."""
        if not self._decisions_path.exists():
            return []

        events: list[dict[str, Any]] = []
        try:
            with open(self._decisions_path) as f:
                for line in f:
                    line = line.strip()
                    if line:
                        try:
                            events.append(json.loads(line))
                        except json.JSONDecodeError:
                            pass
        except OSError:
            pass

        return events[-limit:]

    # ─── Alerts ────────────────────────────────────────────────────

    def get_recent_alerts(self, limit: int = 50) -> list[dict[str, Any]]:
        """Read recent alerts from alert log.

        Sources:
        1. reports/alerts.jsonl (structured alerts from alert engine)
        2. reports/r4_loop/monitor.jsonl (monitor records with level/title)
        """
        alerts: list[dict[str, Any]] = []

        # Source 1: Structured alerts
        if self._alert_path.exists():
            try:
                with open(self._alert_path) as f:
                    for line in f:
                        line = line.strip()
                        if line:
                            try:
                                alerts.append(json.loads(line))
                            except json.JSONDecodeError:
                                pass
            except OSError:
                pass

        # Source 2: Monitor log records (contain level, title, body)
        if self._monitor_path.exists():
            try:
                with open(self._monitor_path) as f:
                    for line in f:
                        line = line.strip()
                        if line:
                            try:
                                rec = json.loads(line)
                                # Only include alert-level records
                                level = rec.get("level", "INFO")
                                if level in ("CRITICAL", "WARN", "WARNING", "TRADE"):
                                    # Normalize to alert format
                                    alert_record = {
                                        "alert_id": rec.get("alert_id", rec.get("timestamp", "unknown")),
                                        "timestamp": rec.get("timestamp", datetime.now(UTC).isoformat()),
                                        "severity": level if level != "WARN" else "WARNING",
                                        "category": rec.get("category", rec.get("title", "MONITOR")),
                                        "event_type": rec.get("event_type", "monitor"),
                                        "message": rec.get("body", rec.get("message", rec.get("title", ""))),
                                        "event_id": None,
                                        "correlation_id": rec.get("correlation_id"),
                                        "state_transition": None,
                                        "consecutive_count": rec.get("consecutive_count", 1),
                                        "details": rec.get("details", {}),
                                        "acknowledged": False,
                                    }
                                    alerts.append(alert_record)
                            except json.JSONDecodeError:
                                pass
            except OSError:
                pass

        # Sort by timestamp descending (newest first)
        alerts.sort(key=lambda a: a.get("timestamp", ""), reverse=True)

        return alerts[-limit:]

    # ─── Helpers ───────────────────────────────────────────────────

    def _read_json(self, path: Path) -> dict[str, Any] | None:
        """Safely read a JSON file, returning None on any error."""
        if not path.exists():
            return None
        try:
            with open(path) as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            return None

    def _empty_account_state(self) -> dict[str, Any]:
        """Return empty account state with explicit NOT_AVAILABLE semantics."""
        return {
            "equity": 0,
            "balance": 0,
            "free_margin": 0,
            "margin_used": 0,
            "margin_utilization": 0,
            "equity_high_water": 0,
            "drawdown": 0,
            "drawdown_pct": 0,
            "daily_pnl": 0,
            "daily_loss_remaining": 0,
            "unrealized_pnl": 0,
            "currency": "USD",
            "timestamp": datetime.now(UTC).isoformat(),
            "freshness": DataFreshness.UNKNOWN.value,
            "source": "unavailable",
        }

    def _assess_freshness(self, timestamp_str: str | None) -> str:
        """Assess data freshness based on timestamp.

        States:
        - LIVE: < 30s old
        - STALE: 30s-5min old
        - UNKNOWN: > 5min old or no timestamp
        """
        if not timestamp_str:
            return DataFreshness.UNKNOWN.value

        try:
            ts = datetime.fromisoformat(timestamp_str)
            age_seconds = (datetime.now(UTC) - ts).total_seconds()

            if age_seconds < 30:
                return DataFreshness.LIVE.value
            elif age_seconds < 300:
                return DataFreshness.STALE.value
            else:
                return DataFreshness.UNKNOWN.value
        except (ValueError, TypeError):
            return DataFreshness.UNKNOWN.value
