# SAT-SA Architecture & Operational Boundaries

**System**: Supervisory Analytics Tool for SOC Assessment (SAT-SA)  
**Stakeholder**: NTRO / NCIIPC  
**Problem Statement**: SIH2026 / SIH26157  
**Operating Mode**: Air-Gapped / Disconnected High-Assurance Review Workbench  

---

## 1. Architectural Boundaries & Data Flow

```
                      AIR-GAPPED HIGH-ASSURANCE BOUNDARY
┌────────────────────────────────────────────────────────────────────────┐
│  OFF-CHAIN EVIDENCE & SYSTEM OF RECORD (SQLite / SQLAlchemy)           │
│  ┌───────────────────────┐         ┌───────────────────────────────┐   │
│  │ CSE Submissions       │         │ Normalized Telemetry Records  │   │
│  │ - Manifest validation │         │ - Alerts & Investigation logs │   │
│  │ - Exact SHA-256 files │────────>│ - Escalations & SLA Claims    │   │
│  │ - Quarantined records │         │ - Zero-evidence observations  │   │
│  └───────────────────────┘         └───────────────────────────────┘   │
│              │                                     │                   │
│              ▼                                     ▼                   │
│  ┌─────────────────────────────────────────────────────────────────┐   │
│  │ SUPERVISORY ANALYTICS ENGINE                                    │   │
│  │ • POL-INV-001: Execution Gaps (superficial investigation)       │   │
│  │ • POL-ESC-002: Overdue Critical Escalations                     │   │
│  │ • POL-COV-003: Negative Space (quiet vs broken sensors)         │   │
│  │ • POL-KPI-004: Contradicted SLA Claims (bounded intervals)      │   │
│  │ • POL-REC-005: Recurring Incidents Post-Remediation             │   │
│  │ • Explainable Unusual Patterns (Median / MAD Robust Statistics) │   │
│  │ • Versioned Peer Cohorts (N >= 3, Target Excluded Distribution) │   │
│  │ • Longitudinal Multi-Quarter Trends (Preserved Period Gaps)     │   │
│  └─────────────────────────────────────────────────────────────────┘   │
│              │                                                         │
│              ▼                                                         │
│  ┌─────────────────────────────────────────────────────────────────┐   │
│  │ EXAMINER DELIBERATION & HUMAN DECISION LAYER                    │   │
│  │ • Submodular Knapsack Portfolio Optimization (Budget/Strata)    │   │
│  │ • Independent Decision Vocabulary (AFFIRMED, SUPPRESSED, etc.)  │   │
│  │ • Local Internal Evidence Requests (REQ-YYYY-NNN)               │   │
│  │ • Machine Findings Immutability: Findings are NEVER Overwritten │   │
│  └─────────────────────────────────────────────────────────────────┘   │
│              │                                                         │
│              ▼                                                         │
│  ┌─────────────────────────────────────────────────────────────────┐   │
│  │ IMMUTABLE FROZEN REPORTING                                      │   │
│  │ • Run-Frozen Snapshots (HTML, JSON, Checksum Manifest)          │   │
│  │ • Detached Standalone Proof Sidecars (*.proof.json)             │   │
│  └─────────────────────────────────────────────────────────────────┘   │
└────────────────────────────────────────────────────────────────────────┘
                               │ (SHA-256 Commitments ONLY)
                               ▼
┌────────────────────────────────────────────────────────────────────────┐
│  CRYPTOGRAPHIC EVIDENCE CUSTODY & ANCHORING LAYER                      │
│  ┌────────────────────────────────┐  ┌──────────────────────────────┐  │
│  │ Ed25519 Signed Append-Only Log │  │ RFC 6962 Merkle Checkpoints  │  │
│  │ - Monotonic entity sequence    │  │ - Tree size, root hash       │  │
│  │ - Cryptographic hash chaining  │  │ - Offline CLI verifier       │  │
│  └────────────────────────────────┘  └──────────────────────────────┘  │
│                               │                                        │
│                               ▼                                        │
│  ┌──────────────────────────────────────────────────────────────────┐  │
│  │ TRANSACTIONAL OUTBOX & PERMISSIONED LEDGER                       │  │
│  │ • Mode A: Standalone Signed Log (Zero external infrastructure)   │  │
│  │ • Mode B: Hyperledger Fabric v2.5 LTS (Org1/Org2 Raft channel)   │  │
│  │ • Strict Boundary: ZERO raw case narratives or telemetry on-chain│  │
│  └──────────────────────────────────────────────────────────────────┘  │
└────────────────────────────────────────────────────────────────────────┘
```

---

## 2. Invariant Specifications

### A. SQL Evidence Storage & Off-Chain Boundaries
- **System of Record**: SQLite (`storage/sat_sa.db` in production; `storage/sat_sa_demo.db` in demo mode) stores all relational data.
- **Privacy Boundary**: Sensitive case text, asset IP addresses, employee IDs, and incident narratives strictly remain in local off-chain storage.
- **Ledger Commitments**: Only cryptographic hashes (SHA-256 of raw files, canonical commitments of milestones, and Merkle roots) are submitted to the ledger outbox.

### B. Supervisory Analytics vs SIEM / Real-Time Operations
- **Periodic Assessment**: SAT-SA evaluates periodic batches (e.g. `2026-Q3`), not real-time event streams.
- **Machine Findings vs Human Verdicts**:
  - Machine findings evaluate evidence states: `supported`, `potential_concern`, `contradictory`, `insufficient_evidence`, `not_applicable`.
  - Machine findings are byte-immutable once generated.
  - Human examiners record distinct decisions (`AFFIRMED_CONCERN`, `BENIGN_SUPPRESSED`, `REQUIRES_FURTHER_INQUIRY`, `EXCEPTION_NOTED`) with full revision provenance.
- **Explainability**: Statistical anomaly detection relies on robust, transparent distribution metrics (Median / Median Absolute Deviation), not uncalibrated opaque ML confidence scores.

### C. Peer Cohort Isolation & Target Exclusion
- **Eligibility Invariant**: Cohort matching requires sector alignment, critical asset tier parity, and minimum evidence completeness ($C \ge 60\%$).
- **Target Exclusion Rule**: The target entity under examination is strictly excluded from its peer reference distribution to prevent self-bias.
- **Privacy Boundary**: Examiners comparing peer aggregates have zero direct-object access to underlying peer investigation narratives or internal tickets.

### D. Cryptographic Custody & Dual-Mode Ledger
- **Ed25519 Custody Log**: Every milestone (`submission_committed`, `assessment_finalized`, `human_decision_recorded`, `report_snapshot_finalized`) produces a signed hash-chained audit record.
- **RFC 6962 Merkle Checkpoints**: Enable standalone mathematical verification of event inclusion without querying the primary database.
- **Dual Mode Operation**:
  - `standalone_signed_log`: Full cryptographic auditability via local Ed25519 signatures and Merkle trees. Transparently labeled in UI/API.
  - `fabric`: Private permissioned anchoring on Hyperledger Fabric v2.5 LTS with verified transaction IDs and block receipts. No fake badges.
