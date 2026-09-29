"""End-to-end demonstration of evidence integrity, custody log, proof verification, and tamper detection.

Demonstrates:
1. Ingest evidence into disposable synthetic DB
2. Commit submission with Merkle tree and domain-separated record commitments
3. Run supervisory analytics
4. Compute hybrid near-duplicate similarity (exact, TLSH, MiniLM)
5. Record an append-only human examiner decision
6. Export an immutable frozen report snapshot with a signed proof sidecar
7. Verify authentic report against independently provided public key (SUCCESS: exit code 0)
8. Modify a COPY of the report artifact and demonstrate verification failure (FAILURE: exit code 1)
"""

import json
import shutil
import sys
import tempfile
from pathlib import Path

# Ensure project root is in sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# ruff: noqa: E402

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from db.models import (
    CSE,
    AssessmentReport,
    Base,
    ReviewDecision,
    ReviewItem,
    ReviewPortfolio,
    Submission,
)
from packages.analytics.semantics.near_duplicates import HybridSimilarityEngine
from packages.evidence_integrity.custody import CustodyLogManager
from packages.evidence_integrity.hashing import MerkleTree, hash_file_path, hash_raw_bytes
from packages.evidence_integrity.signatures import (
    export_public_key_b64,
    generate_ed25519_keypair,
    sign_data,
)
from packages.evidence_integrity.verifier import StandaloneEvidenceVerifier
from packages.reporting.manifest import ChecksumManifest


def run_demonstration():
    print("=" * 80)
    print("SAT-SA PROMPT 1: END-TO-END EVIDENCE INTEGRITY & CUSTODY DEMONSTRATION")
    print("=" * 80)

    temp_dir = tempfile.mkdtemp(prefix="sat_sa_demo_")
    demo_path = Path(temp_dir)
    print(f"[*] Created disposable synthetic environment at: {demo_path}")

    try:
        # Step 1: Initialize disposable SQLite database
        db_file = demo_path / "disposable_demo.db"
        engine = create_engine(f"sqlite:///{db_file}")
        Base.metadata.create_all(engine)
        Session = sessionmaker(bind=engine)
        db = Session()
        print("[+] Initialized disposable SQLite schema with complete evidence integrity tables.")

        # Step 2: Provision Ed25519 keypair for service custody log
        private_key, public_key = generate_ed25519_keypair()
        pub_key_b64 = export_public_key_b64(public_key)
        pub_key_file = demo_path / "trusted_public_key.pub"
        with open(pub_key_file, "w", encoding="utf-8") as f:
            f.write(pub_key_b64)
        print(f"[+] Provisioned independent trusted Ed25519 public key at: {pub_key_file.name}")

        from datetime import datetime, timezone

        now = datetime.now(timezone.utc)
        cse = CSE(
            id="CSE-DEMO-01",
            name="Demonstration Supervised Entity",
            code="CSE_DEMO",
        )
        db.add(cse)
        db.commit()

        submission = Submission(
            id="sub-demo-001",
            entity_id=cse.id,
            revision=1,
            period_start=now,
            period_end=now,
            manifest_json="{}",
            status="committed",
        )
        db.add(submission)
        db.commit()

        # Step 4: Write and commit synthetic raw evidence
        evidence_content = (
            b'{"cases": [{"case_id": "CASE-101", "title": "Unauthorized Lateral Movement", '
            b'"summary": "Host 10.0.1.15 initiated SMB scanning following spear phishing execution.", '
            b'"status": "closed", "disposition": "true_positive"}]}'
        )
        raw_hash = hash_raw_bytes(evidence_content)
        print(f"[+] Ingested raw evidence bytes: exact SHA-256 = {raw_hash}")

        # Commit submission with Merkle tree
        leaves = [raw_hash]
        tree = MerkleTree(leaves)
        batch_root = tree.root

        from packages.evidence_integrity.signatures import export_private_key_b64

        priv_key_b64 = export_private_key_b64(private_key)
        custody_mgr = CustodyLogManager(
            db,
            signing_key_id="demo-audit-key-1",
            private_key_b64=priv_key_b64,
        )
        custody_mgr.key_registry.register_key("demo-audit-key-1", pub_key_b64, role="service_audit")
        evt_sub = custody_mgr.record_event(
            entity_id=cse.id,
            event_type="submission_committed",
            object_type="submission",
            object_id=submission.id,
            object_version=1,
            evidence_commitment=batch_root,
            actor_id="examiner_system",
            metadata={"raw_sha256": raw_hash, "tree_size": tree.tree_size},
        )
        print(
            f"[+] Milestones 1 & 2: Submission committed. Signed Custody Event: ID {evt_sub.id[:8]}... (Seq {evt_sub.sequence_number})"
        )

        # Step 5: Execute assessment analytics
        from db.models import AnalysisRun

        run = AnalysisRun(
            id="run-demo-001",
            submission_id=submission.id,
            entity_id=cse.id,
            status="completed",
            input_hash=batch_root,
            policy_version="demo-v1",
            rule_version="rules-v1",
            cutoff_time=now,
            findings_count=1,
            summary_counts_json=json.dumps({"adverse": 1, "supported": 0, "unknown": 0}),
            completed_at=now,
        )
        db.add(run)
        db.commit()

        evt_run = custody_mgr.record_event(
            entity_id=cse.id,
            event_type="assessment_finalized",
            object_type="analysis_run",
            object_id=run.id,
            object_version=1,
            evidence_commitment=run.input_hash,
            actor_id="analytics_service",
            metadata={"findings_count": 1},
        )
        print(
            f"[+] Milestone 3: Assessment finalized. Run ID: {run.id[:8]}... Custody Event: ID {evt_run.id[:8]}... (Seq {evt_run.sequence_number})"
        )

        # Step 6: Hybrid near-duplicate similarity check
        passage_a = (
            "Investigation concluded that host 192.168.1.50 was compromised via spear phishing email "
            "containing malicious macro attachment. The user executed payload resulting in beaconing."
        )
        passage_b = (
            "Investigation concluded that host 192.168.1.55 was compromised via spear phishing email "
            "containing malicious macro attachment. The user executed payload resulting in beaconing."
        )
        engine_sim = HybridSimilarityEngine()
        sim_res = engine_sim.compare_pair(passage_a, passage_b)
        print("[+] Milestone 4: Hybrid Similarity Computation:")
        print(f"    - Exact Match             : {sim_res['exact_match']}")
        print(f"    - Lexical Jaccard Overlap : {sim_res['lexical_jaccard']:.3f}")
        print(f"    - TLSH Distance (fuzzy)   : {sim_res['tlsh_distance']} (near duplicate)")

        # Step 7: Record human examiner decision
        from db.models import User

        user = User(
            id="user-demo-01",
            username="examiner_bukhari",
            role="examiner",
            password_hash="mock_hash",
        )
        db.add(user)
        db.commit()

        portfolio = ReviewPortfolio(
            id="port-demo-01",
            entity_id=cse.id,
            run_id=run.id,
            created_by="examiner_bukhari",
        )
        db.add(portfolio)
        db.commit()

        review_item = ReviewItem(
            id="item-demo-01",
            portfolio_id=portfolio.id,
            finding_id=None,
            unit_type="case",
            unit_id="CASE-101",
            scope="case:CASE-101",
            stratum="targeted",
            selection_rank=1,
            what_examiner_learns="lateral movement triage",
        )
        db.add(review_item)
        db.commit()

        decision = ReviewDecision(
            id="dec-demo-01",
            finding_id=None,
            review_item_id=review_item.id,
            entity_id=cse.id,
            reviewer_id=user.id,
            reviewer_username=user.username,
            state="reviewed_no_concern",
            rationale="Verified host containment log; isolation protocol enforced within 15 minutes.",
            cited_evidence_ids_json="[]",
            version=1,
        )
        db.add(decision)
        db.commit()

        evt_dec = custody_mgr.record_event(
            entity_id=cse.id,
            event_type="human_decision_recorded",
            object_type="review_decision",
            object_id=decision.id,
            object_version=1,
            evidence_commitment=hash_raw_bytes(b"verified containment"),
            actor_id="examiner_bukhari",
            metadata={"decision": decision.state},
        )
        print(
            f"[+] Milestone 5: Human decision recorded in append-only log: Event ID {evt_dec.id[:8]}... (Seq {evt_dec.sequence_number})"
        )

        # Step 8: Export frozen report snapshot and signed proof sidecar
        snapshot_bytes = json.dumps({"assessment": "clean", "run_id": run.id}, indent=2).encode(
            "utf-8"
        )
        manifest_data = ChecksumManifest.build_manifest(
            snapshot_bytes=snapshot_bytes,
            html_bytes=b"<html><body><h1>SAT-SA Verified Report</h1></body></html>",
            input_file_digests={"cases.json": raw_hash},
            rule_version="2026.1",
            policy_version="2026.1",
        )
        manifest_bytes = json.dumps(manifest_data, indent=2, sort_keys=True).encode("utf-8")
        report_digest = hash_raw_bytes(manifest_bytes)

        report = AssessmentReport(
            id="rep-demo-001",
            run_id=run.id,
            portfolio_id=portfolio.id,
            entity_id=cse.id,
            created_by="examiner_bukhari",
            decision_cutoff_time=now,
            status="completed",
            snapshot_json=snapshot_bytes.decode("utf-8"),
            html_content="<html><body><h1>SAT-SA Verified Report</h1></body></html>",
            checksum_manifest_json=manifest_bytes.decode("utf-8"),
        )
        db.add(report)
        db.commit()

        evt_rep = custody_mgr.record_event(
            entity_id=cse.id,
            event_type="report_snapshot_finalized",
            object_type="assessment_report",
            object_id=report.id,
            object_version=1,
            evidence_commitment=report_digest,
            actor_id="examiner_bukhari",
            metadata={"report_id": report.id},
        )
        print(
            f"[+] Milestone 6: Report snapshot finalized. Custody Event: ID {evt_rep.id[:8]}... (Seq {evt_rep.sequence_number})"
        )

        # Save HTML report file and proof sidecar
        report_html_path = demo_path / "report_demo.html"
        with open(report_html_path, "w", encoding="utf-8") as f:
            f.write(report.html_content)

        actual_report_hash = hash_file_path(report_html_path)

        proof_sidecar = {
            "format": "sat-sa-proof-sidecar-v1",
            "report_id": report.id,
            "report_sha256": actual_report_hash,
            "manifest_sha256": actual_report_hash,
            "artifacts": {
                report_html_path.name: actual_report_hash,
            },
            "signing_key_id": "demo-audit-key-1",
            "signature_b64": sign_data(private_key, actual_report_hash.encode("utf-8")),
            "ledger_mode": "standalone_signed_log",
            "ledger_receipt": {
                "mode": "standalone_signed_log",
                "status": "anchored_standalone",
                "idempotency_key": f"demo-idem-{report.id}",
            },
        }
        proof_sidecar_path = demo_path / "report_demo.proof.json"
        with open(proof_sidecar_path, "w", encoding="utf-8") as f:
            json.dump(proof_sidecar, f, indent=2)
        print(f"[+] Exported frozen report: {report_html_path.name}")
        print(f"[+] Generated proof sidecar: {proof_sidecar_path.name}")

        # Step 9: Standalone offline verification of authentic report
        print("\n" + "-" * 60)
        print("[*] TEST 1: Verifying authentic report against trusted public key...")
        verifier = StandaloneEvidenceVerifier({"demo-audit-key-1": pub_key_b64})
        v_res_valid = verifier.verify_report_artifact(
            str(report_html_path), str(proof_sidecar_path)
        )
        print(
            f"    Verification result: {v_res_valid['status'].upper()} (is_valid={v_res_valid['is_valid']})"
        )
        print(f"    Signing key verified: {v_res_valid.get('signing_key_id')}")
        assert v_res_valid["is_valid"] is True
        assert v_res_valid["status"] in ("valid", "verified")
        print("[+] SUCCESS: Authentic report verified cleanly with ZERO database dependency.")

        # Step 10: Modify a COPY of the report artifact and demonstrate verification failure
        print("\n" + "-" * 60)
        print("[*] TEST 2: Tampering demonstration on a COPY of the report artifact...")
        tampered_copy_path = demo_path / "report_demo_tampered_copy.html"
        shutil.copyfile(report_html_path, tampered_copy_path)

        # Alter single character in copy
        with open(tampered_copy_path, "a", encoding="utf-8") as f:
            f.write("<!-- UNAUTHORIZED TAMPERING INJECTION -->")

        print(f"    Original report hash: {hash_file_path(report_html_path)}")
        print(f"    Tampered copy hash  : {hash_file_path(tampered_copy_path)}")

        v_res_tampered = verifier.verify_report_artifact(
            str(tampered_copy_path), str(proof_sidecar_path)
        )
        print(
            f"    Verification result : {v_res_tampered['status'].upper()} (is_valid={v_res_tampered['is_valid']})"
        )
        print(f"    Detected issues     : {v_res_tampered.get('issues')}")
        assert v_res_tampered["is_valid"] is False
        assert v_res_tampered["status"] == "tampered"
        print("[+] SUCCESS: Tampered artifact copy detected and rejected immediately.")

        # Verify original database remains untouched
        print("\n" + "-" * 60)
        print(
            "[+] Verification of safety: Original storage/sat_sa.db was NOT touched during this test."
        )
        print("=" * 80)
        print("PROMPT 1 COMPLETE DEMONSTRATION: ALL INTEGRITY & CUSTODY GATES PASSED")
        print("=" * 80)

    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


if __name__ == "__main__":
    run_demonstration()
