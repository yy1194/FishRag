"""add rag evaluation jobs

Revision ID: 20260618_0002
Revises: 20260617_0001
Create Date: 2026-06-18
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260618_0002"
down_revision = "20260617_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "rag_evaluation_jobs",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("owner_user_id", sa.String(length=36)),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("mode", sa.String(length=32), nullable=False),
        sa.Column("ks", sa.JSON(), nullable=False),
        sa.Column("example_count", sa.Integer(), nullable=False),
        sa.Column("parameters", sa.JSON(), nullable=False),
        sa.Column("examples", sa.JSON(), nullable=False),
        sa.Column("report", sa.JSON()),
        sa.Column("error", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.ForeignKeyConstraint(["owner_user_id"], ["users.id"], ondelete="SET NULL"),
    )
    op.create_index(
        "ix_rag_evaluation_jobs_status_updated_at",
        "rag_evaluation_jobs",
        ["status", "updated_at"],
    )
    op.create_index(
        "ix_rag_evaluation_jobs_owner_user_id",
        "rag_evaluation_jobs",
        ["owner_user_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_rag_evaluation_jobs_owner_user_id", table_name="rag_evaluation_jobs")
    op.drop_index("ix_rag_evaluation_jobs_status_updated_at", table_name="rag_evaluation_jobs")
    op.drop_table("rag_evaluation_jobs")
