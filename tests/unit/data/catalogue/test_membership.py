"""Tests for survivorship-aware universe membership tracking."""

import pytest

from eigencapital.data.catalogue.membership import (
    MembershipError,
    MembershipRepository,
    UniverseMembership,
    UniverseMembershipRegistry,
)


class TestUniverseMembership:
    """Membership record invariants."""

    def test_open_interval_valid(self):
        m = UniverseMembership("ES", "futures_core", "2015-03-01")
        assert m.effective_to is None
        assert m.is_active_on("2026-08-25")

    def test_closed_interval_bounds_inclusive(self):
        m = UniverseMembership(
            "ES", "futures_core", "2015-03-01", "2020-12-31", reason="delisted"
        )
        assert m.is_active_on("2015-03-01")
        assert m.is_active_on("2020-12-31")
        assert not m.is_active_on("2021-01-01")
        assert not m.is_active_on("2015-02-28")

    def test_end_before_start_rejected(self):
        with pytest.raises(MembershipError):
            UniverseMembership("ES", "u", "2020-01-01", "2019-01-01")

    def test_invalid_dates_rejected(self):
        with pytest.raises(MembershipError):
            UniverseMembership("ES", "u", "01/02/2020")
        with pytest.raises(MembershipError):
            UniverseMembership("ES", "u", "2020-01-01", "not-a-date")

    def test_empty_ids_rejected(self):
        with pytest.raises(MembershipError):
            UniverseMembership("", "u", "2020-01-01")
        with pytest.raises(MembershipError):
            UniverseMembership("ES", "", "2020-01-01")

    def test_is_active_on_validates_input(self):
        m = UniverseMembership("ES", "u", "2020-01-01")
        with pytest.raises(MembershipError):
            m.is_active_on("2020-13-40")

    def test_serialization_round_stable(self):
        m = UniverseMembership("ES", "u", "2020-01-01", "2021-06-30", "merged")
        d = m.to_dict()
        assert UniverseMembership.from_dict(d).to_dict() == d

    def test_open_serializes_null_end(self):
        d = UniverseMembership("ES", "u", "2020-01-01").to_dict()
        assert d["effective_to"] is None
        assert UniverseMembership.from_dict(d).effective_to is None


class TestRegistryPointInTime:
    """Point-in-time membership queries (survivorship-bias prevention)."""

    def _registry(self) -> UniverseMembershipRegistry:
        registry = UniverseMembershipRegistry()
        registry.add(UniverseMembership("AAA", "sp500", "2010-01-01"))
        registry.add(
            UniverseMembership(
                "DELISTED", "sp500", "2010-01-01", "2018-06-30", "acquired"
            )
        )
        registry.add(UniverseMembership("LATE", "sp500", "2020-01-01"))
        return registry

    def test_members_as_of_excludes_future_and_past_names(self):
        registry = self._registry()
        assert registry.members_as_of("sp500", "2015-01-01") == ["AAA", "DELISTED"]
        assert registry.members_as_of("sp500", "2019-01-01") == ["AAA"]
        assert registry.members_as_of("sp500", "2021-01-01") == ["AAA", "LATE"]

    def test_delisted_name_survives_in_history(self):
        """The core survivorship property: removed names remain queryable."""
        registry = self._registry()
        history = registry.history("DELISTED")
        assert len(history) == 1
        assert history[0].reason == "acquired"
        assert registry.is_member_at("DELISTED", "sp500", "2018-06-30")
        assert not registry.is_member_at("DELISTED", "sp500", "2018-07-01")

    def test_unknown_universe_empty(self):
        assert self._registry().members_as_of("nope", "2020-01-01") == []

    def test_active_members_only_open_intervals(self):
        assert self._registry().active_members("sp500") == ["AAA", "LATE"]


class TestRegistryMutation:
    """add/delist semantics and overlap protection."""

    def test_delist_closes_open_interval(self):
        registry = UniverseMembershipRegistry()
        registry.add(UniverseMembership("ES", "core", "2020-01-01"))
        closed = registry.delist("ES", "core", "2024-12-31", reason="contract_expired")
        assert closed.effective_to == "2024-12-31"
        assert closed.reason == "contract_expired"
        assert registry.active_members("core") == []
        assert registry.members_as_of("core", "2024-12-31") == ["ES"]
        assert registry.members_as_of("core", "2025-01-01") == []

    def test_delist_without_open_interval_raises(self):
        registry = UniverseMembershipRegistry()
        registry.add(UniverseMembership("ES", "core", "2020-01-01", "2021-01-01"))
        with pytest.raises(MembershipError, match="No open membership"):
            registry.delist("ES", "core", "2022-01-01")

    def test_delist_unknown_instrument_raises(self):
        with pytest.raises(MembershipError):
            UniverseMembershipRegistry().delist("XX", "core", "2022-01-01")

    def test_overlapping_add_rejected(self):
        registry = UniverseMembershipRegistry()
        registry.add(UniverseMembership("ES", "core", "2020-01-01", "2021-01-01"))
        with pytest.raises(MembershipError, match="Overlapping"):
            registry.add(UniverseMembership("ES", "core", "2021-01-01"))

    def test_day_after_closed_interval_allowed(self):
        registry = UniverseMembershipRegistry()
        registry.add(UniverseMembership("ES", "core", "2020-01-01", "2020-12-31"))
        registry.add(UniverseMembership("ES", "core", "2021-01-01"))
        assert registry.history("ES", "core")[1].effective_from == "2021-01-01"

    def test_same_instrument_different_universes_ok(self):
        registry = UniverseMembershipRegistry()
        registry.add(UniverseMembership("ES", "core", "2020-01-01"))
        registry.add(UniverseMembership("ES", "watchlist", "2019-01-01"))
        assert sorted(registry.universes()) == ["core", "watchlist"]

    def test_sequential_membership_cycles(self):
        registry = UniverseMembershipRegistry()
        for year in range(3):
            start = f"{2010 + 2 * year}-01-01"
            end = f"{2011 + 2 * year}-12-31"
            registry.add(UniverseMembership("X", "u", start, end))
        assert [m.effective_from for m in registry.history("X")] == [
            "2010-01-01",
            "2012-01-01",
            "2014-01-01",
        ]


class TestRegistrySerialization:
    """Deterministic persistence."""

    def test_to_dict_sorted_and_stable(self):
        registry = UniverseMembershipRegistry()
        registry.add(UniverseMembership("B", "u2", "2020-01-01"))
        registry.add(UniverseMembership("A", "u1", "2021-01-01"))
        d = registry.to_dict()
        order = [
            (m["universe_id"], m["instrument_id"])
            for m in d["memberships"]
        ]
        assert order == [("u1", "A"), ("u2", "B")]

    def test_roundtrip_preserves_queries(self):
        registry = UniverseMembershipRegistry()
        registry.add(UniverseMembership("ES", "core", "2020-01-01", "2022-01-01"))
        restored = UniverseMembershipRegistry.from_dict(registry.to_dict())
        assert restored.members_as_of("core", "2021-01-01") == ["ES"]
        assert restored.members_as_of("core", "2023-01-01") == []


class TestMembershipRepository:
    """JSON persistence."""

    def test_save_load_roundtrip(self, tmp_path):
        repo = MembershipRepository(tmp_path / "meta")
        registry = UniverseMembershipRegistry()
        registry.add(UniverseMembership("ES", "core", "2020-01-01"))
        repo.save(registry)
        loaded = repo.load()
        assert loaded.active_members("core") == ["ES"]

    def test_load_missing_file_returns_empty_registry(self, tmp_path):
        repo = MembershipRepository(tmp_path / "nowhere")
        assert isinstance(repo.load(), UniverseMembershipRegistry)
        assert repo.load().universes() == []

    def test_saved_json_is_deterministic(self, tmp_path):
        import json

        repo = MembershipRepository(tmp_path / "meta")
        registry = UniverseMembershipRegistry()
        registry.add(UniverseMembership("B", "u", "2020-01-01"))
        registry.add(UniverseMembership("A", "u", "2020-01-01"))
        repo.save(registry)
        content = json.loads((tmp_path / "meta" / "memberships.json").read_text())
        ids = [m["instrument_id"] for m in content["memberships"]]
        assert ids == sorted(ids)
