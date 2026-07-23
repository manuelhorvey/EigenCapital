"""ForensicsReportBuilder — aggregate per-asset reports into a portfolio view."""

from __future__ import annotations

from typing import Any


class ForensicsReportBuilder:
    """Aggregate per-asset forensic reports into a portfolio-level report."""

    def aggregate(self, per_asset: dict[str, dict]) -> dict[str, Any]:
        """Build a portfolio-level aggregate from individual asset reports.

        Parameters
        ----------
        per_asset:
            Map of ``asset_key → forensic_report`` as produced by
            ``LabelForensicsEngine.analyze_asset()``.

        Returns
        -------
        dict with keys:

            - ``n_assets_analyzed`` — count
            - ``n_assets_errored`` — count of assets that failed
            - ``portfolio_label_distribution`` — summed buy/sell/timeout
            - ``portfolio_first_touch`` — weighted avg first-touch pcts
            - ``portfolio_asymmetry`` — aggregated asymmetry stats
            - ``sell_bias_summary`` — how many assets have sell_pct > 55%
            - ``assets_by_bias`` — ranked by sell_pct descending
            - ``conclusions`` — list of likely root causes per asset
        """
        assets_ok = {k: v for k, v in per_asset.items() if "error" not in v}
        assets_err = {k: v for k, v in per_asset.items() if "error" in v}

        # ── Aggregate label distribution ──
        total = {"buy": 0, "sell": 0, "timeout": 0}
        for a, r in assets_ok.items():
            ld = r.get("label_distribution", {}).get("overall", {})
            total["buy"] += ld.get("buy", 0)
            total["sell"] += ld.get("sell", 0)
            total["timeout"] += ld.get("timeout", 0)
        tot = sum(total.values())
        portfolio_dist = {
            "buy": total["buy"],
            "sell": total["sell"],
            "timeout": total["timeout"],
            "buy_pct": round(total["buy"] / tot * 100, 2) if tot else 0.0,
            "sell_pct": round(total["sell"] / tot * 100, 2) if tot else 0.0,
            "timeout_pct": round(total["timeout"] / tot * 100, 2) if tot else 0.0,
            "total_labels": tot,
        }

        # ── Aggregate first-touch ──
        ft_agg = {"upper_total": 0, "lower_total": 0, "timeout_total": 0}
        for a, r in assets_ok.items():
            bm = r.get("barrier_statistics", {}).get("first_touch_distribution", {})
            # Recover approximate counts from percentages
            ld = r.get("label_distribution", {}).get("overall", {})
            n_total = ld.get("buy", 0) + ld.get("sell", 0) + ld.get("timeout", 0)
            ft_agg["upper_total"] += int(bm.get("upper_pct", 0) / 100.0 * n_total)
            ft_agg["lower_total"] += int(bm.get("lower_pct", 0) / 100.0 * n_total)
            ft_agg["timeout_total"] += int(bm.get("timeout_pct", 0) / 100.0 * n_total)
        ft_tot = sum(ft_agg.values())
        portfolio_ft = {
            "upper_pct": round(ft_agg["upper_total"] / ft_tot * 100, 2) if ft_tot else 0.0,
            "lower_pct": round(ft_agg["lower_total"] / ft_tot * 100, 2) if ft_tot else 0.0,
            "timeout_pct": round(ft_agg["timeout_total"] / ft_tot * 100, 2) if ft_tot else 0.0,
        }

        # ── Sell bias summary ──
        bias_list = []
        for a, r in assets_ok.items():
            ld = r.get("label_distribution", {}).get("overall", {})
            sp = ld.get("sell_pct", 0)
            bp = ld.get("buy_pct", 0)
            ba = r.get("barrier_statistics", {})
            ratio = ba.get("asymmetry_ratio_upper_over_lower", 0)
            bias_list.append((a, sp, bp, ratio))

        bias_list.sort(key=lambda x: x[1], reverse=True)

        heavy_sell = sum(1 for _, sp, _, _ in bias_list if sp > 55.0)
        heavy_buy = sum(1 for _, _, bp, _ in bias_list if bp > 55.0)

        sell_bias_summary = {
            "n_assets_with_sell_pct_gt_55": heavy_sell,
            "n_assets_with_buy_pct_gt_55": heavy_buy,
            "mean_sell_pct": round(
                sum(sp for _, sp, _, _ in bias_list) / len(bias_list), 2
            ) if bias_list else 0.0,
            "mean_asymmetry_ratio": round(
                sum(r for _, _, _, r in bias_list) / len(bias_list), 4
            ) if bias_list else 0.0,
        }

        assets_by_bias = [
            {"asset": a, "sell_pct": sp, "buy_pct": bp, "asymmetry_ratio": r}
            for a, sp, bp, r in bias_list
        ]

        # ── Conclusions ──
        conclusions = []
        for a, r in assets_ok.items():
            ld = r.get("label_distribution", {}).get("overall", {})
            sp = ld.get("sell_pct", 0)
            if sp > 65:
                conclusions.append({
                    "asset": a,
                    "sell_pct": sp,
                    "verdict": "extreme_sell_bias",
                    "suggestion": "Investigate barrier symmetry — likely vertical barrier or vol expansion during selloffs creates asymmetric labeling",
                })
            elif sp > 55:
                conclusions.append({
                    "asset": a,
                    "sell_pct": sp,
                    "verdict": "moderate_sell_bias",
                    "suggestion": "Compare label expectancy — may reflect genuine edge or label construction artifact",
                })

        return {
            "n_assets_analyzed": len(assets_ok),
            "n_assets_errored": len(assets_err),
            "error_list": list(assets_err.keys()) if assets_err else [],
            "portfolio_label_distribution": portfolio_dist,
            "portfolio_first_touch": portfolio_ft,
            "sell_bias_summary": sell_bias_summary,
            "assets_by_bias": assets_by_bias,
            "conclusions": conclusions,
        }
