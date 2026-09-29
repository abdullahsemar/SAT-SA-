"""Tests for report snapshot immutability, sidecar verification, and tamper detection."""

import json

from packages.evidence_integrity.hashing import hash_bytes
from packages.evidence_integrity.signatures import (
    export_public_key_b64,
    generate_ed25519_keypair,
    sign_data,
)
from packages.evidence_integrity.verifier import StandaloneEvidenceVerifier


def test_report_proof_sidecar_verification_and_tamper_detection(tmp_path):
    # Setup report directory with frozen snapshot artifacts
    report_dir = tmp_path / "report_001"
    report_dir.mkdir()

    html_file = report_dir / "report.html"
    json_file = report_dir / "report.json"
    manifest_file = report_dir / "checksums.sha256"
    sidecar_file = report_dir / "proof_sidecar.json"

    html_bytes = b"<html><body><h1>Supervisory Assessment Report E-101</h1></body></html>"
    json_bytes = b'{"entity_id": "E-101", "period": "2026-Q1", "metrics": {"total_findings": 3}}'

    html_file.write_bytes(html_bytes)
    json_file.write_bytes(json_bytes)

    html_hash = hash_bytes(html_bytes)
    json_hash = hash_bytes(json_bytes)

    manifest_lines = f"{html_hash}  report.html\n{json_hash}  report.json\n"
    manifest_file.write_text(manifest_lines)
    manifest_hash = hash_bytes(manifest_lines.encode("utf-8"))

    # Generate authority keypair
    priv, pub = generate_ed25519_keypair()
    pub_b64 = export_public_key_b64(pub)

    # Sign the manifest digest
    manifest_sig = sign_data(priv, manifest_hash.encode("utf-8"))

    # Create proof sidecar
    sidecar_data = {
        "report_id": "rep-001",
        "entity_id": "E-101",
        "manifest_sha256": manifest_hash,
        "signing_key_id": "service-key-2026",
        "service_public_key_b64": pub_b64,
        "signature_b64": manifest_sig,
        "artifacts": {
            "report.html": html_hash,
            "report.json": json_hash,
        },
    }
    sidecar_file.write_text(json.dumps(sidecar_data, indent=2))

    verifier = StandaloneEvidenceVerifier(trusted_public_keys={"service-key-2026": pub_b64})

    # 1. Verify original pristine bundle
    res_valid = verifier.verify_report_artifact(
        str(html_file),
        sidecar_path=str(sidecar_file),
        expected_key_id="service-key-2026",
    )
    assert res_valid["is_valid"] is True
    assert res_valid["status"] == "valid"

    # 2. Tamper with a COPY of report.html
    tampered_html_file = tmp_path / "report_tampered" / "report.html"
    tampered_html_file.parent.mkdir()
    tampered_html_file.write_bytes(html_bytes + b"<!-- Malicious Injected Content -->")

    res_tampered = verifier.verify_report_artifact(
        str(tampered_html_file),
        sidecar_path=str(sidecar_file),
        expected_key_id="service-key-2026",
    )
    assert res_tampered["is_valid"] is False
    assert res_tampered["status"] == "tampered"
    assert any("SHA-256 hash mismatch" in issue for issue in res_tampered["issues"])

    # 3. Substituted key
    _, other_pub = generate_ed25519_keypair()
    other_pub_b64 = export_public_key_b64(other_pub)
    verifier_wrong_key = StandaloneEvidenceVerifier(
        trusted_public_keys={"service-key-2026": other_pub_b64}
    )

    res_wrong_key = verifier_wrong_key.verify_report_artifact(
        str(html_file),
        sidecar_path=str(sidecar_file),
        expected_key_id="service-key-2026",
    )
    assert res_wrong_key["is_valid"] is False
    assert res_wrong_key["status"] == "invalid_signature"
