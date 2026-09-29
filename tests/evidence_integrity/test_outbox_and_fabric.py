"""Tests for transactional outbox processing and Fabric gateway adapter."""

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from db.models.evidence_integrity import CustodyEvent, LedgerOutbox
from db.session import Base
from packages.evidence_integrity.fabric_client import FabricGatewayClient
from packages.evidence_integrity.outbox import OutboxProcessor


def test_fabric_client_standalone_mode():
    client = FabricGatewayClient(configured=False)
    assert client.mode == "standalone_signed_log"

    # In standalone mode, submit_anchor returns a signed local receipt without external network call
    receipt = client.submit_anchor(
        idempotency_key="idem-12345",
        event_id="ev-001",
        event_type="submission_committed",
        entity_id="E-101",
        sequence_number=1,
        evidence_commitment="commit_abc123",
        actor_id="examiner-1",
        signing_key_id="test-key",
        signature="sig-abc",
    )
    assert receipt["status"] == "anchored_standalone"
    assert receipt["mode"] == "standalone_signed_log"
    assert receipt["idempotency_key"] == "idem-12345"


def test_outbox_processor_processing(tmp_path):
    db_file = tmp_path / "outbox_test.db"
    engine = create_engine(f"sqlite:///{db_file}")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()

    # Insert prerequisite CustodyEvent to satisfy foreign key constraint
    import datetime

    now = datetime.datetime.now(datetime.timezone.utc)
    evt = CustodyEvent(
        id="ev-999",
        entity_id="E-101",
        event_type="assessment_finalized",
        sequence_number=1,
        previous_event_commitment="0" * 64,
        object_type="assessment",
        object_id="assess-999",
        object_version=1,
        evidence_commitment="commit_999",
        claimed_event_time=now,
        actor_id="examiner-1",
        signing_key_id="key-1",
        signature="sig-999",
        payload_digest="0" * 64,
    )
    session.add(evt)
    session.commit()

    # Insert a pending outbox entry
    entry = LedgerOutbox(
        event_id="ev-999",
        entity_id="E-101",
        event_type="assessment_finalized",
        idempotency_key="idempotency_key_test_999",
        payload={
            "event_id": "ev-999",
            "entity_id": "E-101",
            "event_type": "assessment_finalized",
            "sequence_number": 1,
            "evidence_commitment": "commit_999",
            "actor_id": "examiner-1",
            "signing_key_id": "key-1",
            "signature": "sig-999",
        },
        status="pending",
    )
    session.add(entry)
    session.commit()

    # Process outbox
    client = FabricGatewayClient(configured=False)
    processor = OutboxProcessor(session, client)
    stats = processor.process_pending_entries(batch_size=10)

    assert stats["processed"] == 1
    assert stats["errors"] == 0

    # Verify status updated to anchored in database
    session.refresh(entry)
    assert entry.status == "anchored"
    assert entry.receipt is not None
    assert entry.anchored_at is not None

    session.close()


def test_outbox_retry_and_backoff(tmp_path):
    db_file = tmp_path / "outbox_retry_test.db"
    engine = create_engine(f"sqlite:///{db_file}")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()

    import datetime

    now = datetime.datetime.now(datetime.timezone.utc)
    evt_fail = CustodyEvent(
        id="ev-fail-1",
        entity_id="E-101",
        event_type="assessment_finalized",
        sequence_number=1,
        previous_event_commitment="0" * 64,
        object_type="assessment",
        object_id="assess-fail-1",
        object_version=1,
        evidence_commitment="commit_fail_1",
        claimed_event_time=now,
        actor_id="examiner-1",
        signing_key_id="key-1",
        signature="sig-fail-1",
        payload_digest="0" * 64,
    )
    session.add(evt_fail)
    session.commit()

    entry = LedgerOutbox(
        event_id="ev-fail-1",
        entity_id="E-101",
        event_type="assessment_finalized",
        idempotency_key="idempotency_fail_1",
        payload={"event_id": "ev-fail-1"},
        status="pending",
    )
    session.add(entry)
    session.commit()

    # Mock client that raises an exception simulating network outage
    class FailingFabricClient:
        mode = "fabric_anchored"

        def submit_anchor(self, **kwargs):
            raise ConnectionError("Simulated peer network timeout")

    processor = OutboxProcessor(session, FailingFabricClient())
    stats = processor.process_pending_entries(batch_size=10)

    assert stats["processed"] == 0
    assert stats["errors"] == 1

    session.refresh(entry)
    assert entry.retry_count == 1
    assert entry.last_error == "Simulated peer network timeout"
    # Status remains pending until max retries reached
    assert entry.status in ("pending", "pending_anchor")

    session.close()
