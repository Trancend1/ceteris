"""Skema awal Phase 7: dataset, model_version, scan, finding, impact_estimate (ADR 0018).

Revision ID: 0001
Revises:
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None

TS = sa.DateTime(timezone=True)


def upgrade() -> None:
    op.create_table(
        "dataset",
        sa.Column("id", sa.String(40), primary_key=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("target", sa.String(200), nullable=False),
        sa.Column("created_at", TS, nullable=False),
        sa.Column("deleted_at", TS, nullable=True),
    )
    op.create_table(
        "model_version",
        sa.Column("version", sa.String(64), primary_key=True),
        sa.Column("profile_schema_version", sa.String(32), nullable=False),
        sa.Column("experimental", sa.Boolean(), nullable=False),
        sa.Column("registered_at", TS, nullable=False),
    )
    op.create_table(
        "scan",
        sa.Column("id", sa.String(40), primary_key=True),
        sa.Column("dataset_id", sa.String(40), sa.ForeignKey("dataset.id"), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("snapshot_uri", sa.Text(), nullable=False),
        sa.Column("snapshot_key", sa.Text(), nullable=False),
        sa.Column(
            "model_version", sa.String(64), sa.ForeignKey("model_version.version"), nullable=True
        ),
        sa.Column("report", sa.JSON(), nullable=True),
        sa.Column("error", sa.JSON(), nullable=True),
        sa.Column("trace_id", sa.String(64), nullable=False),
        sa.Column("created_at", TS, nullable=False),
        sa.Column("started_at", TS, nullable=True),
        sa.Column("finished_at", TS, nullable=True),
        sa.Column("deleted_at", TS, nullable=True),
    )
    op.create_table(
        "finding",
        sa.Column("id", sa.String(40), primary_key=True),
        sa.Column("scan_id", sa.String(40), sa.ForeignKey("scan.id"), nullable=False),
        sa.Column("issue_type", sa.String(64), nullable=False),
        sa.Column("column", sa.String(200), nullable=True),
        sa.Column("rows_affected_pct", sa.Float(), nullable=False),
        sa.Column("observed_or_estimated", sa.String(16), nullable=False),
        sa.Column("recovery_potential", sa.Float(), nullable=True),
        sa.Column("rank", sa.Integer(), nullable=False),
    )
    op.create_table(
        "impact_estimate",
        sa.Column("id", sa.String(40), primary_key=True),
        sa.Column("scan_id", sa.String(40), sa.ForeignKey("scan.id"), nullable=False),
        sa.Column("finding_id", sa.String(40), sa.ForeignKey("finding.id"), nullable=True),
        sa.Column("metric", sa.String(16), nullable=False),
        sa.Column("delta", sa.Float(), nullable=False),
        sa.Column("lo", sa.Float(), nullable=False),
        sa.Column("hi", sa.Float(), nullable=False),
        sa.Column("ood_score", sa.Float(), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("threshold", sa.Float(), nullable=False),
        sa.Column(
            "model_version", sa.String(64), sa.ForeignKey("model_version.version"), nullable=False
        ),
    )


def downgrade() -> None:
    for table in ("impact_estimate", "finding", "scan", "model_version", "dataset"):
        op.drop_table(table)
