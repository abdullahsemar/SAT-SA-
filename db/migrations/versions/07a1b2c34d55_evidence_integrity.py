"""evidence_integrity

Revision ID: 07a1b2c34d55
Revises: 069ac12b5d33
Create Date: 2026-09-27 12:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "07a1b2c34d55"
down_revision: Union[str, None] = "069ac12b5d33"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. evidence_commitments
    op.create_table(
        "evidence_commitments",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("entity_id", sa.String(length=64), nullable=False),
        sa.Column("submission_id", sa.String(length=36), nullable=True),
        sa.Column("commitment_type", sa.String(length=32), nullable=False),
        sa.Column("record_type", sa.String(length=64), nullable=True),
        sa.Column("record_id", sa.String(length=255), nullable=True),
        sa.Column("raw_file_sha256", sa.String(length=64), nullable=True),
        sa.Column("canonical_digest", sa.String(length=64), nullable=True),
        sa.Column("merkle_root", sa.String(length=64), nullable=True),
        sa.Column("nonce", sa.String(length=64), nullable=True),
        sa.Column(
            "representation_version",
            sa.String(length=32),
            nullable=False,
            server_default="v1.0-canonical-json",
        ),
        sa.Column("details_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["submission_id"], ["submissions.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_evidence_commitments_entity_id", "evidence_commitments", ["entity_id"], unique=False
    )
    op.create_index(
        "ix_evidence_commitments_submission_id",
        "evidence_commitments",
        ["submission_id"],
        unique=False,
    )
    op.create_index(
        "ix_evidence_commitments_canonical_digest",
        "evidence_commitments",
        ["canonical_digest"],
        unique=False,
    )
    op.create_index(
        "ix_evidence_commitments_merkle_root",
        "evidence_commitments",
        ["merkle_root"],
        unique=False,
    )
    op.create_index(
        "ix_ev_commit_entity_type",
        "evidence_commitments",
        ["entity_id", "commitment_type"],
        unique=False,
    )
    op.create_index(
        "ix_ev_commit_rec",
        "evidence_commitments",
        ["entity_id", "record_type", "record_id"],
        unique=False,
    )

    # 2. custody_events
    op.create_table(
        "custody_events",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("entity_id", sa.String(length=64), nullable=False),
        sa.Column("event_type", sa.String(length=64), nullable=False),
        sa.Column("sequence_number", sa.Integer(), nullable=False),
        sa.Column("previous_event_commitment", sa.String(length=64), nullable=False),
        sa.Column("object_type", sa.String(length=64), nullable=False),
        sa.Column("object_id", sa.String(length=255), nullable=False),
        sa.Column("object_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("evidence_commitment", sa.String(length=64), nullable=False),
        sa.Column("claimed_event_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("actor_id", sa.String(length=100), nullable=False),
        sa.Column("signing_key_id", sa.String(length=100), nullable=False),
        sa.Column("signature", sa.Text(), nullable=False),
        sa.Column("payload_digest", sa.String(length=64), nullable=False),
        sa.Column("metadata_json", sa.Text(), nullable=False, server_default="{}"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("entity_id", "sequence_number", name="uq_custody_entity_sequence"),
    )
    op.create_index("ix_custody_events_entity_id", "custody_events", ["entity_id"], unique=False)
    op.create_index(
        "ix_custody_events_evidence_commitment",
        "custody_events",
        ["evidence_commitment"],
        unique=False,
    )
    op.create_index(
        "ix_custody_obj",
        "custody_events",
        ["entity_id", "object_type", "object_id"],
        unique=False,
    )

    # 3. custody_checkpoints
    op.create_table(
        "custody_checkpoints",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("entity_id", sa.String(length=64), nullable=False),
        sa.Column("sequence_number", sa.Integer(), nullable=False),
        sa.Column("tree_size", sa.Integer(), nullable=False),
        sa.Column("root_hash", sa.String(length=64), nullable=False),
        sa.Column("signing_key_id", sa.String(length=100), nullable=False),
        sa.Column("signature", sa.Text(), nullable=False),
        sa.Column("checkpoint_time", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("entity_id", "sequence_number", name="uq_checkpoint_entity_seq"),
    )
    op.create_index(
        "ix_custody_checkpoints_entity_id", "custody_checkpoints", ["entity_id"], unique=False
    )

    # 4. ledger_outbox
    op.create_table(
        "ledger_outbox",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("idempotency_key", sa.String(length=128), nullable=False),
        sa.Column("event_id", sa.String(length=36), nullable=False),
        sa.Column("entity_id", sa.String(length=64), nullable=False),
        sa.Column(
            "channel_name", sa.String(length=64), nullable=False, server_default="sat-sa-channel"
        ),
        sa.Column(
            "chaincode_name",
            sa.String(length=64),
            nullable=False,
            server_default="sat_sa_custody",
        ),
        sa.Column("payload_json", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="pending_anchor"),
        sa.Column("retry_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("transaction_id", sa.String(length=128), nullable=True),
        sa.Column("block_number", sa.Integer(), nullable=True),
        sa.Column("receipt_json", sa.Text(), nullable=True),
        sa.Column("anchored_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["event_id"], ["custody_events.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("idempotency_key", name="uq_outbox_idempotency_key"),
    )
    op.create_index("ix_ledger_outbox_entity_id", "ledger_outbox", ["entity_id"], unique=False)
    op.create_index("ix_ledger_outbox_event_id", "ledger_outbox", ["event_id"], unique=False)
    op.create_index(
        "ix_outbox_status_retries", "ledger_outbox", ["status", "retry_count"], unique=False
    )

    # 5. verification_runs
    op.create_table(
        "verification_runs",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("entity_id", sa.String(length=64), nullable=False),
        sa.Column("target_type", sa.String(length=32), nullable=False),
        sa.Column("target_id", sa.String(length=255), nullable=False),
        sa.Column("verification_status", sa.String(length=32), nullable=False),
        sa.Column(
            "mode",
            sa.String(length=32),
            nullable=False,
            server_default="standalone_signed_log",
        ),
        sa.Column("checked_bytes_sha256", sa.String(length=64), nullable=True),
        sa.Column(
            "canonical_hash_verified", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
        sa.Column("signature_verified", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("checkpoint_verified", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("ledger_verified", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("details_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("actor_id", sa.String(length=100), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_verif_target",
        "verification_runs",
        ["entity_id", "target_type", "target_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_table("verification_runs")
    op.drop_table("ledger_outbox")
    op.drop_table("custody_checkpoints")
    op.drop_table("custody_events")
    op.drop_table("evidence_commitments")
