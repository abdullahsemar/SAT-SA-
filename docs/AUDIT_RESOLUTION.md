# 13-Item Audit Defect Resolution Table

## Historical Context & Baseline

The September 2026 supervisory audit (`SAT-SA-Audit-2026-09-26.md`) documented 13 architectural, analytical, and cryptographic defect areas across the prototype. 

In accordance with Section 2 of Prompt 1:
- The historical audit is treated as evidentiary baseline, not assumption of ongoing failure.
- Current code, regression tests, and cryptographic implementations have been verified independently.
- The 13 findings are cataloged below with direct links to implementation modules, regression test evidence, and documented limitations.

---

## Audit Defect Resolution Matrix

| # | Audit Finding / Defect Area | Root Cause in Prototype | Current Implementation & Fix | Regression Evidence | Remaining Limitations |
| :-: | :--- | :--- | :--- | :--- | :--- |
| **1** | **Entity Scope Bleed & Cross-Entity Access** | API routes lacked server-side entity filtering and allowed path traversals. | Server-side entity authorization enforced in `apps/api/auth.py` and all routes in `apps/api/routes/`. Cross-entity access returns HTTP 403. | `tests/integration/test_audit_regressions.py::test_scoped_analytics` | Entity admin cannot reassign records across entities without supervisory re-ingestion. |
| **2** | **Partial Escalation Treated as Absence** | An incomplete escalation file caused rules to treat missing alerts as proven non-escalated. | `EscalationEvidenceDetector` checks source completeness declarations; partial exports yield `insufficient_evidence` rather than adverse finding. | `tests/integration/test_audit_regressions.py::test_partial_escalations_do_not_prove_absence` | Relies on accurate manifest declarations of declared row count and export scope. |
| **3** | **Incomplete Denominator in KPI Reconciliation** | Unknown or missing alert outcomes produced speculative compliance rates. | `KPIReconciliationDetector` calculates bounded intervals; if denominator is incomplete, rate is marked `insufficient_evidence`. | `tests/analytics/test_phase_a_regressions.py` (Criterion 6 & 7) | Upper and lower interval bounds require at least one verified sample. |
| **4** | **Future-Due Obligations Flagged Overdue** | Assessments flagged active SLAs whose due date had not elapsed at cutoff time. | `ObligationEvaluator` compares SLA due time strictly against `decision_cutoff_time`. Future-due items produce no adverse finding. | `tests/analytics/test_phase_a_regressions.py` (Criterion 11) | Clock skew in entity timestamps is flagged as a quality issue during intake. |
| **5** | **Empty Complete Export vs Incomplete Export** | Zero-row exports were flagged as missing files rather than legitimate clean periods. | `ManifestDeclaration` distinguishes empty complete exports (`actual_row_count=0`, status `PRESENT`) from missing files. | `tests/integration/test_audit_regressions.py::test_valid_empty_complete_exports` | Supervised entity must explicitly declare zero rows in manifest. |
| **6** | **Quarantined Records Population Skew** | Malformed rows dropped silently during intake without adjusting population count. | `IngestionService` explicitly tracks `quarantined_count` and `rejected_count` in `QualityReport` and factors them into completeness. | `tests/integration/test_audit_regressions.py::test_quarantined_records_affecting_population_completeness` | Quarantined records require corrective submission to be analyzed. |
| **7** | **Policy Exception Validity Boundaries** | Exceptions granted after incident occurrence were erroneously applied retroactively. | `ObligationEvaluator` checks temporal overlap: exception start $\le$ event timestamp $\le$ exception expiry. | `tests/integration/test_audit_regressions.py::test_policy_exceptions_at_validity_boundaries` | Expired exceptions must be explicitly renewed by entity risk authority. |
| **8** | **Unflagged Review Items Missing Decisions** | Examiner workspace required machine findings to attach human review determinations. | Review items support independent human review decisions and local evidence requests without manufactured machine findings. | `tests/integration/test_migration_acceptance.py` (Steps 8-10) | Examiner must record explicit rationale text when overriding. |
| **9** | **Citations with Placeholder Hashes** | Prototype emitted dummy record IDs (`dummy`, `null`) and constant hashes (`0*64`). | `evaluation/citations.py` verifies physical files, recomputes SHA-256, and validates foreign key existence in database. | `tests/integration/test_citation_validation.py` (8 negative regression tests) | Offline files must remain stored in `storage/evidence/` for citation audit. |
| **10** | **Historical Reports Mutated Post-Cutoff** | Adding a human decision or receipt after report generation modified existing report HTML/JSON. | Frozen snapshots: report HTML, JSON, and `checksums.sha256` are byte-immutable. Later decisions or proofs are attached as linked sidecars. | `tests/evidence_integrity/test_report_sidecar_proof.py::test_report_proof_sidecar_verification_and_tamper_detection` | Requires examiners to generate a new report version for revised periods. |
| **11** | **Fuzzy Hash Conflated with Cryptographic Proof** | TLSH and embeddings were described in early docs as evidence verification hashes. | Strict architectural separation: exact-byte SHA-256 for files, canonical JSON for records, TLSH/embeddings strictly for similarity. | `tests/evidence_integrity/test_canonical_hashing.py::test_exact_byte_versus_canonical_record_hashing` | TLSH distance is non-cryptographic and cannot prove byte-level integrity. |
| **12** | **Simulated Blockchain Badges in Offline Mode** | UI displayed "Blockchain Verified" even when running locally without a live ledger. | Dual mode architecture: explicit badges for `Standalone Signed Log` (Ed25519) vs `Hyperledger Fabric Anchored`. No false badges. | `tests/evidence_integrity/test_outbox_and_fabric.py::test_fabric_client_standalone_mode` | Fabric mode requires Docker daemon with elevated permissions on host. |
| **13** | **Text Normalization Inverting Negations** | Stop-word removal stripped critical operational words (`not`, `failed`, `blocked`). | `HybridSimilarityEngine.normalize_text` explicitly preserves operational outcome keywords and negation markers. | `tests/evidence_integrity/test_hybrid_similarity.py::test_negation_and_operational_words_preservation` | Complex double negatives require human examiner context interpretation. |

---

## Verification & Regression Status

All 13 defect areas have dedicated automated regression tests in the test suite (`tests/integration/test_audit_regressions.py`, `tests/analytics/test_phase_a_regressions.py`, `tests/integration/test_citation_validation.py`, and `tests/evidence_integrity/`).
