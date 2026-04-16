from ai_accounts_core.services.chat_state import ChatStateService


def test_push_increments_seq():
    svc = ChatStateService()
    svc.init_session("s1")
    svc.push_event("s1", {"kind": "token", "payload": "hi"})
    svc.push_event("s1", {"kind": "token", "payload": "there"})
    log = svc.get_event_log("s1")
    assert len(log) == 2
    assert log[0]["_seq"] == 1
    assert log[1]["_seq"] == 2


def test_replay_from_cursor():
    svc = ChatStateService()
    svc.init_session("s1")
    for i in range(5):
        svc.push_event("s1", {"kind": "token", "payload": str(i)})
    replayed = svc.replay("s1", last_seq=3)
    assert len(replayed) == 2
    assert replayed[0]["_seq"] == 4
    assert replayed[1]["_seq"] == 5


def test_event_log_capped():
    svc = ChatStateService(max_events=10)
    svc.init_session("s1")
    for i in range(15):
        svc.push_event("s1", {"kind": "token", "payload": str(i)})
    log = svc.get_event_log("s1")
    assert len(log) == 10
    assert log[0]["_seq"] == 6


def test_replay_returns_full_log_when_cursor_evicted():
    svc = ChatStateService(max_events=5)
    svc.init_session("s1")
    for i in range(10):
        svc.push_event("s1", {"kind": "token", "payload": str(i)})
    replayed = svc.replay("s1", last_seq=2)
    assert len(replayed) == 5
    assert replayed[0]["_seq"] == 6


def test_remove_session():
    svc = ChatStateService()
    svc.init_session("s1")
    svc.push_event("s1", {"kind": "token", "payload": "x"})
    svc.remove_session("s1")
    assert svc.get_event_log("s1") == []


def test_push_on_unknown_session_is_noop():
    svc = ChatStateService()
    seq = svc.push_event("unknown", {"kind": "token"})
    assert seq == -1


def test_init_session_with_start_seq_seeds_counter():
    """After eviction + reconnect, init_session(start_seq=N) must cause
    the next push to return N+1 so client dedup sees strictly-greater seqs."""
    svc = ChatStateService()
    svc.init_session("s1", start_seq=42)
    first = svc.push_event("s1", {"kind": "token", "payload": "a"})
    assert first == 43
    second = svc.push_event("s1", {"kind": "token", "payload": "b"})
    assert second == 44


def test_push_on_unknown_session_logs_warning(caplog):
    """push_event on a missing session must log so orphaned events aren't silent."""
    import logging
    svc = ChatStateService()
    with caplog.at_level(logging.WARNING, logger="ai_accounts_core.services.chat_state"):
        seq = svc.push_event("ghost", {"kind": "token"})
    assert seq == -1
    assert any("ghost" in r.message for r in caplog.records)
