"""review_schema

Revision ID: 0589b91e4f22
Revises: 0478a82d3e11
Create Date: 2026-09-21 16:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0589b91e4f22"
down_revision: Union[str, None] = "0478a82d3e11"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. review_portfolios
    op.create_table(
        "review_portfolios",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("run_id", sa.String(length=36), nullable=False),
        sa.Column("entity_id", sa.String(length=64), nullable=False),
        sa.Column("created_by", sa.String(length=100), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("seed", sa.Integer(), nullable=False, server_default="42"),
        sa.Column("parameters_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("summary_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("sampling_frame_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["run_id"], ["analysis_runs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_review_portfolios_entity_run",
        "review_portfolios",
        ["entity_id", "run_id"],
        unique=False,
    )
    op.create_index(
        "ix_review_portfolios_run_id",
        "review_portfolios",
        ["run_id"],
        unique=False,
    )
    op.create_index(
        "ix_review_portfolios_entity_id",
        "review_portfolios",
        ["entity_id"],
        unique=False,
    )

    # 2. review_items
    op.create_table(
        "review_items",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("portfolio_id", sa.String(length=36), nullable=False),
        sa.Column("unit_id", sa.String(length=100), nullable=False),
        sa.Column("unit_type", sa.String(length=32), nullable=False),
        sa.Column("finding_id", sa.String(length=36), nullable=True),
        sa.Column("scope", sa.String(length=255), nullable=False),
        sa.Column("stratum", sa.String(length=32), nullable=False),
        sa.Column("selection_rank", sa.Integer(), nullable=False),
        sa.Column("marginal_reasons_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("evidence_references_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("unknowns_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("what_examiner_learns", sa.Text(), nullable=False),
        sa.Column("estimated_review_minutes", sa.Float(), nullable=False, server_default="10.0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["portfolio_id"], ["review_portfolios.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["finding_id"], ["findings.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_review_items_port_rank",
        "review_items",
        ["portfolio_id", "selection_rank"],
        unique=False,
    )
    op.create_index(
        "ix_review_items_portfolio_id",
        "review_items",
        ["portfolio_id"],
        unique=False,
    )
    op.create_index(
        "ix_review_items_unit_id",
        "review_items",
        ["unit_id"],
        unique=False,
    )
    op.create_index(
        "ix_review_items_finding_id",
        "review_items",
        ["finding_id"],
        unique=False,
    )

    # 3. review_decisions
    op.create_table(
        "review_decisions",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("finding_id", sa.String(length=36), nullable=True),
        sa.Column("review_item_id", sa.String(length=36), nullable=True),
        sa.Column("entity_id", sa.String(length=64), nullable=False),
        sa.Column("reviewer_id", sa.String(length=36), nullable=False),
        sa.Column("reviewer_username", sa.String(length=100), nullable=False),
        sa.Column("state", sa.String(length=50), nullable=False),
        sa.Column("rationale", sa.Text(), nullable=False),
        sa.Column("cited_evidence_ids_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("superseded_decision_id", sa.String(length=36), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["finding_id"], ["findings.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["review_item_id"], ["review_items.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["reviewer_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["superseded_decision_id"], ["review_decisions.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_review_decisions_finding_created",
        "review_decisions",
        ["finding_id", "created_at"],
        unique=False,
    )
    op.create_index(
        "ix_review_decisions_item_created",
        "review_decisions",
        ["review_item_id", "created_at"],
        unique=False,
    )
    op.create_index(
        "ix_review_decisions_entity_id",
        "review_decisions",
        ["entity_id"],
        unique=False,
    )

    # 4. evidence_requests
    op.create_table(
        "evidence_requests",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("finding_id", sa.String(length=36), nullable=True),
        sa.Column("review_item_id", sa.String(length=36), nullable=True),
        sa.Column("entity_id", sa.String(length=64), nullable=False),
        sa.Column("requester_id", sa.String(length=36), nullable=False),
        sa.Column("missing_artifact", sa.Text(), nullable=False),
        sa.Column("distinguishing_question", sa.Text(), nullable=False),
        sa.Column("responsible_owner", sa.String(length=100), nullable=False),
        sa.Column("due_date", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="open"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["finding_id"], ["findings.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["review_item_id"], ["review_items.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["requester_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_evidence_requests_entity_status",
        "evidence_requests",
        ["entity_id", "status"],
        unique=False,
    )

    # 5. review_audit_events
    op.create_table(
        "review_audit_events",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("entity_id", sa.String(length=64), nullable=False),
        sa.Column("event_type", sa.String(length=64), nullable=False),
        sa.Column("actor_id", sa.String(length=36), nullable=False),
        sa.Column("actor_username", sa.String(length=100), nullable=False),
        sa.Column("target_type", sa.String(length=64), nullable=False),
        sa.Column("target_id", sa.String(length=64), nullable=False),
        sa.Column("details_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_review_audit_entity_event",
        "review_audit_events",
        ["entity_id", "event_type"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_table("review_audit_events")
    op.drop_table("evidence_requests")
    op.drop_table("review_decisions")
    op.drop_table("review_items")
    op.drop_table("review_portfolios")
