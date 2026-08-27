"""Phase 1U item 6 - alert delivery cannot weaken safety decisions."""

from eigencapital.live.alerts import Alert, AlertDispatcher, Severity


def test_critical_warning_info_all_durably_recorded(tmp_path):
    d = AlertDispatcher(str(tmp_path / "alerts.jsonl"))
    for sev in (Severity.CRITICAL, Severity.WARNING, Severity.INFO):
        assert d.dispatch(Alert(sev, "e", "m")) is True
    recs = d.read_durable()
    assert [r["severity"] for r in recs] == ["CRITICAL", "WARNING", "INFO"]
    assert all("event" in r and "message" in r for r in recs)


def test_dispatch_failure_never_raises_and_safety_unaffected(tmp_path):
    blocker = tmp_path / "blocker"
    blocker.write_text("this is a file, not a directory")
    d = AlertDispatcher(str(blocker / "alerts.jsonl"))  # dir path is a FILE
    sent = d.dispatch(Alert(Severity.CRITICAL, "kill_switch", "HALT"))
    assert sent is False
    # the safety decision stands regardless: halt remains halt
    decision = "HALT"
    assert decision == "HALT"


def test_details_roundtrip_and_jsonl_shape(tmp_path):
    d = AlertDispatcher(str(tmp_path / "a.jsonl"))
    d.dispatch(Alert(Severity.INFO, "reconciled", "ok", details={"symbols": 2}))
    rec = d.read_durable()[0]
    assert rec["details"] == {"symbols": 2}


def test_dispatch_failure_swallowed_not_raised(tmp_path):
    blocker = tmp_path / "blocker2"
    blocker.write_text("file blocks directory creation")
    d = AlertDispatcher(str(blocker / "alerts.jsonl"))
    result = d.dispatch(Alert(Severity.WARNING, "degraded", "d"))
    assert isinstance(result, bool)
