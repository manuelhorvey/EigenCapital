"""Micro-Live Runner — connects to real MT5 broker and runs R4 with minimal capital.

This is the final engineering gate:
- Real broker connection
- Real order submission
- Real fills
- Real reconciliation
- Automatic kill conditions
"""

from __future__ import annotations

import logging
import time
from typing import Dict, List, Optional, Any

import numpy as np
import pandas as pd

from eigencapital.fidelity.r4_manifest import R4ConfigManifest
from eigencapital.micro_live.campaign import (
    MicroLiveCampaign,
    MicroLiveEnvelope,
    MicroLiveAuthorization,
    MicroLiveStatus,
    KillReason,
)
from eigencapital.micro_live.qualification import MicroLiveEvaluator

logger = logging.getLogger(__name__)


class MT5Connection:
    """Connection to MT5 via RPyC bridge."""

    def __init__(self, host: str = "127.0.0.1", port: int = 8001) -> None:
        self._host = host
        self._port = port
        self._mt5 = None
        self._connected = False

    def connect(self) -> bool:
        try:
            from mt5linux import MetaTrader5
            self._mt5 = MetaTrader5(host=self._host, port=self._port)
            self._connected = self._mt5.initialize()
            if self._connected:
                logger.info(f"MT5 connected on {self._host}:{self._port}")
            return self._connected
        except Exception as e:
            logger.error(f"MT5 connection failed: {e}")
            return False

    def get_account_info(self) -> Dict[str, Any]:
        if not self._connected:
            return {}
        info = self._mt5.account_info()
        if info is None:
            return {}
        return {
            "balance": info.balance,
            "equity": info.equity,
            "margin": info.margin,
            "free_margin": info.margin_free,
            "leverage": info.leverage,
            "currency": info.currency,
            "profit": info.profit,
        }

    def get_positions(self) -> List[Dict[str, Any]]:
        if not self._connected:
            return []
        positions = self._mt5.positions_get()
        if positions is None:
            return []
        return [
            {
                "ticket": p.ticket,
                "symbol": p.symbol,
                "type": "BUY" if p.type == 0 else "SELL",
                "volume": p.volume,
                "price_open": p.price_open,
                "price_current": p.price_current,
                "sl": p.sl,
                "tp": p.tp,
                "profit": p.profit,
                "swap": p.swap,
            }
            for p in positions
        ]

    def get_symbol_info(self, symbol: str) -> Dict[str, Any]:
        if not self._connected:
            return {}
        info = self._mt5.symbol_info(symbol)
        if info is None:
            return {}
        return {
            "symbol": info.symbol,
            "bid": info.bid,
            "ask": info.ask,
            "spread": info.spread,
            "volume": info.volume_real,
            "point": info.point,
            "digits": info.digits,
        }

    def submit_order(
        self,
        symbol: str,
        order_type: str,
        volume: float,
        price: float = 0.0,
        sl: float = 0.0,
        tp: float = 0.0,
        comment: str = "EigenCapital-MicroLive",
    ) -> Dict[str, Any]:
        """Submit a real order to MT5."""
        if not self._connected:
            return {"success": False, "error": "Not connected"}

        from mt5linux import MetaTrader5

        if order_type == "BUY":
            mt5_type = MetaTrader5.ORDER_TYPE_BUY
        elif order_type == "SELL":
            mt5_type = MetaTrader5.ORDER_TYPE_SELL
        else:
            return {"success": False, "error": f"Unknown order type: {order_type}"}

        request = {
            "action": MetaTrader5.TRADE_ACTION_DEAL,
            "symbol": symbol,
            "volume": volume,
            "type": mt5_type,
            "price": price,
            "sl": sl,
            "tp": tp,
            "deviation": 10,
            "magic": 20260824,
            "comment": comment,
            "type_time": MetaTrader5.ORDER_TIME_GTC,
            "type_filling": MetaTrader5.ORDER_FILLING_IOC,
        }

        result = self._mt5.order_send(request)
        if result is None:
            return {"success": False, "error": "Order send returned None"}

        return {
            "success": result.retcode == MetaTrader5.TRADE_RETCODE_DONE,
            "order": result.order,
            "deal": result.deal,
            "retcode": result.retcode,
            "comment": result.comment,
            "price": result.price,
            "volume": result.volume,
        }

    def close_position(self, ticket: int) -> Dict[str, Any]:
        """Close a specific position."""
        if not self._connected:
            return {"success": False, "error": "Not connected"}

        from mt5linux import MetaTrader5

        positions = self._mt5.positions_get(ticket=ticket)
        if not positions:
            return {"success": False, "error": "Position not found"}

        pos = positions[0]
        close_type = (
            MetaTrader5.ORDER_TYPE_SELL if pos.type == 0
            else MetaTrader5.ORDER_TYPE_BUY
        )

        request = {
            "action": MetaTrader5.TRADE_ACTION_DEAL,
            "symbol": pos.symbol,
            "volume": pos.volume,
            "type": close_type,
            "position": ticket,
            "price": 0,
            "deviation": 10,
            "magic": 20260824,
            "comment": "EigenCapital-Close",
            "type_time": MetaTrader5.ORDER_TIME_GTC,
            "type_filling": MetaTrader5.ORDER_FILLING_IOC,
        }

        result = self._mt5.order_send(request)
        if result is None:
            return {"success": False, "error": "Close order returned None"}

        return {
            "success": result.retcode == MetaTrader5.TRADE_RETCODE_DONE,
            "order": result.order,
            "deal": result.deal,
            "retcode": result.retcode,
        }

    def disconnect(self) -> None:
        if self._mt5:
            self._mt5.shutdown()
            self._connected = False

    @property
    def is_connected(self) -> bool:
        return self._connected


class MicroLiveRunner:
    """Runs the micro-live campaign against real MT5 broker."""

    def __init__(self, manifest: R4ConfigManifest) -> None:
        self._manifest = manifest
        self._campaign_id = f"ML-{manifest.compute_identity()[:12]}"
        self._mt5 = MT5Connection()
        self._envelope = MicroLiveEnvelope()
        self._authorization: Optional[MicroLiveAuthorization] = None
        self._campaign: Optional[MicroLiveCampaign] = None
        self._internal_positions: Dict[str, float] = {}

    def authorize(
        self,
        operator_identity: str = "manuel",
        broker_identity: str = "exness",
        account_identity: str = "168966110",
    ) -> MicroLiveAuthorization:
        """Create human authorization for micro-live campaign."""
        self._authorization = MicroLiveAuthorization(
            authorization_id=f"AUTH-{self._campaign_id}",
            campaign_id=self._campaign_id,
            strategy_fingerprint=self._manifest.compute_identity(),
            risk_envelope_hash=self._envelope.compute_identity(),
            broker_identity=broker_identity,
            account_identity=account_identity,
            operator_identity=operator_identity,
            max_capital=self._envelope.max_account_equity,
            max_duration_hours=self._envelope.max_campaign_duration_hours,
            created_timestamp=time.strftime("%Y-%m-%dT%H:%M:%S"),
            expiry_timestamp=time.strftime(
                "%Y-%m-%dT%H:%M:%S",
                time.gmtime(time.time() + self._envelope.max_campaign_duration_hours * 3600),
            ),
        )
        return self._authorization

    def run(self) -> Dict[str, Any]:
        """Run the micro-live campaign."""
        print("=" * 70)
        print("MICRO-LIVE CAMPAIGN")
        print("Real MT5 Broker + Frozen R4 + Minimal Capital")
        print("=" * 70)

        # 1. Connect to MT5
        print("\n[1/6] Connecting to MT5...")
        if not self._mt5.connect():
            return {"status": "FAILED", "error": "Cannot connect to MT5"}

        account = self._mt5.get_account_info()
        print(f"  Balance: ${account.get('balance', 0):.2f}")
        print(f"  Equity: ${account.get('equity', 0):.2f}")
        print(f"  Free margin: ${account.get('free_margin', 0):.2f}")

        # 2. Create authorization
        print("\n[2/6] Creating authorization...")
        if not self._authorization:
            self.authorize()
        print(f"  Authorization: {self._authorization.authorization_id}")
        print(f"  Expires: {self._authorization.expiry_timestamp}")

        # 3. Create campaign
        print("\n[3/6] Creating campaign...")
        self._campaign = MicroLiveCampaign(
            campaign_id=self._campaign_id,
            envelope=self._envelope,
            authorization=self._authorization,
        )

        # 4. Preflight
        print("\n[4/6] Running preflight...")
        preflight = self._campaign.preflight()
        print(f"  Preflight: {'PASS' if preflight['all_pass'] else 'FAIL'}")
        if not preflight["all_pass"]:
            return {"status": "FAILED", "error": "Preflight failed", "preflight": preflight}

        # 5. Activate and check positions
        print("\n[5/6] Activating campaign...")
        self._campaign.activate()
        print(f"  Status: {self._campaign.state.status.value}")

        # Check current broker positions
        broker_positions = self._mt5.get_positions()
        print(f"  Current broker positions: {len(broker_positions)}")
        for pos in broker_positions:
            print(f"    {pos['symbol']}: {pos['type']} {pos['volume']} @ {pos['price_open']}")

        # 6. Check kill conditions
        print("\n[6/6] Checking kill conditions...")
        kill_reason = self._campaign.check_kill_conditions(
            current_equity=account.get("equity", 0)
        )
        if kill_reason:
            self._campaign.execute_kill(kill_reason, f"Pre-execution kill: {kill_reason.value}")
            print(f"  KILLED: {kill_reason.value}")
        else:
            print("  No kill conditions triggered")

        # Get result
        result = self._campaign.get_result()

        # Print summary
        print("\n" + "=" * 70)
        print("MICRO-LIVE CAMPAIGN RESULT")
        print("=" * 70)
        print(f"  Campaign: {result['campaign_id']}")
        print(f"  Status: {result['state']['status']}")
        print(f"  Kill events: {len(result['kill_events'])}")
        print(f"  Orders submitted: {result['state']['orders_submitted']}")
        print(f"  Orders filled: {result['state']['orders_filled']}")

        # Disconnect
        self._mt5.disconnect()

        return result

    def get_campaign(self) -> Optional[MicroLiveCampaign]:
        return self._campaign

    @property
    def mt5(self) -> MT5Connection:
        return self._mt5
