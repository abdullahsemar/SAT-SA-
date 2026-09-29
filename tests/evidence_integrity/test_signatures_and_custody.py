"""Tests for Ed25519 signatures, custody log hash chaining, and rollback detection."""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from db.session import Base
from packages.evidence_integrity.custody import (
    CustodyEventVerificationError,
    CustodyLogManager,
)
from packages.evidence_integrity.signatures import (
    KeyRegistry,
    export_private_key_b64,
    export_public_key_b64,
    generate_ed25519_keypair,
    sign_data,
    verify_signature,
)


def test_ed25519_sign_and_verify():
    priv, pub = generate_ed25519_keypair()
    data = b"NCIIPC Supervisory Assessment Commitment Payload"
    sig = sign_data(priv, data)

    # Valid verification
    assert verify_signature(pub, data, sig) is True

    # Tampered data
    assert verify_signature(pub, data + b"!", sig) is False

    # Substituted key
    _, other_pub = generate_ed25519_keypair()
    assert verify_signature(other_pub, data, sig) is False


def test_key_registry_and_rotation():
    registry = KeyRegistry()
    priv1, pub1 = generate_ed25519_keypair()
    pub1_b64 = export_public_key_b64(pub1)
    registry.register_key("service-key-2026-v1", pub1_b64, owner="SAT-SA Service")

    # Rotate to v2
    priv2, pub2 = generate_ed25519_keypair()
    pub2_b64 = export_public_key_b64(pub2)
    registry.register_key("service-key-2026-v2", pub2_b64, owner="SAT-SA Service")

    # Sign with v1
    data1 = b"Event from Q1 2026"
    sig1 = sign_data(priv1, data1)
    assert registry.verify("service-key-2026-v1", data1, sig1) is True

    # Sign with v2
    data2 = b"Event from Q2 2026"
    sig2 = sign_data(priv2, data2)
    assert registry.verify("service-key-2026-v2", data2, sig2) is True

    # Cross-key mismatch fails
    assert registry.verify("service-key-2026-v1", data2, sig2) is False


def test_custody_log_append_and_verification(tmp_path):
    db_file = tmp_path / "custody_test.db"
    engine = create_engine(f"sqlite:///{db_file}")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()

    priv, pub = generate_ed25519_keypair()
    priv_b64 = export_private_key_b64(priv)
    pub_b64 = export_public_key_b64(pub)

    manager = CustodyLogManager(session, signing_key_id="test-key-v1", private_key_b64=priv_b64)

    # 1. Submission committed
    ev1 = manager.record_event(
        entity_id="E-101",
        event_type="submission_committed",
        object_type="submission",
        object_id="sub-001",
        object_version=1,
        evidence_commitment="commit_sub_001_root_hash",
        actor_id="examiner-bukhari",
    )
    assert ev1.sequence_number == 1
    assert ev1.previous_event_commitment == "0" * 64

    # 2. Assessment finalized
    ev2 = manager.record_event(
        entity_id="E-101",
        event_type="assessment_finalized",
        object_type="assessment_run",
        object_id="run-001",
        object_version=1,
        evidence_commitment="commit_run_001_findings_root",
        actor_id="examiner-bukhari",
    )
    assert ev2.sequence_number == 2
    assert ev2.previous_event_commitment == ev1.payload_digest

    # 3. Decision recorded
    ev3 = manager.record_event(
        entity_id="E-101",
        event_type="human_decision_recorded",
        object_type="review_decision",
        object_id="dec-001",
        object_version=1,
        evidence_commitment="commit_dec_001",
        actor_id="examiner-bukhari",
    )
    assert ev3.sequence_number == 3
    assert ev3.previous_event_commitment == ev2.payload_digest

    # Verify log integrity
    valid, issues = manager.verify_log("E-101", public_key_b64=pub_b64)
    assert valid is True
    assert len(issues) == 0

    # Test rollback / truncation detection
    # If an external auditor expects sequence 3, but the log only had sequence 2:
    with pytest.raises(CustodyEventVerificationError, match="Rollback detected"):
        manager.verify_log("E-101", expected_sequence=5, public_key_b64=pub_b64)

    session.close()
