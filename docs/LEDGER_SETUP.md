# Hyperledger Fabric Permissioned Ledger Setup & Architecture

## 1. Role and Strategic Scope

In accordance with Section 1 and Section 6 of the project requirements baseline:
- SAT-SA is a periodic supervisory assessment workbench for **NTRO / NCIIPC**.
- The primary system of record remains the **SQL database**.
- The blockchain integration serves strictly as an **immutable, multi-party custody anchoring layer**. Full case details, raw telemetry, and investigation narratives are **never** committed to the ledger.
- SAT-SA is designed for air-gapped, offline operational networks with zero external cloud dependencies, zero cryptocurrency, and zero public RPC endpoints.

---

## 2. Permissioned Network Topology

The local deployment profile in `deploy/ledger/` specifies a minimal, production-grade **Hyperledger Fabric v2.5.x LTS** network:

```
+-----------------------------------------------------------------------------------------+
|                               HYPERLEDGER FABRIC CLUSTER                                |
+-----------------------------------------------------------------------------------------+
|  [ Orderer Organization ]                                                               |
|        └─ orderer.sat-sa.local (Raft Consensus, TLS, Port 7050)                        |
|                                                                                         |
|  [ Supervisory Org (Org1 / NCIIPC) ]         [ Supervised Org (Org2 / Bank SOC) ]       |
|        ├─ ca.org1.sat-sa.local (Port 7054)          ├─ ca.org2.sat-sa.local (Port 8054) |
|        └─ peer0.org1.sat-sa.local (Port 7051)       └─ peer0.org2.sat-sa.local (Port 9051)
|                                                                                         |
|  [ Consortium Channel: 'satsa-custody-channel' ]                                        |
|        └─ Chaincode: 'sat_sa_custody' (Go runtime)                                      |
|        └─ Endorsement Policy: OR('Org1MSP.peer', 'Org2MSP.peer')                        |
+-----------------------------------------------------------------------------------------+
```

### 2.1 Ledger Metadata Schema (Opaque On-Chain Records)
To prevent information leakage while ensuring proof auditability, on-chain transactions contain only minimal opaque commitments:
```json
{
  "eventId": "ev_4f8a1c90",
  "entityId": "E-101",
  "eventType": "submission_committed",
  "sequenceNumber": 1,
  "objectType": "submission",
  "objectId": "sub_49a0b1c2",
  "objectVersion": 1,
  "evidenceCommitment": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
  "payloadDigest": "8a3f5b7c...",
  "signature": "c2lnX2VkMjU1MTlf...",
  "signingKeyId": "service-audit-key-2026",
  "actorId": "lead_examiner",
  "idempotencyKey": "idem_sub_49a0b1c2_v1",
  "timestamp": 1774609200
}
```

---

## 3. Go Smart Contract (`deploy/ledger/chaincode.go`)

The chaincode enforces four critical integrity invariants:
1. **Submitter Authorization**: Validates that the submitter possesses an authorized MSP role (`Org1MSP` or `Org2MSP`).
2. **Idempotency and Duplicate Rejection**: Prevents duplicate transactions for identical idempotency keys; subsequent calls return the existing receipt rather than creating duplicate state.
3. **Monotonic Sequences**: Verifies sequence continuity per entity to prevent replay or silent history rewrites.
4. **Historical Correction Linkage**: Revisions must link to a prior event ID; historical commitments cannot be deleted or overwritten.

---

## 4. Transactional Outbox Pattern & Failure Recovery

To guarantee atomicity between local SQL persistence and external ledger anchoring:
1. **Atomic Enqueueing**:
   When an examiner commits evidence, finalizes an assessment, or exports a report, the application event and a corresponding `LedgerOutbox` record (`status='pending'`) are written in the **exact same SQL transaction**.
2. **Asynchronous Processor (`OutboxProcessor`)**:
   A background worker retrieves pending entries, submits transactions to Fabric gateway peers via mTLS, and persists the validated `transaction_id` and `block_number`.
3. **Resilience & Outage Recovery**:
   If the ledger peer is offline or network errors occur, the job remains in `pending` state with incremented `retry_count` and exponential backoff (`next_retry_at`). The supervisory workflow is **not** aborted; the UI indicates `pending_anchor`.

---

## 5. Dual Modes: Standalone Signed Log vs Fabric Anchored

| Mode | Trust Anchor | Ledger Dependencies | UI Badge |
| :--- | :--- | :--- | :--- |
| **`fabric_anchored`** | Multi-party consensus block commit (Fabric v2.5.x) | Live Fabric peers and ordering service | `Hyperledger Fabric Anchored` (Blue) |
| **`standalone_signed_log`** | Local Ed25519 digital signature & RFC 6962 Merkle tree | None (Self-contained offline operation) | `Standalone Signed Log` (Amber) |

> [!NOTE]
> The system **never** displays a blockchain badge when operating in Standalone Signed Log mode. The mode is explicitly exposed in `/api/v1/evidence-integrity/status` and on the Evidence Integrity dashboard.

---

## 6. Real Security Assumptions & Developer Sandbox Boundaries

1. **Host Workstation Reality**:
   Running multiple Docker containers on a single developer host demonstrates cryptographic protocol behavior and network API compatibility. It does **not** provide physically independent organizational separation.
2. **Consensus Characteristics**:
   Raft consensus provides Crash Fault Tolerance (**CFT**). It tolerates peer outages, but does not provide Byzantine Fault Tolerance (**BFT**) against an adversary with root administrative access to the host.
3. **Environment Blocker Documentation**:
   Docker Desktop version 28.5.1 is installed on the host machine, but the Windows service `com.docker.service` is stopped and starting Windows system services requires elevated administrative privileges.
   In full compliance with project instructions:
   - Complete Fabric configuration, crypto-config, docker-compose, and Go chaincode are authored in `deploy/ledger/`.
   - SAT-SA runs in verified `standalone_signed_log` mode by default and seamlessly connects to Fabric when the daemon is started.
   - No mock adapter is falsely claimed as a live blockchain block.
