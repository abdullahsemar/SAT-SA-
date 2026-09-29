"""Signed append-only custody log, hash chaining, and checkpoint verification.

Preserves core architectural invariants:
- Monotonic sequence numbers per entity.
- Strict cryptographic hash chaining: previous_event_commitment = SHA256(previous_event_payload).
- Captures 5 meaningful milestones:
  1. submission_committed
  2. evidence_revision_registered
  3. assessment_finalized
  4. human_decision_recorded
  5. report_snapshot_finalized
- Distinguishes claimed event time from local recording time.
- Atomic SQL outbox enrollment for permissioned ledger anchoring.
- Standalone verification against trusted checkpoints without database boolean trust.
"""

from __future__ import annotations

import datetime
import json
import uuid
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from db.models.evidence_integrity import CustodyCheckpoint, CustodyEvent, LedgerOutbox
from packages.evidence_integrity.canonical import compute_canonical_digest
from packages.evidence_integrity.hashing import MerkleTree
from packages.evidence_integrity.signatures import (
    default_key_registry,
    sign_data,
    verify_signature,
)

GENESIS_COMMITMENT = "0" * 64


def utc_now() -> datetime.datetime:
    return datetime.datetime.now(datetime.timezone.utc)


class CustodyEventVerificationError(Exception):
    """Raised when an integrity check, rollback, or hash break is detected."""

    pass


class CustodyLogManager:
    """Manages the creation, verification, and checkpointing of signed custody events."""

    def __init__(
        self,
        db: Session,
        key_registry=None,
        signing_key_id: str = "service-audit-key-2026",
        private_key_b64: Optional[str] = None,
    ):
        self.db = db
        self.key_registry = key_registry or default_key_registry
        self.signing_key_id = signing_key_id
        self.private_key_b64 = private_key_b64

    def record_event(
        self,
        entity_id: str,
        event_type: str,
        object_type: str,
        object_id: str,
        object_version: int,
        evidence_commitment: str,
        actor_id: str,
        claimed_event_time: Optional[datetime.datetime] = None,
        metadata: Optional[Dict[str, Any]] = None,
        custom_signer=None,
    ) -> CustodyEvent:
        """Atomically appends a signed custody event and its pending ledger outbox task."""
        if claimed_event_time is None:
            claimed_event_time = utc_now()

        # 1. Fetch latest event for this entity to obtain sequence and previous hash
        stmt = (
            select(CustodyEvent)
            .where(CustodyEvent.entity_id == entity_id)
            .order_by(desc(CustodyEvent.sequence_number))
            .limit(1)
        )
        latest_event = self.db.execute(stmt).scalar_one_or_none()

        sequence_number = (latest_event.sequence_number + 1) if latest_event else 1
        previous_commitment = latest_event.payload_digest if latest_event else GENESIS_COMMITMENT

        event_id = str(uuid.uuid4())

        # 2. Resolve signer
        if custom_signer:
            signing_key_id, private_key = custom_signer
        elif self.private_key_b64:
            from packages.evidence_integrity.signatures import load_private_key_b64

            signing_key_id = self.signing_key_id
            private_key = load_private_key_b64(self.private_key_b64)
        else:
            signing_key_id, private_key = self.key_registry.get_service_signer()

        # 3. Build canonical event envelope
        envelope = {
            "event_id": event_id,
            "entity_id": entity_id,
            "event_type": event_type,
            "sequence_number": sequence_number,
            "previous_event_commitment": previous_commitment,
            "object_type": object_type,
            "object_id": object_id,
            "object_version": object_version,
            "evidence_commitment": evidence_commitment,
            "claimed_event_time": claimed_event_time.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "actor_id": actor_id,
            "signing_key_id": signing_key_id,
        }

        c_json, payload_digest = compute_canonical_digest(envelope)
        sig_b64 = sign_data(private_key, c_json.encode("utf-8"))

        event = CustodyEvent(
            id=event_id,
            entity_id=entity_id,
            event_type=event_type,
            sequence_number=sequence_number,
            previous_event_commitment=previous_commitment,
            object_type=object_type,
            object_id=object_id,
            object_version=object_version,
            evidence_commitment=evidence_commitment,
            claimed_event_time=claimed_event_time,
            recorded_at=utc_now(),
            actor_id=actor_id,
            signing_key_id=signing_key_id,
            signature=sig_b64,
            payload_digest=payload_digest,
            metadata_json=json.dumps(metadata or {}),
        )
        self.db.add(event)

        # 4. Transactional Outbox: Write anchoring job in the same SQL transaction
        idempotency_key = (
            f"anchor:{entity_id}:{event_type}:{object_id}:v{object_version}:{event_id}"
        )
        outbox_payload = {
            "event_id": event_id,
            "entity_id": entity_id,
            "event_type": event_type,
            "sequence_number": sequence_number,
            "object_type": object_type,
            "object_id": object_id,
            "object_version": object_version,
            "evidence_commitment": evidence_commitment,
            "payload_digest": payload_digest,
            "signature": sig_b64,
            "signing_key_id": signing_key_id,
            "recorded_at": event.recorded_at.isoformat(),
        }

        outbox = LedgerOutbox(
            id=str(uuid.uuid4()),
            idempotency_key=idempotency_key,
            event_id=event_id,
            entity_id=entity_id,
            channel_name="sat-sa-channel",
            chaincode_name="sat_sa_custody",
            payload_json=json.dumps(outbox_payload),
            status="pending_anchor",
            retry_count=0,
        )
        self.db.add(outbox)
        self.db.flush()

        return event

    def create_checkpoint(self, entity_id: str) -> Optional[CustodyCheckpoint]:
        """Calculates Merkle root over all custody events to date and signs an audit checkpoint."""
        events_stmt = (
            select(CustodyEvent)
            .where(CustodyEvent.entity_id == entity_id)
            .order_by(CustodyEvent.sequence_number)
        )
        events = list(self.db.execute(events_stmt).scalars().all())
        if not events:
            return None

        # Build Merkle tree over the sequential event digests
        tree = MerkleTree([e.payload_digest for e in events])
        root_hex = tree.get_root_hex()
        tree_size = tree.tree_size
        latest_seq = events[-1].sequence_number

        signing_key_id, private_key = self.key_registry.get_service_signer()
        checkpoint_payload = {
            "entity_id": entity_id,
            "sequence_number": latest_seq,
            "tree_size": tree_size,
            "root_hash": root_hex,
            "signing_key_id": signing_key_id,
        }
        c_json, _ = compute_canonical_digest(checkpoint_payload)
        sig_b64 = sign_data(private_key, c_json.encode("utf-8"))

        checkpoint = CustodyCheckpoint(
            id=str(uuid.uuid4()),
            entity_id=entity_id,
            sequence_number=latest_seq,
            tree_size=tree_size,
            root_hash=root_hex,
            signing_key_id=signing_key_id,
            signature=sig_b64,
            checkpoint_time=utc_now(),
        )
        self.db.add(checkpoint)
        self.db.flush()
        return checkpoint

    def verify_event_chain(
        self, entity_id: str, expected_checkpoint: Optional[CustodyCheckpoint] = None
    ) -> Tuple[bool, List[str]]:
        """Verifies the unbroken cryptographic chain and Ed25519 signatures of the entity's custody log."""
        issues: List[str] = []
        events_stmt = (
            select(CustodyEvent)
            .where(CustodyEvent.entity_id == entity_id)
            .order_by(CustodyEvent.sequence_number)
        )
        events = list(self.db.execute(events_stmt).scalars().all())
        if not events:
            return True, []

        prev_hash = GENESIS_COMMITMENT
        for idx, ev in enumerate(events):
            expected_seq = idx + 1
            if ev.sequence_number != expected_seq:
                issues.append(
                    f"Sequence gap or reordering: expected {expected_seq}, observed {ev.sequence_number} (event {ev.id})"
                )

            if ev.previous_event_commitment != prev_hash:
                issues.append(
                    f"Hash link break at sequence {ev.sequence_number}: expected {prev_hash}, found {ev.previous_event_commitment}"
                )

            # Recompute payload digest
            envelope = {
                "event_id": ev.id,
                "entity_id": ev.entity_id,
                "event_type": ev.event_type,
                "sequence_number": ev.sequence_number,
                "previous_event_commitment": ev.previous_event_commitment,
                "object_type": ev.object_type,
                "object_id": ev.object_id,
                "object_version": ev.object_version,
                "evidence_commitment": ev.evidence_commitment,
                "claimed_event_time": ev.claimed_event_time.strftime("%Y-%m-%dT%H:%M:%SZ"),
                "actor_id": ev.actor_id,
                "signing_key_id": ev.signing_key_id,
            }
            c_json, recomputed_digest = compute_canonical_digest(envelope)
            if recomputed_digest != ev.payload_digest:
                issues.append(
                    f"Tampered event payload at sequence {ev.sequence_number}: recorded {ev.payload_digest}, recomputed {recomputed_digest}"
                )

            # Verify Ed25519 signature
            pub_key = self.key_registry.get_public_key(ev.signing_key_id)
            if not pub_key:
                issues.append(
                    f"Untrusted or revoked signing key {ev.signing_key_id} at sequence {ev.sequence_number}"
                )
            else:
                if not verify_signature(pub_key, c_json.encode("utf-8"), ev.signature):
                    issues.append(f"Invalid Ed25519 signature at sequence {ev.sequence_number}")

            prev_hash = ev.payload_digest

        # Checkpoint validation
        if expected_checkpoint:
            if len(events) < expected_checkpoint.tree_size:
                issues.append(
                    f"Rollback detected: expected tree size >= {expected_checkpoint.tree_size}, log contains {len(events)}"
                )
            else:
                sub_tree = MerkleTree(
                    [e.payload_digest for e in events[: expected_checkpoint.tree_size]]
                )
                if sub_tree.get_root_hex() != expected_checkpoint.root_hash:
                    issues.append(
                        f"Checkpoint root mismatch: expected {expected_checkpoint.root_hash}, observed {sub_tree.get_root_hex()}"
                    )

        return len(issues) == 0, issues

    def verify_log(
        self,
        entity_id: str,
        expected_sequence: Optional[int] = None,
        public_key_b64: Optional[str] = None,
        expected_checkpoint: Optional[CustodyCheckpoint] = None,
    ) -> Tuple[bool, List[str]]:
        """Verifies custody log for entity with optional expected sequence rollback check."""
        if public_key_b64:
            self.key_registry.register_key(self.signing_key_id, public_key_b64)

        events_stmt = (
            select(CustodyEvent)
            .where(CustodyEvent.entity_id == entity_id)
            .order_by(CustodyEvent.sequence_number)
        )
        events = list(self.db.execute(events_stmt).scalars().all())

        if expected_sequence is not None and len(events) < expected_sequence:
            raise CustodyEventVerificationError(
                f"Rollback detected: expected sequence >= {expected_sequence}, but log contains {len(events)}"
            )

        return self.verify_event_chain(entity_id, expected_checkpoint=expected_checkpoint)
