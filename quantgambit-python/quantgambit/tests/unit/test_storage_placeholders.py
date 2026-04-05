from quantgambit.storage.redis_streams import Command, CommandResult, Event
from quantgambit.storage.postgres import CommandAuditRecord
from quantgambit.storage.wal import WalEntry


def test_command_dataclass():
    cmd = Command(
        command_id="1",
        type="PAUSE",
        scope={"bot_id": "qg-1"},
        requested_by="tester",
        requested_at="2025-01-01T00:00:00Z",
    )
    assert cmd.command_id == "1"


def test_command_result_dataclass():
    result = CommandResult(
        command_id="1",
        status="accepted",
        message="ok",
        executed_at="2025-01-01T00:00:00Z",
    )
    assert result.status == "accepted"


def test_event_dataclass():
    event = Event(
        event_id="1",
        event_type="decision",
        schema_version="v1",
        timestamp="2025-01-01T00:00:00Z",
        ts_recv_us=0,
        ts_canon_us=0,
        ts_exchange_s=None,
        bot_id="qg-1",
        payload={"stage": "Signal"},
    )
    assert event.event_type == "decision"


def test_command_audit_record():
    record = CommandAuditRecord(
        command_id="1",
        type="PAUSE",
        scope={"bot_id": "qg-1"},
        requested_by="tester",
        requested_at="2025-01-01T00:00:00Z",
        status="accepted",
    )
    assert record.type == "PAUSE"


def test_wal_entry():
    entry = WalEntry(
        sequence_id=1,
        event_type="order",
        timestamp="2025-01-01T00:00:00Z",
        payload={"order_id": "abc"},
    )
    assert entry.sequence_id == 1
