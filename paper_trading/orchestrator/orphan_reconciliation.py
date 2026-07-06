"""MT5 orphan reconciliation — periodic sweep to detect and clean orphaned positions.

Owns all orphan-related state (stale ticket counters, abandoned orphan count,
first-seen cycle tracking). Called by EngineOrchestrator every cycle as Phase 3g.

Phases:
    A — Drain cleanup queues (event-triggered from MT5 close failures).
    B — Detect stale paper mt5_tickets (MT5-native SL/TP, manual close).
    C — Dry-run orphan report (log only, no state mutation).
    D — Self-healing adoption (backfill mt5_ticket from broker when paper has
        position but no ticket — crash recovery).
"""

from __future__ import annotations

import logging
from typing import Any

from eigencapital.domain.time import utc_now

logger = logging.getLogger("eigencapital.orchestrator.orphan_reconciliation")

# After this many consecutive close failures, abandon the orphan and log CRITICAL.
MAX_CLEANUP_RETRIES = 5
# Number of consecutive cycles a ticket must be missing from broker positions
# before the paper position is closed as stale. At 30s/cycle this is ~5 minutes.
# Prevents premature closure during MT5 order fill propagation delay.
MAX_STALE_TICKET_CYCLES = 10
# After this many missing cycles, check the MT5 deal history (history_deals_get)
# to determine whether the ticket was ever filled. If it was, the position
# was closed by MT5-native SL/TP or manual intervention. If no deal exists,
# the order was never filled (e.g. broker rejection) and the paper position
# is a ghost. At 30s/cycle this is ~90s for the deal-history check.
STALE_TICKET_DEAL_CHECK_CYCLES = 3


class OrphanReconciler:
    """Orphan reconciliation state and logic for one orchestrator instance."""

    def __init__(self) -> None:
        self.abandoned_orphans: int = 0
        self._stale_ticket_cycles: dict[str, int] = {}
        self._orphan_first_seen: dict[str, int] = {}
        self._orphan_cycle_no: int = 0

    def reconcile(self, actors: dict[str, Any], resolve_broker) -> None:
        """Run all orphan reconciliation phases for one engine cycle.

        Args:
            actors: dict of asset name → AssetActor
            resolve_broker: callable that returns an MT5 broker or None
        """
        broker = resolve_broker()
        if broker is None:
            return

        self._phase_a_drain_queues(broker, actors)
        self._phase_b_stale_tickets(broker, actors)
        self._phase_c_orphan_report(broker, actors)

    # ── Phase A: Drain cleanup queues ──────────────────────────────────

    def _phase_a_drain_queues(self, broker, actors: dict[str, Any]) -> None:
        """Event-triggered cleanup from MT5 close failures."""
        for name, actor in actors.items():
            engine = actor._engine
            db = engine.__dict__
            queue = db.get("_mt5_cleanup_queue")
            if not queue:
                continue
            retries = db.get("_mt5_cleanup_retries", 0)

            if retries >= MAX_CLEANUP_RETRIES:
                self.abandoned_orphans += 1
                logger.error(
                    "MT5_ORPHAN abandoned after %d retries: %s queue=%s — manual MT5 cleanup required",
                    MAX_CLEANUP_RETRIES,
                    name,
                    queue,
                )
                abandonment_threshold = 3
                if self.abandoned_orphans == abandonment_threshold or self.abandoned_orphans % 5 == 0:
                    try:
                        from paper_trading.alerting.manager import Severity, global_alert_manager

                        global_alert_manager().alert(
                            severity=Severity.CRITICAL,
                            title=f"MT5 orphan abandonments reached {self.abandoned_orphans}",
                            message=(
                                f"Abandoned orphan for {name} after {MAX_CLEANUP_RETRIES} retries. "
                                f"Manual MT5 cleanup required. Queue was: {queue}"
                            ),
                            asset=name,
                        )
                    except Exception:  # noqa: BLE001
                        logger.exception("Alerter dispatch failed for orphan abandonment")
                engine._mt5_cleanup_queue = []
                engine._mt5_cleanup_retries = 0
                continue

            still_pending: list[tuple[str, int]] = []
            for mt5_symbol, ticket in queue:
                try:
                    ok = broker.close_position(mt5_symbol, str(ticket))
                    if ok:
                        logger.warning(
                            "MT5_ORPHAN cleaned: %s ticket=%s on %s",
                            name,
                            ticket,
                            mt5_symbol,
                        )
                    else:
                        still_pending.append((mt5_symbol, ticket))
                        logger.warning(
                            "MT5_ORPHAN retry %d/%d: %s ticket=%s on %s",
                            retries + 1,
                            MAX_CLEANUP_RETRIES,
                            name,
                            ticket,
                            mt5_symbol,
                        )
                except (OSError, ValueError, TypeError) as e:
                    still_pending.append((mt5_symbol, ticket))
                    logger.error(
                        "MT5_ORPHAN exception on retry %d: %s ticket=%s on %s: %s",
                        retries + 1,
                        name,
                        ticket,
                        mt5_symbol,
                        e,
                    )

            engine._mt5_cleanup_queue = still_pending
            engine._mt5_cleanup_retries = retries + 1 if still_pending else 0

    # ── Phase B: Stale ticket detection ────────────────────────────────

    def _phase_b_stale_tickets(self, broker, actors: dict[str, Any]) -> None:
        """Detect paper-side mt5_tickets that no longer exist on the broker.

        Multi-cycle grace period prevents premature closure during MT5 order
        fill propagation delay through Wine.
        """
        if not broker.ensure_connected():
            return
        try:
            broker._position_cache_time = 0.0  # invalidate cache for fresh data
            mt5_positions = broker.get_positions()
        except (OSError, ValueError, TypeError):
            return

        mt5_by_ticket: dict[str, object] = {}
        for p in mt5_positions:
            if p.position_id:
                mt5_by_ticket[p.position_id] = p

        for name, actor in actors.items():
            engine = actor._engine
            if not engine.position:
                continue
            mt5_ticket = engine.position.get("mt5_ticket")
            if mt5_ticket is None:
                continue
            ticket_key = f"{name}:{mt5_ticket}"
            if str(mt5_ticket) not in mt5_by_ticket:
                prev = self._stale_ticket_cycles.get(ticket_key, 0)
                self._stale_ticket_cycles[ticket_key] = prev + 1
                missing_for = self._stale_ticket_cycles[ticket_key]

                if missing_for >= MAX_STALE_TICKET_CYCLES:
                    logger.warning(
                        "MT5_STALE_TICKET: %s ticket=%s missing for %d/%d cycles — closing paper position",
                        name,
                        mt5_ticket,
                        missing_for,
                        MAX_STALE_TICKET_CYCLES,
                    )
                    self._stale_ticket_cycles.pop(ticket_key, None)
                    engine.position.pop("mt5_ticket", None)
                    exit_price = getattr(engine, "current_price", None)
                    if exit_price is not None and exit_price > 0:
                        try:
                            engine._close_position(
                                exit_price,
                                utc_now(),
                                "MT5_STALE_TICKET",
                            )
                        except Exception:  # noqa: BLE001
                            logger.exception(
                                "MT5_STALE_TICKET: %s failed to close paper position — position may be a ghost",
                                name,
                            )
                elif missing_for >= STALE_TICKET_DEAL_CHECK_CYCLES:
                    try:
                        deal = broker.get_deal_by_ticket(int(mt5_ticket))
                    except Exception:  # noqa: BLE001
                        deal = None
                    if deal is not None:
                        logger.info(
                            "MT5_STALE_TICKET_DEAL_CHECK: %s ticket=%s found in deal history "
                            "(filled at %.5f profit=%.2f) — position was closed by MT5-native "
                            "SL/TP or manual intervention after %d/%d cycles",
                            name,
                            mt5_ticket,
                            deal["result"].get("price", 0),
                            deal["result"].get("profit", 0),
                            missing_for,
                            MAX_STALE_TICKET_CYCLES,
                        )
                    else:
                        logger.warning(
                            "MT5_ORDER_REJECTED: %s ticket=%s missing for %d/%d cycles "
                            "and no deal found in history — order was never filled, "
                            "closing paper position early",
                            name,
                            mt5_ticket,
                            missing_for,
                            MAX_STALE_TICKET_CYCLES,
                        )
                        self._stale_ticket_cycles.pop(ticket_key, None)
                        engine.position.pop("mt5_ticket", None)
                        exit_price = getattr(engine, "current_price", None)
                        if exit_price is not None and exit_price > 0:
                            try:
                                engine._close_position(
                                    exit_price,
                                    utc_now(),
                                    "MT5_ORDER_REJECTED",
                                )
                            except Exception:  # noqa: BLE001
                                logger.exception(
                                    "MT5_ORDER_REJECTED: %s failed to close paper position — position may be a ghost",
                                    name,
                                )
                else:
                    logger.info(
                        "MT5_STALE_TICKET_GRACE: %s ticket=%s missing for %d/%d cycles "
                        "(deal check at %d cycles) — holding",
                        name,
                        mt5_ticket,
                        missing_for,
                        MAX_STALE_TICKET_CYCLES,
                        STALE_TICKET_DEAL_CHECK_CYCLES,
                    )
            else:
                if ticket_key in self._stale_ticket_cycles:
                    logger.info(
                        "MT5_STALE_TICKET_RECOVERED: %s ticket=%s reappeared after %d cycles — resetting grace counter",
                        name,
                        mt5_ticket,
                        self._stale_ticket_cycles[ticket_key],
                    )
                    self._stale_ticket_cycles.pop(ticket_key, None)

    # ── Phase C: Dry-run orphan report + Phase D: Self-healing adoption ──

    def _phase_c_orphan_report(self, broker, actors: dict[str, Any]) -> None:
        """Report MT5 positions with no matching paper-side ticket.

        Phase C — log-only orphan report (observability).
        Phase D — self-healing adoption: backfill mt5_ticket from broker when
        paper has a position but no ticket (crash recovery).
        """
        try:
            broker._position_cache_time = 0.0
            mt5_positions = broker.get_positions()
        except (OSError, ValueError, TypeError):
            return

        mt5_by_ticket: dict[str, object] = {}
        for p in mt5_positions:
            if p.position_id:
                mt5_by_ticket[p.position_id] = p

        self._orphan_cycle_no += 1

        known_tickets: set[str] = set()
        for name, actor in actors.items():
            engine = actor._engine
            if not engine.position:
                continue
            ticket = engine.position.get("mt5_ticket")
            if ticket is not None:
                mt5_str = str(ticket)
                if mt5_str in mt5_by_ticket:
                    known_tickets.add(mt5_str)

        sym_actors: dict[str, list[tuple[str, Any]]] = {}
        for name, actor in actors.items():
            engine = actor._engine
            if engine is None:
                continue
            mt5_sym = broker.ticker_to_mt5_symbol(engine.ticker)
            sym_actors.setdefault(mt5_sym, []).append((name, engine))

        reverse_map: dict[str, str] = {}
        for ticker, mt5_sym in broker._symbol_map.items():
            reverse_map[mt5_sym] = ticker

        unique_orphans_this_cycle: set[str] = set()
        for p in mt5_positions:
            ticket = p.position_id
            if ticket is None:
                continue
            if ticket in known_tickets:
                continue

            unique_orphans_this_cycle.add(ticket)

            if ticket not in self._orphan_first_seen:
                self._orphan_first_seen[ticket] = self._orphan_cycle_no
                first_seen_str = "this_cycle"
            else:
                first_seen_str = f"cycle_{self._orphan_first_seen[ticket]}"

            matching = sym_actors.get(p.asset)
            if matching:
                name, matched_engine = matching[0]
                ticker = matched_engine.ticker
                paper_pos = matched_engine.position
                if paper_pos and paper_pos.get("mt5_ticket") is not None:
                    orphan_reason = f"paper_ticket_mismatch (has {paper_pos['mt5_ticket']})"
                elif paper_pos:
                    orphan_reason = "paper_has_position_no_ticket"
                    # Phase D: self-healing adoption
                    matched_engine.position["mt5_ticket"] = int(ticket)
                    logger.info(
                        "PHASE_D_ADOPT: %s adopted orphan ticket=%s on %s",
                        name,
                        int(ticket),
                        p.asset,
                    )
                else:
                    orphan_reason = "no_paper_position"
                engine_actor = name
            else:
                ticker = reverse_map.get(p.asset, p.asset)
                orphan_reason = "removed_asset" if p.asset in reverse_map else "unknown_symbol"
                engine_actor = None

            side = "long" if p.quantity >= 0 else "short"
            vol = abs(p.quantity)

            logger.warning(
                "PHASE_C_ORPHAN: ticket=%s mt5_symbol=%s ticker=%s "
                "engine_actor=%s side=%s vol=%.4f entry=%.5f price=%.5f "
                "upnl=%.2f first_seen=%s reason=%s",
                ticket,
                p.asset,
                ticker,
                engine_actor or "None",
                side,
                vol,
                p.avg_entry_price,
                p.current_price,
                p.unrealized_pnl,
                first_seen_str,
                orphan_reason,
            )

        n_unique = len(self._orphan_first_seen)
        n_this_cycle = len(unique_orphans_this_cycle)
        if n_unique > 0 or n_this_cycle > 0:
            logger.warning(
                "PHASE_C_SUMMARY: %d unique orphan tickets tracked (%d this cycle)",
                n_unique,
                n_this_cycle,
            )
