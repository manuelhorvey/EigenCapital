"""Route registry — imports handlers from domain modules."""

from paper_trading.api.analytics_routes import (
    handle_analytics_snapshot,
    handle_archetype_stats,
    handle_attribution_summary,
    handle_attribution_trades,
    handle_attribution_waterfall,
    handle_execution_quality,
    handle_execution_slippage,
    handle_live_attribution,
)
from paper_trading.api.asset_routes import (
    handle_asset_detail,
    handle_mt5_status,
    handle_wal_asset,
)
from paper_trading.api.bundle import handle_state_bundle
from paper_trading.api.governance_routes import (
    handle_governance,
    handle_health,
    handle_health_asset,
    handle_liquidity,
    handle_narrative,
    handle_narrative_confirm,
    handle_psi,
    handle_risk,
    handle_risk_asset,
    handle_risk_parity,
    handle_statistical_metrics,
    handle_trade_outcomes,
    handle_weekly_review,
    handle_weekly_review_acknowledge,
)
from paper_trading.api.shadow_routes import (
    handle_shadow_actions,
    handle_shadow_actions_asset,
    handle_shadow_summary,
    handle_shadow_trades_route,
)
from paper_trading.api.state_routes import (
    handle_clear_cache,
    handle_confidence,
    handle_engine_health,
    handle_equity_history,
    handle_log_error,
    handle_logs,
    handle_metrics,
    handle_optimization,
    handle_ping,
    handle_state,
    handle_trades,
    handle_volatility,
)

GET_ROUTES: dict[str, tuple] = {
    "/state-bundle.json": (handle_state_bundle, False),
    "/state.json": (handle_state, False),
    "/trades.json": (handle_trades, False),
    "/equity_history.json": (handle_equity_history, False),
    "/confidence.json": (handle_confidence, False),
    "/volatility.json": (handle_volatility, False),
    "/logs": (handle_logs, True),
    "/risk.json": (handle_risk, False),
    "/shadow-actions": (handle_shadow_actions, False),
    "/health.json": (handle_health, False),
    "/governance.json": (handle_governance, False),
    "/statistical-metrics.json": (handle_statistical_metrics, False),
    "/risk-parity.json": (handle_risk_parity, False),
    "/narrative.json": (handle_narrative, False),
    "/liquidity.json": (handle_liquidity, False),
    "/psi.json": (handle_psi, False),
    "/trade-outcomes.json": (handle_trade_outcomes, False),
    "/weekly-review.json": (handle_weekly_review, False),
    "/attribution/trades.json": (handle_attribution_trades, False),
    "/attribution/summary.json": (handle_attribution_summary, False),
    "/execution/quality.json": (handle_execution_quality, False),
    "/execution/slippage.json": (handle_execution_slippage, False),
    "/shadow/trades.json": (handle_shadow_trades_route, False),
    "/shadow/summary.json": (handle_shadow_summary, False),
    "/archetype/stats.json": (handle_archetype_stats, False),
    "/attribution/live.json": (handle_live_attribution, False),
    "/attribution/waterfall.json": (handle_attribution_waterfall, False),
    "/analytics/snapshot.json": (handle_analytics_snapshot, False),
    "/mt5/status.json": (handle_mt5_status, False),
    "/optimization.json": (handle_optimization, False),
    "/ping": (handle_ping, False),
    "/health": (handle_engine_health, False),
    "/metrics": (handle_metrics, True),
}

GET_ROUTES_PREFIX: list[tuple[str, object, bool]] = [
    ("/risk/", handle_risk_asset, False),
    ("/shadow-actions/", handle_shadow_actions_asset, False),
    ("/health/", handle_health_asset, False),
    ("/wal/", handle_wal_asset, False),
    ("/asset/", handle_asset_detail, False),
]

POST_ROUTES: dict[str, object] = {
    "/narrative/confirm": handle_narrative_confirm,
    "/weekly-review/acknowledge": handle_weekly_review_acknowledge,
    "/api/clear-cache": handle_clear_cache,
    "/api/log-error": handle_log_error,
}
