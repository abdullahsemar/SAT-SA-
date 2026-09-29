"""semantic_schema

Revision ID: 0478a82d3e11
Revises: 03696b25837f
Create Date: 2026-09-21 14:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0478a82d3e11"
down_revision: Union[str, None] = "03696b25837f"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "semantic_passage_chunks",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("submission_id", sa.String(length=36), nullable=False),
        sa.Column("entity_id", sa.String(length=64), nullable=False),
        sa.Column("source_id", sa.String(length=100), nullable=False),
        sa.Column("record_type", sa.String(length=64), nullable=False),
        sa.Column("record_id", sa.String(length=255), nullable=False),
        sa.Column("chunk_index", sa.Integer(), nullable=False),
        sa.Column("start_char", sa.Integer(), nullable=False),
        sa.Column("end_char", sa.Integer(), nullable=False),
        sa.Column("raw_text", sa.Text(), nullable=False),
        sa.Column("normalized_text", sa.Text(), nullable=False),
        sa.Column("chunk_hash", sa.String(length=64), nullable=False),
        sa.Column("vector_json", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["submission_id"], ["submissions.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["entity_id"], ["cses.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("semantic_passage_chunks", schema=None) as batch_op:
        batch_op.create_index(
            "ix_chunks_entity_record", ["entity_id", "record_type", "record_id"], unique=False
        )
        batch_op.create_index(
            "ix_chunks_submission_hash", ["submission_id", "chunk_hash"], unique=False
        )
        batch_op.create_index(
            "ix_semantic_passage_chunks_submission_id", ["submission_id"], unique=False
        )
        batch_op.create_index("ix_semantic_passage_chunks_entity_id", ["entity_id"], unique=False)
        batch_op.create_index("ix_semantic_passage_chunks_source_id", ["source_id"], unique=False)
        batch_op.create_index(
            "ix_semantic_passage_chunks_record_type", ["record_type"], unique=False
        )
        batch_op.create_index("ix_semantic_passage_chunks_record_id", ["record_id"], unique=False)
        batch_op.create_index("ix_semantic_passage_chunks_chunk_hash", ["chunk_hash"], unique=False)

    op.create_table(
        "finding_similar_passages",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("finding_id", sa.String(length=36), nullable=False),
        sa.Column("run_id", sa.String(length=36), nullable=False),
        sa.Column("entity_id", sa.String(length=64), nullable=False),
        sa.Column("target_passage_text", sa.Text(), nullable=False),
        sa.Column("target_start_char", sa.Integer(), nullable=False),
        sa.Column("target_end_char", sa.Integer(), nullable=False),
        sa.Column("target_record_id", sa.String(length=255), nullable=False),
        sa.Column("matched_passage_text", sa.Text(), nullable=False),
        sa.Column("matched_start_char", sa.Integer(), nullable=False),
        sa.Column("matched_end_char", sa.Integer(), nullable=False),
        sa.Column("matched_record_id", sa.String(length=255), nullable=False),
        sa.Column("matched_source_id", sa.String(length=100), nullable=False),
        sa.Column("matched_record_type", sa.String(length=64), nullable=False),
        sa.Column("similarity_score", sa.Float(), nullable=False),
        sa.Column("semantic_mode", sa.String(length=32), nullable=False),
        sa.Column("method_used", sa.String(length=64), nullable=False),
        sa.Column("model_revision", sa.String(length=64), nullable=True),
        sa.Column("manifest_digest", sa.String(length=64), nullable=True),
        sa.Column("preprocessing_version", sa.String(length=32), nullable=False),
        sa.Column("fallback_reason", sa.String(length=255), nullable=True),
        sa.Column("possible_explanation", sa.String(length=128), nullable=False),
        sa.Column("caveats", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["finding_id"], ["findings.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["run_id"], ["analysis_runs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("finding_similar_passages", schema=None) as batch_op:
        batch_op.create_index(
            "ix_fsp_finding_score", ["finding_id", "similarity_score"], unique=False
        )
        batch_op.create_index("ix_fsp_run_entity", ["run_id", "entity_id"], unique=False)
        batch_op.create_index(
            "ix_finding_similar_passages_finding_id", ["finding_id"], unique=False
        )
        batch_op.create_index("ix_finding_similar_passages_run_id", ["run_id"], unique=False)
        batch_op.create_index("ix_finding_similar_passages_entity_id", ["entity_id"], unique=False)


def downgrade() -> None:
    op.drop_table("finding_similar_passages")
    op.drop_table("semantic_passage_chunks")
