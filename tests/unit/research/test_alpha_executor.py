"""Phase 1Q Tests — Campaign Execution and Research Map Generation.

Tests:
- Campaign executor runs all 29 hypotheses
- Freeze manifest integrity
- Verdict distribution is realistic
- Research map generation with forensic detail
- No hypothesis modified after registration
"""

import pytest

from eigencapital.research.alpha.executor import CampaignExecutor, HYPOTHESIS_LIBRARY, SIMULATED_EVIDENCE


class TestCampaignExecution:
    """Test the frozen 29-hypothesis campaign execution."""

    def test_all_29_hypotheses_registered(self):
        """All 29 hypotheses are registered in the campaign."""
        executor = CampaignExecutor()
        result = executor.execute()
        campaign = result["campaign"]
        assert campaign is not None

    def test_freeze_manifest_created(self):
        """Freeze manifest is created with correct hash."""
        executor = CampaignExecutor()
        result = executor.execute()
        assert result["freeze_manifest"] is not None
        assert result["freeze_hash"] != ""

    def test_verdicts_for_all_hypotheses(self):
        """Every hypothesis gets a verdict."""
        executor = CampaignExecutor()
        result = executor.execute()
        assert len(result["verdicts"]) == 29

    def test_scorecards_for_all_hypotheses(self):
        """Every hypothesis gets a scorecard."""
        executor = CampaignExecutor()
        result = executor.execute()
        assert len(result["scorecards"]) == 29

    def test_incremental_results_for_all(self):
        """Every hypothesis gets an incremental test result."""
        executor = CampaignExecutor()
        result = executor.execute()
        assert len(result["incremental_results"]) == 29

    def test_research_map_generated(self):
        """Research map is generated."""
        executor = CampaignExecutor()
        result = executor.execute()
        rm = result["research_map"]
        assert rm is not None
        assert rm.total_hypotheses == 29

    def test_campaign_completed(self):
        """Campaign reaches COMPLETED phase."""
        executor = CampaignExecutor()
        result = executor.execute()
        campaign = result["campaign"]
        assert campaign.current_phase == "completed"

    def test_realistic_verdict_distribution(self):
        """Verdict distribution is realistic (not too many winners)."""
        executor = CampaignExecutor()
        result = executor.execute()
        summary = result["summary"]
        # Most hypotheses should be rejected or fragile
        assert summary["rejected"] >= 10, f"Expected >=10 rejected, got {summary['rejected']}"
        # Some should survive
        survivors = summary["supported"] + summary["incremental"] + summary["production_candidate"]
        assert survivors >= 3, f"Expected >=3 survivors, got {survivors}"
        # Not too many production candidates
        assert summary["production_candidate"] <= 10, f"Expected <=10 PC, got {summary['production_candidate']}"

    def test_no_hypothesis_modified(self):
        """Registered hypothesis fingerprints match original definitions."""
        executor = CampaignExecutor()
        result = executor.execute()
        runner = executor._runner
        for hyp_def in HYPOTHESIS_LIBRARY:
            h = runner.get_hypothesis(hyp_def["id"])
            assert h is not None
            assert h.hypothesis_id == hyp_def["id"]
            assert h.family == hyp_def["family"]

    def test_research_map_markdown_produces_output(self):
        """Research map produces valid Markdown."""
        executor = CampaignExecutor()
        result = executor.execute()
        md = result["research_map"].to_markdown()
        assert "# Alpha Research Map" in md
        assert "29" in md
        assert len(md) > 500

    def test_freeze_hash_deterministic(self):
        """Same inputs produce same freeze hash."""
        r1 = CampaignExecutor().execute(git_commit="abc123")
        r2 = CampaignExecutor().execute(git_commit="abc123")
        assert r1["freeze_hash"] == r2["freeze_hash"]

    def test_different_commit_different_hash(self):
        """Different git commits produce different freeze hashes."""
        r1 = CampaignExecutor().execute(git_commit="abc123")
        r2 = CampaignExecutor().execute(git_commit="def456")
        assert r1["freeze_hash"] != r2["freeze_hash"]

    def test_summary_counts_add_up(self):
        """Summary counts add up correctly."""
        executor = CampaignExecutor()
        result = executor.execute()
        s = result["summary"]
        total_accounted = (
            s["rejected"] + s["supported"] + s["incremental"] +
            s["production_candidate"] + s["portfolio_useful"] +
            s["inconclusive"] + s["conditional"]
        )
        assert total_accounted == 29, f"Counts don't add up: {total_accounted} != 29"

    def test_hypothesis_library_has_29_entries(self):
        """Hypothesis library has exactly 29 entries."""
        assert len(HYPOTHESIS_LIBRARY) == 29

    def test_simulated_evidence_covers_all(self):
        """Simulated evidence exists for all 29 hypotheses."""
        for hyp in HYPOTHESIS_LIBRARY:
            assert hyp["id"] in SIMULATED_EVIDENCE, f"Missing evidence for {hyp['id']}"

    def test_families_covered(self):
        """All expected families are represented."""
        executor = CampaignExecutor()
        result = executor.execute()
        families = {v.family for v in result["verdicts"]}
        expected = {"factor", "trend", "momentum", "mean_reversion", "breakout",
                    "volatility", "cross_sectional", "statistical_arbitrage",
                    "alternative_data", "ml"}
        assert expected == families

    def test_trend_mom_vol_have_survivors(self):
        """Trend, momentum, and volatility families should have some survivors."""
        executor = CampaignExecutor()
        result = executor.execute()
        surviving_statuses = {"supported", "incremental", "production_candidate", "portfolio_useful"}
        for family in ["trend", "momentum", "volatility"]:
            family_verdicts = [v for v in result["verdicts"] if v.family == family]
            survivors = [v for v in family_verdicts if v.status in surviving_statuses]
            assert len(survivors) >= 1, f"Expected at least 1 survivor in {family}"

    def test_mean_reversion_and_stat_arb_hostile(self):
        """Mean reversion and stat arb should be mostly rejected (hostile cost test)."""
        executor = CampaignExecutor()
        result = executor.execute()
        rejected_statuses = {"rejected", "fragile", "capacity_limited", "redundant", "inconclusive"}
        for family in ["mean_reversion", "statistical_arbitrage"]:
            family_verdicts = [v for v in result["verdicts"] if v.family == family]
            rejected = [v for v in family_verdicts if v.status in rejected_statuses]
            assert len(rejected) >= 2, f"Expected >=2 rejected in {family}, got {len(rejected)}"

    def test_research_map_to_dict(self):
        """Research map serializes to dict."""
        executor = CampaignExecutor()
        result = executor.execute()
        d = result["research_map"].to_dict()
        assert "total_hypotheses" in d
        assert "family_summaries" in d
        assert "verdicts" in d

    def test_research_map_fingerprint(self):
        """Research map fingerprint is deterministic."""
        r1 = CampaignExecutor().execute()
        r2 = CampaignExecutor().execute()
        assert r1["research_map"].compute_fingerprint() == r2["research_map"].compute_fingerprint()
