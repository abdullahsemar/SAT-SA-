# Hyperledger Fabric Permissioned Ledger Architecture for SAT-SA

## 1. Role & Architectural Boundaries

SAT-SA integrates **Hyperledger Fabric (v2.5.x LTS)** as a permissioned, append-only anchor for cryptographic evidence commitments and custody audit events.

> [!IMPORTANT]
> **Strict Operational Scoping**:
> - Cases, raw telemetry, investigator notes, and analytical metrics **never go on the shared blockchain**. They remain strictly in SQL and local evidence storage.
> - The ledger stores only minimal, privacy-preserving cryptographic metadata: `event_id`, `entity_id`, `event_type`, `sequence_number`, `evidence_commitment` (hash digest), `payload_digest`, `signature`, and `timestamp`.
> - Blockchain is an auditability enhancement for regulatory non-repudiation, **not** a replacement for the supervisory analytics workbench.

---

## 2. Network Topology & Participants

The local permissioned network consists of two logically separate organizations with distinct cryptographic identities:

```mermaid
graph TD
    subgraph Orderer Organization
        ORD[orderer.sat-sa.local<br/>Raft Consensus]
    end

    subgraph Org 1: Regulator (NCIIPC / NTRO)
        CA1[ca.regulator.nciipc.gov]
        P1[peer0.regulator.nciipc.gov<br/>Port 7051]
    end

    subgraph Org 2: Supervised Entity (CSE Bank-01)
        CA2[ca.supervised.bank01.org]
        P2[peer0.supervised.bank01.org<br/>Port 9051]
    end

    ORD --- P1
    ORD --- P2
    P1 <-->|Channel: sat-sa-channel<br/>Endorsement: Majorities| P2
```

1. **RegulatorOrg (`RegulatorMSP`)**:
   - National supervisory authority (NCIIPC / NTRO).
   - Peer: `peer0.regulator.nciipc.gov` (7051).
   - Endorsement requirement: All supervisory assessment anchors require regulator endorsement.
2. **SupervisedOrg (`SupervisedMSP`)**:
   - Cyber Security Operations Center of the Supervised Entity (`CSE-BANK-01`).
   - Peer: `peer0.supervised.bank01.org` (9051).
   - Submits evidence intake commitments during periodic reporting.
3. **OrdererOrg (`OrdererMSP`)**:
   - Raft-based Crash Fault Tolerant (CFT) ordering service.
   - Node: `orderer.sat-sa.local` (7050).

---

## 3. Trust Model & Security Assumptions

1. **Crash Fault Tolerance (CFT) vs Byzantine Fault Tolerance (BFT)**:
   - The Raft ordering service tolerates crash failures ($2f + 1$ nodes required for $f$ crashes). It does **not** solve Byzantine (malicious orderer) attacks.
   - For multi-stakeholder adversarial resistance, distinct peer endorsements (`AND('RegulatorMSP.peer', 'SupervisedMSP.peer')`) prevent either single party from unilaterally inserting false transactions.
2. **Local Workstation Boundaries**:
   - In development and single-node prototype environments, running multiple containers on one workstation demonstrates protocol behavior and cryptographic handshakes, **not** independently administered trust.
3. **Data Exposure & Privacy**:
   - Identifiers on-chain are opaque UUIDs and cryptographic digests. Guessable values (e.g. low-entropy case IDs) are salted with 128-bit per-record nonces stored only in authorized local storage.

---

## 4. Chaincode Contract Specification (`sat_sa_custody`)

The smart contract implements 4 methods:
- `AnchorCommitment(payloadJSON)`: Idempotently appends a commitment. Rejects unauthorized organizations and conflicts on same idempotency key with different payload.
- `GetCommitment(eventId)`: Queries commitment record.
- `VerifyCommitment(eventId, expectedDigest)`: Compares on-chain payload digest against expected digest.
- `GetCommitmentHistory(eventId)`: Queries immutable modification history.

---

## 5. Startup & Operations Commands

### Prerequisites
- Docker Engine & Docker Compose
- Fabric binaries (`peer`, `configtxgen`, `cryptogen`) or containerized CLI

### Start Network
```bash
./deploy/ledger/start_network.sh
# or on Windows PowerShell:
.\deploy\ledger\start_network.ps1
```

### Stop Network
```bash
./deploy/ledger/stop_network.sh
# or on Windows PowerShell:
.\deploy\ledger\stop_network.ps1
```

### Operational Modes
1. **Fabric Anchored Mode (`FABRIC_ENABLED=true`)**:
   - Outbox worker connects to Fabric Gateway on `peer0.regulator.nciipc.gov`.
   - Obtains validated transaction receipts with block height and endorsing peers.
2. **Standalone Signed-Log Mode (`FABRIC_ENABLED=false`)**:
   - Default fallback when Fabric network is offline or unconfigured.
   - Outbox records status `not_configured`.
   - Application logs Ed25519-signed custody events with Merkle checkpoints locally without failing supervisory workflows.
