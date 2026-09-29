# SAT-SA Prompt 1 of 2: Handoff Document

**Project**: SIH 2026 / SIH26157 / Supervisory Analytics Tool for SOC Assessment (SAT-SA), NTRO / NCIIPC  
**Target Architecture**: Air-gapped, offline NCIIPC-controlled network  
**Milestone**: Prompt 1 of 2 — SQL Evidence Storage, Hybrid Similarity, and Verifiable Custody  
**Date**: September 27, 2026  
**Status**: Prompt 1 Implementation & Verification Complete. Ready for Prompt 2 handoff.

---

## 1. Executive Summary & Architectural Scope

Prompt 1 establishes a cryptographic evidence foundation for the SAT-SA supervisory workbench without compromising its nature as a periodic supervisory tool:
1. **SQL as System of Record**: Extended existing SQLite and SQLAlchemy schemas with foreign key constraints, indexes, and versioning. Preserved `storage/sat_sa.db` completely untouched (`storage/sat_sa_preserved_backup.db` saved as safety copy).
2. **Strict Five-Tier Integrity Separation**: Raw-file SHA-256 digests, canonical structured commitments (`v1.0-canonical-json`), domain-separated Merkle trees (RFC 6962), TLSH fuzzy hashing, and MiniLM semantic embeddings are kept mathematically distinct.
3. **Signed Append-Only Custody Log**: Captures 5 critical supervisory milestones signed with Ed25519 digital signatures and hash-chained with rollback-detecting checkpoints.
4. **Permissioned Ledger Integration (Hyperledger Fabric v2.5.x LTS)**: Provided complete network profile in `deploy/ledger/` with 2 organizational MSPs, Go chaincode, transactional outbox in SQL, and zero false claims (gracefully degrades to `standalone_signed_log`).
5. **Hybrid Near-Duplicate Investigation Retrieval**: Evaluates exact wording, 2-shingle lexical overlap, input-gated TLSH distance, and MiniLM semantic similarity while preserving negation and operational tokens.
6. **Examiner UI & Standalone Offline Verifier**: Added Evidence Integrity dashboard, proof sidecars (`.proof.json`) for report exports, and an independent offline verifier (`scripts/verify_evidence.py`).

---

## 2. Schema and Configuration Changes

### 2.1 Database Schema Extensions (`db/models/evidence_integrity.py`)
- **`EvidenceCommitment` (`evidence_commitments`)**:
  - `commitment_type`: `raw_file` (exact submitted bytes SHA-256) vs `canonical_record` (normalized structured JSON) vs `merkle_batch`.
  - `canonical_digest`: Hex SHA-256 of deterministic RFC 8785 JSON representation with NFC Unicode and nonces.
  - `merkle_root`: Root of domain-separated RFC 6962 tree.
- **`CustodyEvent` (`custody_events`)**:
  - Sequence number, previous event commitment (SHA-256 hash chaining), object type/id/version, claimed event time, recorded time, actor ID, signing key ID, Ed25519 signature, and canonical payload digest.
- **`CustodyCheckpoint` (`custody_checkpoints`)**:
  - Periodic signed checkpoints capturing `tree_size`, `root_hash`, signing key, and signature for rollback and deletion detection.
- **`LedgerOutbox` (`ledger_outbox`)**:
  - Idempotency key (`uq_outbox_idempotency`), event FK, status (`pending_anchor`, `anchored`, `anchor_failed`, `not_configured`), retry count, last error, transaction ID, block number, and receipt JSON.
- **`VerificationRun` (`verification_runs`)**:
  - Audit trail of examiner verification actions, verification status, and detected issues.

### 2.2 Database Migrations
- **Alembic Migration**: `db/migrations/versions/07a1b2c34d55_evidence_integrity.py`
  - Fully tested for upgrade (`alembic upgrade head`) and downgrade (`alembic downgrade -1`).

### 2.3 Configuration Files
- `pyproject.toml`: Pinned `cryptography>=42.0.0` for Ed25519 signatures.
- `deploy/ledger/docker-compose.yaml`: Local Fabric v2.5 test network definition.
- `deploy/ledger/crypto-config.yaml` & `configtx.yaml`: Multi-org MSP identities and channel profile.
- `deploy/ledger/connection-profile.json`: Gateway connection profile.
- `deploy/ledger/chaincode/sat_sa_custody/chaincode.go`: Go smart contract for commitment anchoring.

---

## 3. Exact Startup and Verification Commands

### 3.1 Environment Bootstrap
```powershell
# From project root
uv sync
```

### 3.2 Key Provisioning
```powershell
# Generate service audit Ed25519 keypair for local development/testing:
uv run python -c "from packages.evidence_integrity.signatures import generate_ed25519_keypair, export_private_key_b64, export_public_key_b64; priv, pub = generate_ed25519_keypair(); print('Private:', export_private_key_b64(priv)); print('Public:', export_public_key_b64(pub))"
```

### 3.3 Full Verification Gate Suite
```powershell
# 1. Backend Linting
uv run ruff check .

# 2. Backend Formatting Check
uv run ruff format --check .

# 3. Complete Pytest Suite (all 152 tests)
uv run pytest -q

# 4. Evidence Integrity Specific Suite (24 tests)
uv run pytest tests/evidence_integrity/ -v

# 5. Synthetic Scenario Evaluation Harness (10 worlds)
uv run python -m evaluation.validate_scenarios

# 6. End-to-End Verification & Tamper Demonstration
uv run python scripts/demonstrate_e2e_verification.py

# 7. Frontend Linting
npm.cmd --prefix apps/web run lint

# 8. Frontend TypeScript Checking
npm.cmd --prefix apps/web run typecheck

# 9. Frontend Unit & Integration Tests (17 tests)
npm.cmd --prefix apps/web run test -- --run

# 10. Frontend Production Build
npm.cmd --prefix apps/web run build
```

### 3.4 Standalone Offline Verifier Usage
```powershell
uv run python scripts/verify_evidence.py \
  --report storage/reports/report_demo.html \
  --proof storage/reports/report_demo.proof.json \
  --public-key storage/keys/trusted_service_key.pub
```

---

## 4. Observed Verification Results Matrix

| Gate / Component | Command | Observed Status | Evidence / Notes |
|---|---|:---:|---|
| Python Linter | `uv run ruff check .` | **OBSERVED: PASS** | 0 errors |
| Python Formatter | `uv run ruff format --check .` | **OBSERVED: PASS** | 202 files checked and formatted |
| Pytest Full Suite | `uv run pytest -q` | **OBSERVED: PASS** | **152 passed** (4 warnings) in 136.34s |
| Ingestion & Analytics Tests | `uv run pytest tests/analytics/ tests/ingestion/` | **OBSERVED: PASS** | All baseline regression tests pass |
| Review & Decision Tests | `uv run pytest tests/review/test_decisions.py` | **OBSERVED: PASS** | 5/5 passed; decision custody events recorded |
| Reporting & Export Tests | `uv run pytest tests/reporting/test_snapshot_export.py` | **OBSERVED: PASS** | 6/6 passed; immutable reports & sidecars generated |
| Evidence Integrity Suite | `uv run pytest tests/evidence_integrity/ -v` | **OBSERVED: PASS** | **24/24 passed** (canonical, Merkle, TLSH, outbox, signatures) |
| Scenario Evaluation Harness | `uv run python -m evaluation.validate_scenarios` | **OBSERVED: PASS** | **10/10 worlds passed** (Sens: 5/5, Spec: 1/1, Unassessable: 1) |
| End-to-End Demo Script | `uv run python scripts/demonstrate_e2e_verification.py` | **OBSERVED: PASS** | Authentic report verified; tampered copy rejected (exit 0) |
| Web Linter | `npm --prefix apps/web run lint` | **OBSERVED: PASS** | 0 warnings, 0 errors |
| Web TypeScript | `npm --prefix apps/web run typecheck` | **OBSERVED: PASS** | 0 type errors |
| Web Tests | `npm --prefix apps/web run test -- --run` | **OBSERVED: PASS** | 6 files, **17/17 passed** in 45.33s |
| Web Production Build | `npm --prefix apps/web run build` | **OBSERVED: PASS** | Clean build in 10.66s (`dist/index.html`) |
| Live Fabric Docker Network | `docker compose -f deploy/ledger/docker-compose.yaml up` | **BLOCKED** | Docker daemon Windows service stopped; requires host admin elevation |
| Automated Browser Subagent | `browser_subagent` navigation | **BLOCKED** | Playwright driver binary absent on host; Azure CDN returned 404 |

---

## 5. Supported Ledger Modes & Security Assumptions

1. **`fabric_anchored` Mode**:
   - Anchors opaque commitments (`eventId`, `evidenceCommitment`, `signature`, `idempotencyKey`) on Hyperledger Fabric v2.5 LTS.
   - Enforces multi-org endorsement (`RegulatorMSP` and `SupervisedEntityMSP`).
   - Transactional outbox pattern handles peer disconnects, timeouts, and gateway retries.
   - **Security Boundary**: Multi-container local execution demonstrates protocol and endorsement semantics; it assumes crash-fault tolerance (Raft) and does NOT protect against full workstation compromise.
2. **`standalone_signed_log` Mode**:
   - Default operating mode for air-gapped environments without running Fabric peers.
   - Ed25519 digital signatures attest to local service audit logs.
   - Merkle checkpoints provide rollback and deletion detection against independently held checkpoint roots.
   - **Zero Fake Claims**: UI and exports explicitly display `STANDALONE SIGNED LOG` and never render blockchain badges without a verified Fabric block receipt.

---

## 6. Audit Resolution Summary (13 Items)

Complete cross-reference table maintained in `docs/AUDIT_RESOLUTION.md`:
1. **Exact-Byte vs Canonical Hashing**: Resolved via separate `raw_file_sha256` and `canonical_digest` in `evidence_commitments`.
2. **Deterministic Canonicalization**: Resolved via `v1.0-canonical-json` (RFC 8785 key sort, NFC Unicode, deterministic floats, nonces).
3. **Domain-Separated Merkle Trees**: Resolved via RFC 6962 prefixes (`0x00`, `0x01`) and audit path index validation.
4. **Fuzzy Hashing Boundaries**: Resolved via Trend Micro TLSH reference implementation with complexity threshold gating.
5. **Score Conflation Prevention**: Resolved by persisting TLSH distance, Jaccard overlap, and cosine similarity as separate columns.
6. **Negation & Operational Token Preservation**: Resolved in tokenizer normalization preserving `not`, `failed`, `blocked`, etc.
7. **Ed25519 Signed Custody Log**: Resolved via `CustodyLogManager` tracking 5 milestone event types.
8. **Rollback & Deletion Detection**: Resolved via `CustodyCheckpoint` root verification.
9. **SQL / Ledger Consistency**: Resolved via `LedgerOutbox` transactional outbox with idempotency keys.
10. **Dual-Mode Graceful Degradation**: Resolved via `fabric_anchored` vs `standalone_signed_log` without blocking analysis.
11. **Standalone Offline Verifier**: Resolved via `scripts/verify_evidence.py` and proof sidecars (`.proof.json`).
12. **Historical Immutability**: Resolved by freezing report snapshots prior to sidecar signing; never mutating historical bytes.
13. **Entity Scope Authorization**: Enforced on all evidence, decision, report, and integrity API routes.

---

## 7. Preserved Assets Confirmation

- **Preserved Database**: `storage/sat_sa.db` (487,424 bytes, LastWriteTime: 9/25/2026 10:56:29 AM) remained untouched throughout all migrations and tests.
- **Preserved Safety Backup**: `storage/sat_sa_preserved_backup.db`.
- **Pretrained Safetensors**: `sentence-transformers/all-MiniLM-L6-v2` (`models/manifest.json`, 90.87 MB safetensors verified).

---

## 8. Handoff to Prompt 2

Prompt 1 has established a verified, mathematically sound evidence integrity foundation.

### Scope for Prompt 2 (Do Not Start in This Prompt):
- Supervisory analytical functionality extensions and finalization.
- Multi-period cross-submission historical regression pipelines.
- Complete performance profiling and query optimization under heavy data volumes.
- Final offline air-gapped release packaging and distribution bundles (`sat_sa_offline_bundle.zip`).
- Full release readiness certification.
