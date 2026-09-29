"""Pydantic schemas for Evidence Integrity, Custody Events, and Ledger Outbox."""

from __future__ import annotations

import datetime
from typing import Any, Dict, List

from pydantic import BaseModel, Field


class CustodyEventResponse(BaseModel):
    id: str
    entity_id: str
    event_type: str
    sequence_number: int
    previous_event_commitment: str
    object_type: str
    object_id: str
    object_version: int
    evidence_commitment: str
    claimed_event_time: datetime.datetime
    recorded_at: datetime.datetime
    actor_id: str
    signing_key_id: str
    signature: str
    payload_digest: str
    metadata: Dict[str, Any] = Field(default_factory=dict)


class CustodyCheckpointResponse(BaseModel):
    id: str
    entity_id: str
    sequence_number: int
    tree_size: int
    root_hash: str
    signing_key_id: str
    signature: str
    checkpoint_time: datetime.datetime


class IntegrityStatusResponse(BaseModel):
    ledger_mode: str = Field(description="'fabric_anchored' or 'standalone_signed_log'")
    fabric_configured: bool
    channel_name: str
    chaincode_name: str
    service_key_id: str
    service_public_key: str
    pending_outbox_count: int
    anchored_outbox_count: int
    failed_outbox_count: int


class VerifyRequest(BaseModel):
    target_type: str = Field(description="'submission', 'report_snapshot', or 'custody_log'")
    target_id: str
    entity_id: str


class VerifyResponse(BaseModel):
    is_valid: bool
    status: str
    target_id: str
    target_type: str
    files_checked: int
    records_checked: int
    signatures_verified: int
    issues: List[str] = Field(default_factory=list)
    details: Dict[str, Any] = Field(default_factory=dict)
