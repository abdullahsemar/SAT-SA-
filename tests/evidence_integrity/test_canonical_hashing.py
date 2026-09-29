"""Tests for canonical serialization, exact-byte hashing, and record commitments."""

from packages.evidence_integrity.canonical import (
    canonical_json_bytes,
    canonical_json_dumps,
    create_record_commitment,
    verify_record_commitment,
)
from packages.evidence_integrity.hashing import hash_bytes, hash_file


def test_canonical_json_key_sorting():
    obj1 = {"z": 1, "a": 2, "m": {"b": 3, "a": 4}}
    obj2 = {"a": 2, "m": {"a": 4, "b": 3}, "z": 1}
    assert canonical_json_dumps(obj1) == canonical_json_dumps(obj2)
    assert canonical_json_bytes(obj1) == canonical_json_bytes(obj2)


def test_canonical_json_unicode_nfc():
    # 'e' + combining acute accent vs precomposed 'é'
    decomposed = "e\u0301cole"
    precomposed = "\u00e9cole"
    assert decomposed != precomposed  # different code points
    # canonicalization normalizes NFC
    assert canonical_json_dumps({"name": decomposed}) == canonical_json_dumps({"name": precomposed})


def test_canonical_json_float_formatting():
    # Floating point numbers formatted deterministically (trailing zeros normalized)
    assert canonical_json_dumps({"val": 1.0}) == '{"val":1}'
    assert canonical_json_dumps({"val": 1.25}) == '{"val":1.25}'


def test_record_commitment_determinism():
    envelope1 = create_record_commitment(
        entity_id="E-101",
        submission_id="sub-001",
        record_id="rec-999",
        record_type="case",
        canonical_content={"status": "closed", "disposition": "benign"},
        nonce="fixed-test-nonce-12345",
    )
    envelope2 = create_record_commitment(
        entity_id="E-101",
        submission_id="sub-001",
        record_id="rec-999",
        record_type="case",
        canonical_content={"disposition": "benign", "status": "closed"},
        nonce="fixed-test-nonce-12345",
    )
    assert envelope1["commitment"] == envelope2["commitment"]
    assert verify_record_commitment(envelope1, envelope1["commitment"]) is True


def test_record_commitment_scope_and_field_modification():
    base_envelope = create_record_commitment(
        entity_id="E-101",
        submission_id="sub-001",
        record_id="rec-999",
        record_type="case",
        canonical_content={"status": "closed", "count": 10},
        nonce="fixed-nonce",
    )
    # Tampered entity
    tampered_entity = dict(base_envelope)
    tampered_entity["entity_id"] = "E-999"
    assert verify_record_commitment(tampered_entity, base_envelope["commitment"]) is False

    # Tampered content
    tampered_content = dict(base_envelope)
    tampered_content["canonical_content"] = {"status": "open", "count": 10}
    assert verify_record_commitment(tampered_content, base_envelope["commitment"]) is False

    # Tampered version
    tampered_ver = dict(base_envelope)
    tampered_ver["representation_version"] = "v2.0"
    assert verify_record_commitment(tampered_ver, base_envelope["commitment"]) is False


def test_exact_byte_versus_canonical_record_hashing(tmp_path):
    raw_content_1 = b'{"case_id": "1",   "summary": "Alert 1"}\n'
    raw_content_2 = b'{"case_id":"1","summary":"Alert 1"}'

    # Raw file digests must differ because byte streams differ
    hash1 = hash_bytes(raw_content_1)
    hash2 = hash_bytes(raw_content_2)
    assert hash1 != hash2

    # Canonical record commitments over parsed structured records must match
    rec1 = {"case_id": "1", "summary": "Alert 1"}
    rec2 = {"summary": "Alert 1", "case_id": "1"}
    comm1 = create_record_commitment("E-1", "S-1", "1", "case", rec1, nonce="nonce-1")
    comm2 = create_record_commitment("E-1", "S-1", "1", "case", rec2, nonce="nonce-1")
    assert comm1["commitment"] == comm2["commitment"]


def test_streaming_file_hash(tmp_path):
    test_file = tmp_path / "test.bin"
    data = b"NCIIPC_AUDIT_DATA_" * 5000
    test_file.write_bytes(data)

    digest_stream = hash_file(str(test_file))
    digest_direct = hash_bytes(data)
    assert digest_stream == digest_direct
