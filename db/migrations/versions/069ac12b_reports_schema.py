"""reports_schema

Revision ID: 069ac12b5d33
Revises: 0589b91e4f22
Create Date: 2026-09-21 18:30:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "069ac12b5d33"
down_revision: Union[str, None] = "0589b91e4f22"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "assessment_reports",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("run_id", sa.String(length=36), nullable=False),
        sa.Column("portfolio_id", sa.String(length=36), nullable=True),
        sa.Column("entity_id", sa.String(length=64), nullable=False),
        sa.Column("created_by", sa.String(length=100), nullable=False),
        sa.Column("decision_cutoff_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="completed"),
        sa.Column(
            "report_schema_version", sa.String(length=32), nullable=False, server_default="v1.0"
        ),
        sa.Column("snapshot_json", sa.Text(), nullable=False),
        sa.Column("html_content", sa.Text(), nullable=False),
        sa.Column("checksum_manifest_json", sa.Text(), nullable=False),
        sa.Column("notes", sa.String(length=500), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["run_id"], ["analysis_runs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["portfolio_id"], ["review_portfolios.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_assessment_reports_run", "assessment_reports", ["run_id"])
    op.create_index(
        "ix_assessment_reports_entity_created",
        "assessment_reports",
        ["entity_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_assessment_reports_entity_created", table_name="assessment_reports")
    op.drop_index("ix_assessment_reports_run", table_name="assessment_reports")
    op.drop_table("assessment_reports")
