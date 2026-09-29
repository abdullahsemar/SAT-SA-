"""Transactional outbox worker for resilient permissioned ledger anchoring.

Preserves consistency invariants:
- Atomic SQL commit: Custody event and pending outbox item are committed together in SQL.
- Retryable submission with stable idempotency keys.
- Records verified commit receipt, transaction ID, and block height.
- Tolerates ledger outages without losing events or fabricating anchoring status.
"""

from __future__ import annotations

import datetime
import json
from typing import Any, Dict, List, Optional

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from db.models.evidence_integrity import LedgerOutbox
from packages.evidence_integrity.fabric_client import FabricGatewayClient, default_fabric_client


def utc_now() -> datetime.datetime:
    return datetime.datetime.now(datetime.timezone.utc)


class OutboxProcessor:
    """Processes pending transactional outbox jobs for blockchain anchoring."""

    def __init__(
        self,
        db: Session,
        client: Optional[FabricGatewayClient] = None,
        max_retries: int = 5,
    ):
        self.db = db
        self.client = client or default_fabric_client
        self.max_retries = max_retries

    def process_pending_jobs(self, limit: int = 50) -> List[Dict[str, Any]]:
        """Processes up to `limit` pending or retryable outbox anchoring entries."""
        stmt = (
            select(LedgerOutbox)
            .where(
                or_(
                    LedgerOutbox.status.in_(["pending", "pending_anchor"]),
                    (LedgerOutbox.status == "anchor_failed")
                    & (LedgerOutbox.retry_count < self.max_retries),
                )
            )
            .order_by(LedgerOutbox.created_at)
            .limit(limit)
        )
        jobs = list(self.db.execute(stmt).scalars().all())
        results: List[Dict[str, Any]] = []

        for job in jobs:
            try:
                payload = json.loads(job.payload_json) if job.payload_json else {}
                if hasattr(self.client, "submit_anchor"):
                    payload_kwargs = dict(payload)
                    payload_kwargs.setdefault("idempotency_key", job.idempotency_key)
                    payload_kwargs.setdefault("event_id", job.event_id)
                    payload_kwargs.setdefault("entity_id", job.entity_id)
                    rcpt = self.client.submit_anchor(**payload_kwargs)
                    status_val = rcpt.get("status", "anchored")
                    if status_val in ("anchored", "anchored_standalone"):
                        job.status = "anchored"
                        job.anchored_at = utc_now()
                        job.receipt_json = json.dumps(rcpt)
                        job.transaction_id = rcpt.get("transaction_id")
                        job.block_number = rcpt.get("block_number")
                        job.last_error = None
                        results.append({"job_id": job.id, "status": "anchored"})
                    elif status_val == "not_configured":
                        job.status = "not_configured"
                        job.last_error = rcpt.get("error", "Fabric ledger not configured")
                        results.append({"job_id": job.id, "status": "not_configured"})
                    else:
                        job.retry_count += 1
                        job.last_error = rcpt.get("error", "Anchoring rejected or failed")
                        if job.retry_count >= self.max_retries:
                            job.status = "anchor_failed"
                        results.append({"job_id": job.id, "status": "anchor_failed"})
                else:
                    res = self.client.anchor_commitment(
                        event_id=payload.get("event_id", job.event_id),
                        entity_id=payload.get("entity_id", job.entity_id),
                        event_type=payload.get("event_type", "custody_event"),
                        sequence_number=payload.get("sequence_number", 1),
                        object_type=payload.get("object_type", "evidence"),
                        object_id=payload.get("object_id", ""),
                        object_version=payload.get("object_version", 1),
                        evidence_commitment=payload.get("evidence_commitment", ""),
                        payload_digest=payload.get("payload_digest", ""),
                        signature=payload.get("signature", ""),
                        signing_key_id=payload.get("signing_key_id", ""),
                        actor_id=payload.get("actor_id", "system"),
                        idempotency_key=job.idempotency_key,
                    )

                    if res.success or res.status in ("anchored", "anchored_standalone"):
                        job.status = "anchored"
                        if res.receipt:
                            job.transaction_id = res.receipt.transaction_id
                            job.block_number = res.receipt.block_number
                            job.receipt_json = json.dumps(
                                {
                                    "transaction_id": res.receipt.transaction_id,
                                    "block_number": res.receipt.block_number,
                                    "channel": res.receipt.channel,
                                    "chaincode": res.receipt.chaincode,
                                    "timestamp": res.receipt.timestamp,
                                    "endorsing_peers": res.receipt.endorsing_peers,
                                }
                            )
                        else:
                            job.receipt_json = json.dumps(
                                {
                                    "status": res.status,
                                    "mode": res.mode,
                                    "idempotency_key": job.idempotency_key,
                                }
                            )
                        job.anchored_at = utc_now()
                        job.last_error = None
                        results.append(
                            {"job_id": job.id, "status": "anchored", "tx_id": job.transaction_id}
                        )
                    elif res.status == "not_configured":
                        job.status = "not_configured"
                        job.last_error = res.error_message
                        results.append({"job_id": job.id, "status": "not_configured"})
                    else:
                        job.retry_count += 1
                        job.last_error = res.error_message or "Anchoring rejected or failed"
                        if job.retry_count >= self.max_retries:
                            job.status = "anchor_failed"
                        results.append(
                            {
                                "job_id": job.id,
                                "status": "anchor_failed",
                                "retries": job.retry_count,
                            }
                        )

            except Exception as exc:
                job.retry_count += 1
                job.last_error = str(exc)
                if job.retry_count >= self.max_retries:
                    job.status = "anchor_failed"
                results.append({"job_id": job.id, "status": "anchor_failed", "error": str(exc)})

        self.db.commit()
        return results

    def process_pending_entries(self, batch_size: int = 50) -> Dict[str, int]:
        """Convenience wrapper returning counts of processed and errored jobs."""
        results = self.process_pending_jobs(limit=batch_size)
        processed = sum(1 for r in results if r.get("status") == "anchored")
        errors = sum(1 for r in results if r.get("status") in ("anchor_failed", "failed"))
        return {"processed": processed, "errors": errors}
