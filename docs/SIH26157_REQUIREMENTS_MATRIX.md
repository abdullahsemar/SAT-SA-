# SIH26157 Requirements Traceability & Verification Matrix

**Project**: SIH 2026 / SIH26157 / Supervisory Analytics Tool for SOC Assessment (SAT-SA)  
**Supervisory Authority**: NTRO / National Critical Information Infrastructure Protection Centre (NCIIPC)  
**Theme**: Blockchain & Cybersecurity (Offline Air-Gapped Supervisory Analytics Workbench)  
**Document Revision**: 2.0 (Prompt 2 Final Integration)

---

## 1. Requirement Scope & Architectural Classification

SAT-SA is an offline supervisory assessment workbench designed to inspect periodic evidence submissions from Critical Sector Entities (CSEs). It evaluates declared operational quality against concrete underlying telemetry without becoming an active SIEM, real-time intrusion monitoring tool, or autonomous sanctioning authority.

> [!NOTE]
> Blockchain anchoring and hybrid locality sensitive hashing (TLSH) are implemented as **cryptographic auditability and explainability enhancements** rather than regulatory substitutes for the core supervisory analytics requirements.

---

## 2. Requirements Matrix (17 Functional Requirements + Operations)

| Req ID | Requirement Description | Working Capability & Workflow | Backend & Frontend Implementation Files | Acceptance Tests & Verification Commands | Prerequisites & Limitations | Status |
|:---:|:---|:---|:---|:---|:---|:---:|
| **FR-01** | **Multi-Entity & Multi-Period Intake** | Authoritative CSV/JSON intake, manifest validation, versioned submissions, draft protection. | `packages/ingestion/service.py`, `apps/api/routes/submissions.py`, `apps/web/src/features/submissions/` | `tests/integration/test_migration_acceptance.py`, `tests/ingestion/` | Requires valid entity registration; strictly rejects raw executable SQL dumps. | **IMPLEMENTED** |
| **FR-02** | **Raw Evidence Byte Preservation & Provenance** | Stores exact submitted file bytes in `storage/evidence/` with raw SHA-256 digests; prevents mutation. | `packages/ingestion/service.py`, `db/models/evidence.py`, `db/models/evidence_integrity.py` | `tests/evidence_integrity/test_canonical_hashing.py`, `tests/integration/test_citation_validation.py` | Storage directory must have write permissions; raw files immutable once committed. | **IMPLEMENTED** |
| **FR-03** | **Quarantine, Completeness & Schema Accounting** | Explicitly records parsed, accepted, rejected, and quarantined counts; factors into assessability. | `packages/ingestion/service.py`, `db/models/evidence.py`, `apps/api/schemas/submissions.py` | `tests/integration/test_audit_regressions.py::test_quarantined_records_affecting_population_completeness` | Quarantined rows require a corrective submission revision to enter assessment. | **IMPLEMENTED** |
| **FR-04** | **Execution-Gap Analysis & Lifecycle Evidence** | Unsubstantiated closures, overdue escalations without exception, missing investigation links. | `packages/analytics/service.py`, `packages/analytics/detectors/`, `packages/analytics/supervisory_summary.py` | `tests/analytics/test_phase_a_regressions.py`, `tests/integration/test_audit_regressions.py` | Requires declared investigation and escalation telemetry sources. | **IMPLEMENTED** |
| **FR-05** | **Negative-Space & Asset Monitoring Analysis** | Detects broken sensors vs healthy quietness; identifies category and telemetry gaps. | `packages/analytics/detectors/coverage.py`, `packages/analytics/supervisory_summary.py` | `tests/analytics/test_coverage.py`, `evaluation/validate_scenarios.py` (World 3 & 5) | Differentiates zero alerts with healthy heartbeats from unmonitored assets. | **IMPLEMENTED** |
| **FR-06** | **Declared Claim & KPI Reconciliation** | Evaluates self-reported SLA claims against observable cases using bounded uncertainty intervals. | `packages/analytics/detectors/kpi_claims.py`, `packages/analytics/supervisory_summary.py` | `tests/analytics/test_kpi_claims.py`, `evaluation/validate_scenarios.py` (World 2 & 10) | Contradiction triggered only when upper bound strictly falls below claim. | **IMPLEMENTED** |
| **FR-07** | **Explainable Unusual-Pattern Detection** | Robust statistics (Median / MAD) detecting rapid closure clusters and activity drops. | `packages/analytics/unusual_patterns.py`, `apps/api/routes/supervisory.py` | `tests/analytics/test_unusual_patterns.py` | Handles small samples ($n < 5$) and zero-MAD baselines transparently. | **IMPLEMENTED** |
| **FR-08** | **Versioned Peer Cohort Comparisons** | Compares normalized rates across eligible peers; target entity excluded from reference distribution. | `packages/analytics/peer_comparison.py`, `apps/api/routes/supervisory.py`, `apps/web/src/features/comparison/` | `tests/analytics/test_peer_comparison.py` | Minimum 3 qualified peers required; privacy boundary isolates peer narratives. | **IMPLEMENTED** |
| **FR-09** | **Multi-Period Longitudinal Trends** | Tracks completeness, concern rates, and decisions across periods; preserves missing periods as gaps. | `packages/analytics/trends.py`, `apps/api/routes/supervisory.py`, `apps/web/src/features/comparison/` | `tests/analytics/test_trends.py` | Exactly 1 run per period; missing periods displayed as gaps, never zeros. | **IMPLEMENTED** |
| **FR-10** | **Security Operations Capability Coverage** | Maps evidence findings to 8 operational dimensions with status pills (`supported` to `not_assessed`). | `packages/analytics/supervisory_summary.py`, `apps/web/src/features/overview/SupervisoryOverview.tsx` | `tests/analytics/test_supervisory_summary.py` | Partial telemetry yields `insufficient_evidence` rather than false compliance. | **IMPLEMENTED** |
| **FR-11** | **Submodular Knapsack Portfolio Optimization** | Budget-constrained portfolio selection across `targeted`, `control`, and `exploratory` strata. | `packages/analytics/selection/optimizer.py`, `packages/analytics/selection/candidates.py` | `tests/analytics/test_portfolio_optimizer.py`, `evaluation/validate_scenarios.py` | Enforces group diversity caps and maximizes marginal hypothesis coverage. | **IMPLEMENTED** |
| **FR-12** | **Append-Only Examiner Decision Deliberation** | Independent decision vocabulary with optimistic concurrency tracking (`version`, `superseded_id`). | `apps/api/services/decisions.py`, `db/models/review.py`, `apps/web/src/features/review/` | `tests/review/test_decisions.py` | Machine findings are byte-immutable; human decisions recorded in dedicated tables. | **IMPLEMENTED** |
| **FR-13** | **Local Evidence Request Tracking** | Tracks documentation requests locally without external network transmission. | `db/models/review.py`, `apps/api/routes/review.py`, `apps/web/src/features/review/` | `tests/review/test_decisions.py::test_evidence_requests_local_and_distinguishing_question` | Requests remain internal audit objects unless external export is authorized. | **IMPLEMENTED** |
| **FR-14** | **Hybrid Near-Duplicate Investigation Retrieval** | Multi-channel matching: Exact duplicate, 2-shingle Jaccard overlap, TLSH fuzzy, MiniLM embeddings. | `packages/analytics/semantics/near_duplicates.py`, `packages/analytics/semantics/tlsh_engine.py` | `tests/evidence_integrity/test_hybrid_similarity.py` | Preserves negation (`not`, `failed`, `blocked`); input complexity gating for TLSH. | **IMPLEMENTED** |
| **FR-15** | **Frozen Byte-Immutable Assessment Snapshots** | Snapshots database state at cutoff; generates HTML, JSON, and `checksums.sha256` manifest. | `packages/reporting/snapshot.py`, `packages/reporting/manifest.py`, `packages/reporting/renderer.py` | `tests/reporting/test_snapshot_export.py` | Historical report bytes are never modified to add later decisions or receipts. | **IMPLEMENTED** |
| **FR-16** | **Standalone Offline Proof Sidecars & Verifier** | Generates `.proof.json` sidecars; verifiable offline via CLI tool without DB or internet. | `packages/evidence_integrity/verifier.py`, `scripts/verify_evidence.py` | `tests/evidence_integrity/test_report_sidecar_proof.py`, `scripts/demonstrate_e2e_verification.py` | Exit codes: 0 = Valid, 1 = Tampered/Invalid signature, 2 = Missing files. | **IMPLEMENTED** |
| **FR-17** | **Permissioned Blockchain & Transactional Outbox** | Hyperledger Fabric v2.5 LTS network profile, Go chaincode, SQL transactional outbox, dual modes. | `deploy/ledger/`, `packages/evidence_integrity/outbox.py`, `packages/evidence_integrity/fabric_client.py` | `tests/evidence_integrity/test_outbox_and_fabric.py` | Gracefully operates in `standalone_signed_log` mode without fake blockchain claims. | **IMPLEMENTED** |

---

## 3. Operational, AI & Deployment Requirements

| Category | Requirement | Implementation Details | Verification Method | Status |
|:---|:---|:---|:---|:---:|
| **Deployment** | **Offline Air-Gapped Operation** | Local loopback `127.0.0.1`, zero external CDN dependencies, embedded fonts, local wheels. | `tests/offline/test_no_network.py` | **IMPLEMENTED** |
| **Deployment** | **Database Preservation** | `storage/sat_sa.db` preserved untouched; safety backup at `storage/sat_sa_preserved_backup.db`. | File hash & LastWriteTime verification | **IMPLEMENTED** |
| **Security** | **Session Auth & CSRF Protection** | `HttpOnly`, `SameSite=Lax` cookies, double-submit CSRF header, entity authorization. | `apps/api/auth.py`, `tests/integration/test_migration_acceptance.py` | **IMPLEMENTED** |
| **AI Documentation** | **Pretrained Model Governance** | `sentence-transformers/all-MiniLM-L6-v2` pinned commit SHA, verified safetensors manifest. | `docs/model-card.md`, `models/manifest.json` | **IMPLEMENTED** |
| **Validation** | **Real-Ingestion Scenario Evaluation** | 10 synthetic scenario worlds validating sensitivity, specificity, and citation provenance. | `uv run python -m evaluation.validate_scenarios` (10/10 PASS) | **IMPLEMENTED** |
| **Release** | **Self-Contained Offline Bundle** | Deterministic packaging script building release ZIP with SHA-256 release manifest. | `scripts/build_offline_bundle.py`, `scripts/verify_release.py` | **IMPLEMENTED** |

---

## 4. Requirement Verification Matrix Sign-Off

All 17 functional requirements and operational categories are fully implemented, accompanied by automated regression tests, and verifiable offline.
