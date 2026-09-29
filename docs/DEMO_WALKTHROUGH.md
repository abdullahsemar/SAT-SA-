# SAT-SA: Demonstration Walkthrough & Examiner Operational Guide

**Project**: SIH 2026 / SIH26157 / Supervisory Analytics Tool for SOC Assessment (SAT-SA)  
**Stakeholder**: NTRO / NCIIPC  
**Target Environment**: Offline / Air-Gapped High-Security Supervisory Infrastructure  
**Preserved Production Database Safety**: `storage/sat_sa.db` strictly preserved untouched (Safety Backup: `storage/sat_sa_preserved_backup.db`)  
**Active Demonstration Database**: `storage/sat_sa_demo.db`

---

## 1. Safety & Architecture Invariants

1. **System of Record**: SQL database (`storage/sat_sa_demo.db`) maintains all entity accounts, telemetry intake records, normalized data, machine findings, human review items, examiner decisions, and frozen assessment report snapshots.
2. **Immutable Off-Chain Evidence**: Original raw evidence files are cryptographically indexed with SHA-256 and SHA-512 domain-separated commitments. Sensitive case narratives never leave off-chain storage.
3. **Custody & Anchoring**: Five-tier cryptographic custody log (Ed25519 signatures, RFC 6962 Merkle tree checkpoints) with dual-mode ledger support (`standalone_signed_log` and permissioned Hyperledger Fabric v2.5 channel).
4. **Independent Human Decision Separation**: Machine evidence states (`supported`, `potential_concern`, `contradictory`, `insufficient_evidence`, `not_applicable`) are strictly immutable. Human review decisions (`AFFIRMED_CONCERN`, `BENIGN_SUPPRESSED`, `REQUIRES_FURTHER_INQUIRY`, `EXCEPTION_NOTED`) are recorded in an append-only audit trail with examiner provenance.
5. **No Synthetic Shortcuts**: Zero hardcoded metrics, zero dummy findings, zero decorative badges. All metrics and indicators are computed dynamically from real database records.

---

## 2. Quick Start: Launching the Prototype

### Step 1: Initialize Demo Data (Idempotent)
Run the automated demonstration initializer to seed the separate demo database with 4 comparable banking institutions, 1 healthcare control institution, 3 historical quarters, and complete supervisory telemetry across all 5 detector families:

```powershell
# Set database environment variable to demo database
$env:DATABASE_URL = "sqlite:///storage/sat_sa_demo.db"

# Execute demo initializer (requires --reset flag to re-create demo DB from scratch)
.\.venv\Scripts\python.exe scripts/initialize_demo_data.py --reset --tamper-demo
```

### Step 2: Start the Backend FastAPI Service
In a terminal window:

```powershell
$env:DATABASE_URL = "sqlite:///storage/sat_sa_demo.db"
uv run uvicorn apps.api.main:app --host 127.0.0.1 --port 8000 --reload
```

The API docs and OpenAPI specifications will be available at `http://127.0.0.1:8000/docs`.

### Step 3: Start the Frontend Supervisory Workbench
In a separate terminal window:

```powershell
npm --prefix apps/web run dev
```

Open `http://localhost:5173` in your web browser.

---

## 3. Demo Credentials & Authorized Entities

| Username | Password | Role | Entity Scope | Purpose |
| :--- | :--- | :--- | :--- | :--- |
| `examiner` | `ExaminerPassword123!` | `examiner` | `["*"]` (All Entities) | Full supervisory examiner authority across all CSEs |
| `admin` | `AdminPassword123!` | `admin` | `["*"]` (All Entities) | System administration, ledger management, policy tuning |
| `bank_analyst` | `BankAnalystPassword123!` | `examiner` | `["CSE-BANK-01"]` | Restricted scoped examiner for State Bank of Bharat only |
| `health_officer` | `HealthOfficerPassword123!` | `examiner` | `["CSE-HEALTH-01"]` | Restricted scoped examiner for Healthcare Portal |

---

## 4. End-to-End Examiner Supervisory Walkthrough

### Phase 1: Authentication & Context Selection
1. Navigate to `http://localhost:5173` and log in as `examiner` (`ExaminerPassword123!`).
2. In the top navigation context bar:
   - Select Entity: **State Bank of Bharat (`CSE-BANK-01`)**
   - Select Period: **`2026-Q3`** (Jul 1, 2026 – Sep 30, 2026)
3. Notice how all screens maintain this contextual entity and period scope without requiring manual database UUID entry.

### Phase 2: Entity Supervisory Overview
1. Click **Supervisory Overview** in the primary navigation bar.
2. Inspect the **Supervisory Attention Index (SAI)**:
   - Composite attention meter with explainable weights ($W_{inv}=0.30$, $W_{esc}=0.30$, $W_{cov}=0.20$, $W_{kpi}=0.10$, $W_{rec}=0.10$).
   - Prominent regulatory disclaimer: *SAI is an investigative prioritization index, NOT an authoritative SOC maturity grade or probability of compromise.*
3. Review the **4 Core Supervisory Indicator Cards**:
   - **Evidence Completeness**: 100.0% (all declared manifest sources parsed and accepted; 0 quarantined records).
   - **Execution Gaps**: 2 operational concerns detected (`POL-INV-001` fast closure without artifacts, `POL-ESC-002` overdue critical escalation).
   - **Negative Space**: 1 operational blind spot detected (`POL-COV-003` active payment gateway `SRV-CSE-BANK-01-PAY-02` with stale telemetry).
   - **Contradicted Claims**: 1 KPI contradiction detected (`POL-KPI-004` claimed 99.0% SLA compliance contradicted by calculated interval).
4. Review the **8-Dimension Capability Coverage Matrix**:
   - Evaluates coverage across Threat Detection, Investigation Quality, Escalation, Incident Response, Governance, Operational Discipline, and Resilience.
   - Accurately reports `not_assessed` or `insufficient_evidence` where telemetry is absent rather than fabricating maturity scores.

### Phase 3: Peer Comparison & Longitudinal Trends
1. Click **Peer Comparison & Trends** in the primary navigation.
2. **Tab 1: Peer Cohort Comparison**:
   - Inspect the **Cohort Definition**: Sector: *Financial / Banking*, Tier: *Critical Infrastructure*, Window: *2026-Q3*.
   - Invariant Verification: **Target entity (`CSE-BANK-01`) is strictly excluded from reference distribution calculation** to prevent self-skewing.
   - Cohort Size: $N=3$ qualified peers (`CSE-BANK-02`, `CSE-BANK-03`, `CSE-BANK-04`).
   - Audit Exclusions: **National Healthcare Portal (`CSE-HEALTH-01`)** is explicitly listed in the Excluded Entities table with reason: *Sector mismatch: Healthcare Services != Financial / Banking*.
   - Compare entity metrics against peer median and interquartile range (IQR).
3. **Tab 2: Longitudinal Trends**:
   - View the quarterly trajectory across `2026-Q1`, `2026-Q2`, and `2026-Q3`.
   - Observe the trajectory: Q1 healthy baseline -> Q2 minor backlog -> Q3 execution gap accumulation.
   - Invariant Verification: Missing periods are preserved as explicit gaps (`has_data=False`) rather than fabricated zeros.
4. **Tab 3: Explainable Unusual Patterns**:
   - Review Median / Median Absolute Deviation (MAD) statistical review hypotheses:
     * Concentrated rapid closures (< 120s duration without artifacts).
     * Workload surge relative to eligible case volume.
     * Telemetry drop despite stable exposure.
     * Repeated narrative cluster.

### Phase 4: Supervisory Findings & Exception Suppression
1. Click **Supervisory Findings** in the navigation bar.
2. Inspect the detected findings:
   - Filter by evidence state: `potential_concern`, `contradictory`, `supported`.
   - Click on `POL-ESC-002` (`CASE-CSE-BANK-01-OVERDUE-01`): Review exact citation path, eligible time window (4h SLA), and absence of escalation record.
   - Inspect `CASE-CSE-BANK-01-EXC-03`: Notice that port scan alert on `SRV-CSE-BANK-01-EXC-04` was **suppressed from adverse finding** due to approved CISO maintenance exception `EXC-2026-089`.

### Phase 5: Examiner Review Workspace & Decision Recording
1. Click **Examiner Review** in the navigation bar.
2. Review the optimized portfolio: 15 items allocated across **Targeted**, **Exploratory**, **Unflagged Control**, and **Asset** strata.
3. Select the flagged overdue critical case (`CASE-CSE-BANK-01-OVERDUE-01`).
4. In the Examiner Decision panel:
   - Select Finding Decision: `REQUIRES_FURTHER_INQUIRY`
   - Enter Rationale: *"Overdue critical escalation requires verification against SIEM audit logs. Internal ticket shows no external incident response dispatch."*
   - Submit the decision. Notice the immutable append-only record created in the audit log.
5. Create an **Evidence Request**:
   - Request Type: `SIEM_AUDIT_LOGS`
   - Description: *"Requesting raw SIEM escalation event logs to verify external dispatch."*
   - Click Submit Request.

### Phase 6: Evidence Custody & Ledger Verification
1. Click **Evidence Custody & Integrity** in the navigation bar.
2. Inspect the **Ed25519 Custody Log**:
   - Monotonic sequence numbers (1, 2, 3...) per entity.
   - Strict cryptographic hash chaining: `previous_event_commitment == SHA256(previous_event_payload)`.
   - Milestones captured: `submission_committed`, `assessment_finalized`, `human_decision_recorded`, `report_snapshot_finalized`.
3. Inspect the **Signed Merkle Checkpoint**:
   - RFC 6962 Merkle tree root hash and tree size.
   - Cryptographic signature signed by the audit authority key.
4. Inspect the **Ledger Anchoring Status**:
   - Milestone event anchored on Hyperledger Fabric: Block #1042, Transaction ID `0x...`, Channel `sat-sa-evidence-channel`.
   - Secondary event in transparent `pending_anchor` state, demonstrating honest unanchored handling without deceptive green badges.

### Phase 7: Frozen Verifiable Reports & Tamper Detection
1. Click **Reports & Exports** in the navigation bar.
2. Review finalized report snapshot `rep-...`:
   - Contains immutable snapshot JSON, standalone HTML rendering, and SHA-256 Checksum Manifest.
   - Download the Report Bundle ZIP.
3. Run the standalone cryptographic tamper check script:
   ```powershell
   .\.venv\Scripts\python.exe scripts/initialize_demo_data.py --tamper-demo
   ```
   - Test 1 verifies the authentic report against the trusted Ed25519 public key (**VALID**).
   - Test 2 injects an unauthorized modification into a disposable COPY of the report (**TAMPERED / REJECTED**).

---

## 5. Offline & Air-Gapped Operation

- **No Remote Network Calls**: All web assets, styles, fonts, and model weights are packaged locally.
- **Pretrained MiniLM**: Pinned local safetensors with SHA-256 integrity manifest (`packages/analytics/semantics/registry.py`).
- **Private Fabric LAN**: Fabric integration operates on local Docker network with Internet egress disabled.
