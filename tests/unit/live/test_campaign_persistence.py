"""H-8 regression tests — campaign history must survive crash and restart.

``CampaignManager`` previously kept campaigns and transition events only in
plain dicts: a crash/restart lost every campaign. These tests pin the
durable behaviour: restart survival of campaigns and events, tolerance of a
torn write from a crash mid-append, and lifecycle transitions still being
enforced on reloaded state.
"""

from __future__ import annotations

from pathlib import Path

from eigencapital.live.campaign import (
    CampaignManager,
    CampaignStatus,
    MicroLiveCampaign,
)


def _make_campaign(campaign_id: str = "camp-1", **overrides) -> MicroLiveCampaign:
    defaults = {
        "campaign_id": campaign_id,
        "strategy_fingerprint": "strat-fp",
        "portfolio_fingerprint": "port-fp",
        "feature_fingerprint": "feat-fp",
        "risk_fingerprint": "risk-fp",
        "execution_fingerprint": "exec-fp",
        "broker_identity": "broker-1",
        "account_identity": "acct-1",
        "capital_limit": 10000.0,
        "drawdown_limit": 2000.0,
        "start_timestamp": "2026-01-01T00:00:00",
        "expiry_timestamp": "2026-12-31T23:59:59",
    }
    defaults.update(overrides)
    return MicroLiveCampaign(**defaults)


def test_campaigns_survive_process_restart(tmp_path: Path) -> None:
    """A new manager instance over the same store sees the same campaigns."""
    store = tmp_path / "campaigns.jsonl"
    manager = CampaignManager(store_path=store)
    manager.create_campaign(_make_campaign())
    assert manager.transition_campaign("camp-1", CampaignStatus.PREFLIGHT.value, "t1")
    assert manager.transition_campaign("camp-1", CampaignStatus.AUTHORIZED.value, "t2")
    first_record = store.read_bytes().splitlines()[0]

    restarted = CampaignManager(store_path=store)
    reloaded = restarted.get_campaign("camp-1")
    assert reloaded is not None
    assert reloaded.status == CampaignStatus.AUTHORIZED.value
    assert reloaded.status_history == (
        (CampaignStatus.PREFLIGHT.value, "t1"),
        (CampaignStatus.AUTHORIZED.value, "t2"),
    )
    assert [c.campaign_id for c in restarted.get_all_campaigns()] == ["camp-1"]
    assert len(restarted.get_campaigns_by_status(CampaignStatus.AUTHORIZED.value)) == 1
    assert restarted.get_campaigns_by_status(CampaignStatus.ACTIVE.value) == []
    # Append-only history: the first record was never rewritten or dropped.
    assert store.read_bytes().splitlines()[0] == first_record


def test_events_survive_process_restart(tmp_path: Path) -> None:
    """Every recorded event is reloaded verbatim by a new instance."""
    store = tmp_path / "campaigns.jsonl"
    manager = CampaignManager(store_path=store)
    manager.create_campaign(_make_campaign())
    assert manager.transition_campaign("camp-1", CampaignStatus.PREFLIGHT.value, "t1")
    assert manager.transition_campaign("camp-1", CampaignStatus.ACTIVE.value, "nope") is False

    restarted = CampaignManager(store_path=store)
    assert restarted.get_events() == manager.get_events()
    assert [e["event_type"] for e in restarted.get_events()] == [
        "CAMPAIGN_CREATED",
        "STATUS_CHANGED",
        "INVALID_TRANSITION",
    ]


def test_crash_mid_write_does_not_corrupt_store(tmp_path: Path) -> None:
    """A torn append from a crash neither zeros nor corrupts the store."""
    store = tmp_path / "campaigns.jsonl"
    manager = CampaignManager(store_path=store)
    manager.create_campaign(_make_campaign())
    assert manager.transition_campaign("camp-1", CampaignStatus.PREFLIGHT.value, "t1")
    intact_before_crash = store.read_bytes()

    # Simulate a crash mid-append: a torn, partially written final line.
    with open(store, "ab") as handle:
        handle.write(b'{"seq": 3, "hash": "abc", "payload": {"event_type": "STATUS_CH')

    # The store was appended to, never truncated or zeroed.
    assert store.read_bytes().startswith(intact_before_crash)

    reloaded = CampaignManager(store_path=store)
    campaign = reloaded.get_campaign("camp-1")
    assert campaign is not None
    assert campaign.status == CampaignStatus.PREFLIGHT.value
    assert len(reloaded.get_events()) == 2

    # The store keeps accepting writes past the torn tail...
    assert reloaded.transition_campaign("camp-1", CampaignStatus.AUTHORIZED.value, "t2")

    # ...and no history, old or new, is lost.
    final = CampaignManager(store_path=store)
    final_campaign = final.get_campaign("camp-1")
    assert final_campaign is not None
    assert final_campaign.status == CampaignStatus.AUTHORIZED.value
    assert len(final.get_events()) == 3


def test_crashed_mirror_replace_leaves_store_usable(tmp_path: Path) -> None:
    """A crash inside the write-then-replace mirror step leaves only a .tmp."""
    store = tmp_path / "campaigns.jsonl"
    manager = CampaignManager(store_path=store)
    manager.create_campaign(_make_campaign())
    mirror = tmp_path / "campaigns.mirror.jsonl"
    assert mirror.exists()  # mirror is rewritten atomically after each append

    # Crash artifact: the staged temp file was partially written, never renamed.
    (tmp_path / "campaigns.mirror.jsonl.tmp").write_bytes(b'{"seq": 1, "payload"')

    reloaded = CampaignManager(store_path=store)
    assert reloaded.get_campaign("camp-1") is not None
    assert reloaded.transition_campaign("camp-1", CampaignStatus.PREFLIGHT.value, "t1") is True


def test_mirror_fallback_when_primary_lost(tmp_path: Path) -> None:
    """If the primary file is deleted, the mirror restores full history."""
    store = tmp_path / "campaigns.jsonl"
    manager = CampaignManager(store_path=store)
    manager.create_campaign(_make_campaign())
    assert manager.transition_campaign("camp-1", CampaignStatus.PREFLIGHT.value, "t1")
    store.unlink()

    reloaded = CampaignManager(store_path=store)
    campaign = reloaded.get_campaign("camp-1")
    assert campaign is not None
    assert campaign.status == CampaignStatus.PREFLIGHT.value
    assert len(reloaded.get_events()) == 2


def test_illegal_transition_rejected_after_restart(tmp_path: Path) -> None:
    """Lifecycle enforcement still applies to reloaded campaign state."""
    store = tmp_path / "campaigns.jsonl"
    manager = CampaignManager(store_path=store)
    manager.create_campaign(_make_campaign())  # PLANNED
    assert manager.transition_campaign("camp-1", CampaignStatus.ACTIVE.value, "t1") is False

    restarted = CampaignManager(store_path=store)
    reloaded = restarted.get_campaign("camp-1")
    assert reloaded is not None
    assert reloaded.status == CampaignStatus.PLANNED.value
    assert reloaded.can_transition_to(CampaignStatus.ACTIVE.value) is False
    assert restarted.transition_campaign("camp-1", CampaignStatus.ACTIVE.value, "t2") is False
    assert restarted.get_campaign("camp-1").status == CampaignStatus.PLANNED.value
    assert any(e["event_type"] == "INVALID_TRANSITION" for e in restarted.get_events())
    # A legal transition still succeeds with reloaded state.
    assert restarted.transition_campaign("camp-1", CampaignStatus.PREFLIGHT.value, "t3") is True


def test_duplicate_record_replay_is_idempotent(tmp_path: Path) -> None:
    """A crash-retry that duplicates a record cannot change replayed state.

    Ack lost after a successful write means the store may hold the same
    record twice; replay must stay idempotent (campaigns are keyed by id, the
    last snapshot wins) and the store must keep accepting appends.
    """
    store = tmp_path / "campaigns.jsonl"
    manager = CampaignManager(store_path=store)
    manager.create_campaign(_make_campaign())
    assert manager.transition_campaign("camp-1", CampaignStatus.PREFLIGHT.value, "t1")
    before = manager.get_campaign("camp-1")
    assert before is not None
    before_record = before.to_record()

    # Crash-retry artifact: the tail record written a second time. Existing
    # bytes are only ever appended to, never rewritten.
    data = store.read_bytes()
    tail = data.splitlines(keepends=True)[-1]
    store.write_bytes(data + tail)

    first = CampaignManager(store_path=store)
    replayed = first.get_campaign("camp-1")
    assert replayed is not None
    assert replayed.to_record() == before_record
    assert [c.campaign_id for c in first.get_all_campaigns()] == ["camp-1"]
    assert len(first.get_campaigns_by_status(CampaignStatus.PREFLIGHT.value)) == 1

    # A second replay of the identical store is equally stable.
    second = CampaignManager(store_path=store)
    after_second = second.get_campaign("camp-1")
    assert after_second is not None
    assert after_second.to_record() == before_record
    assert [c.campaign_id for c in second.get_all_campaigns()] == ["camp-1"]

    # Appends continue past the duplicated line without losing history.
    assert second.transition_campaign("camp-1", CampaignStatus.AUTHORIZED.value, "t2") is True
    final = CampaignManager(store_path=store)
    final_campaign = final.get_campaign("camp-1")
    assert final_campaign is not None
    assert final_campaign.status == CampaignStatus.AUTHORIZED.value
    assert final_campaign.status_history == (
        (CampaignStatus.PREFLIGHT.value, "t1"),
        (CampaignStatus.AUTHORIZED.value, "t2"),
    )
    assert len(final.get_all_campaigns()) == 1


def test_duplicate_create_replay_is_idempotent(tmp_path: Path) -> None:
    """Replaying the same create keeps exactly one campaign, across restarts."""
    store = tmp_path / "campaigns.jsonl"
    manager = CampaignManager(store_path=store)
    manager.create_campaign(_make_campaign())
    manager.create_campaign(_make_campaign())  # retried create: ack was lost
    assert [c.campaign_id for c in manager.get_all_campaigns()] == ["camp-1"]
    created = manager.get_campaign("camp-1")
    assert created is not None
    assert created.status == CampaignStatus.PLANNED.value

    restarted = CampaignManager(store_path=store)
    assert [c.campaign_id for c in restarted.get_all_campaigns()] == ["camp-1"]
    reloaded = restarted.get_campaign("camp-1")
    assert reloaded is not None
    assert reloaded.status == CampaignStatus.PLANNED.value
    assert restarted.transition_campaign("camp-1", CampaignStatus.PREFLIGHT.value, "t1") is True
    assert len(CampaignManager(store_path=store).get_all_campaigns()) == 1


def test_history_survives_primary_loss_across_writes(tmp_path: Path) -> None:
    """A write after the primary is lost still keeps the full history on disk.

    Without the mirror restore, that write would start a new chain and the
    next restart would silently drop every mirrored record.
    """
    store = tmp_path / "campaigns.jsonl"
    manager = CampaignManager(store_path=store)
    manager.create_campaign(_make_campaign())
    assert manager.transition_campaign("camp-1", CampaignStatus.PREFLIGHT.value, "t1")
    store.unlink()  # cleanup job removes the primary; the mirror still has it

    reloaded = CampaignManager(store_path=store)
    assert reloaded.transition_campaign("camp-1", CampaignStatus.AUTHORIZED.value, "t2") is True

    final = CampaignManager(store_path=store)
    campaign = final.get_campaign("camp-1")
    assert campaign is not None
    assert campaign.status == CampaignStatus.AUTHORIZED.value
    assert campaign.status_history == (
        (CampaignStatus.PREFLIGHT.value, "t1"),
        (CampaignStatus.AUTHORIZED.value, "t2"),
    )
    assert len(final.get_all_campaigns()) == 1
    assert [e["event_type"] for e in final.get_events()] == [
        "CAMPAIGN_CREATED",
        "STATUS_CHANGED",
        "STATUS_CHANGED",
    ]
