# Evidence Trust Model and Cryptographic Custody

## 1. Architectural Purpose and Trust Boundaries

The SAT-SA cryptographic evidence custody subsystem provides an independently verifiable record of supervisory assessment artifacts within an offline, air-gapped **NTRO / NCIIPC** deployment.

```
+---------------------------------------------------------------------------------------+
|                                    TRUST BOUNDARIES                                   |
+---------------------------------------------------------------------------------------+
|  [ Audited Organization (SOC) ]                                                       |
|        │                                                                              |
|        │ Evidence Transmission (CSV/JSON, Logs, Case Exports)                         |
|        ▼                                                                              |
|  [ SAT-SA Application Service ]                                                       |
|        │ - Computes raw-file SHA-256 and canonical commitments                        |
|        │ - Signs custody milestones with Service Audit Key (Ed25519)                  |
|        │ - Records monotonic sequence and cryptographic hash chain                    |
|        ▼                                                                              |
|  [ Supervisory Examiner ]                                                             |
|        │ - Evaluates findings, records sampling reviews, issues decision              |
|        │ - Signs human review determinations with Examiner Key                        |
|        ▼                                                                              |
|  [ External Independent Verifier / Audit Authority ]                                  |
|        - Holds independently provisioned Public Keys & Trusted Checkpoints            |
|        - Recomputes hashes and verifies Ed25519 signatures independently              |
|        - Reconstructs Merkle inclusion proofs without database boolean trust          |
+---------------------------------------------------------------------------------------+
```

### 1.1 Service Signatures vs Examiner Signatures
- **Application Service Key (`service-audit-key-2026`)**: Attests strictly to what the SAT-SA ingestion and processing service received and recorded at system time. It does **not** represent a personal assertion by an individual examiner.
- **Examiner Personal Key (`examiner-<username>`)**: Attests to human deliberations, review item assessments, and regulatory dispositions recorded during the supervisory examination.
- **Authentication Separation**: The authenticated actor identity (`actor_id`) is stored as metadata inside the canonical event envelope, distinct from the signing key identity (`signing_key_id`).

---

## 2. Five Supervisory Custody Milestones

Custody events are emitted exclusively at meaningful supervisory process boundaries:

| Milestone Event Type | Trigger Boundary | Object Bound | Evidence Commitment |
| :--- | :--- | :--- | :--- |
| `submission_committed` | Evidence intake validated and committed | `submission` (v1) | Merkle root of raw files + canonical records |
| `evidence_revision_registered` | Corrective submission submitted | `submission` (v2+) | Merkle root of revised evidence set |
| `assessment_finalized` | Automated analytical rules frozen | `assessment_run` | Merkle root of all generated findings |
| `human_decision_recorded` | Examiner commits review determination | `review_decision` | Canonical digest of decision envelope |
| `report_snapshot_finalized` | Final examination report frozen | `report_snapshot` | SHA-256 of `checksums.sha256` manifest |

---

## 3. Cryptographic Hash Chaining and Monotonic Sequences

Every custody event $E_k$ for a given entity incorporates:
1. **Monotonic Sequence Number**: $k = k_{\text{prev}} + 1$, starting at sequence 1.
2. **Previous Event Commitment**:
   $$H_0 = 0^{64} \quad (\text{Genesis Commitment})$$
   $$H_k = \text{SHA256}(\text{CanonicalJSON}(E_{k-1}))$$
3. **Payload Digest**:
   $$\text{PayloadDigest}_k = \text{SHA256}(\text{CanonicalJSON}(E_k))$$
4. **Digital Signature**:
   $$\text{Signature}_k = \text{Ed25519\_Sign}(\text{PrivateKey}, \text{PayloadDigest}_k)$$

---

## 4. Checkpoints and Rollback Detection

A standalone append-only log cannot prove the absence of truncation unless compared against an independently retained anchor.

1. **Independent Checkpoint Provisioning**:
   Periodic checkpoints are signed and exported to external proof stores. A checkpoint consists of:
   - Entity ID
   - Sequence Number / Tree Size ($S$)
   - Checkpoint Root Hash ($R$)
   - Checkpoint Timestamp
   - Digital Signature
2. **Rollback Detection**:
   When verifying an entity log against an expected sequence $S_{\text{expected}}$, if the database contains fewer than $S_{\text{expected}}$ events, a `CustodyEventVerificationError` ("Rollback detected") is immediately raised.

---

## 5. Key Lifecycle, Storage, and Revocation

1. **Key Generation**: Ed25519 curve keys generated via RFC 8032 standard implementations.
2. **Secure Key Isolation**:
   - Private keys are stored strictly in restricted local filesystem directories (`config/keys/`) with operating system access control lists.
   - Private keys are **never** committed to version control, embedded in demo archives, or emitted in log files.
3. **Key Rotation**:
   - Each key is assigned a versioned identifier (e.g. `service-key-2026-v1`, `service-key-2026-v2`).
   - The `KeyRegistry` maintains a map of historical public keys and validity ranges. Historical events signed by older keys remain fully verifiable without rewriting history.
4. **Legacy Unanchored Records**:
   Historical evidence records ingested before integrity instrumentation are explicitly labeled `legacy_unanchored`. SAT-SA never retroactively fabricates blockchain or digital signature proofs for past events.

---

## 6. Trust Assertions: What The Proof Establishes and Does Not Establish

| What The Proof Establishes | What The Proof Does NOT Establish |
| :--- | :--- |
| Original evidence file bytes match the exact hash recorded at intake. | Does not prove the entity's underlying SOC is secure or effective. |
| Structured fields and scopes conform to canonical deterministic JSON. | Does not prove that telemetry was unmanipulated prior to transmission. |
| Supervisory milestones follow an unbroken cryptographic sequence. | Does not replace human examiner judgement or statutory oversight. |
| Events were signed by an authorized key holder registered in SAT-SA. | Does not establish current ledger state if verifying a historical snapshot. |
| Tampering, bit rot, truncation, or key substitution is detected immediately. | Is not a guarantee against internal compromise of the signing workstation. |
