"""Phase 8: akun lokal, token API, dan profil scan untuk BR-62 (ADR 0020).

Revision ID: 0002
Revises: 0001
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None

TS = sa.DateTime(timezone=True)


def upgrade() -> None:
    op.create_table(
        "scan_profile",
        sa.Column("scan_id", sa.String(40), sa.ForeignKey("scan.id"), primary_key=True),
        sa.Column("profile_schema_version", sa.String(32), nullable=False),
        sa.Column("features", sa.JSON(), nullable=False),
        sa.Column("leakage_flagged", sa.Boolean(), nullable=False),
    )
    op.create_table(
        "app_user",
        sa.Column("id", sa.String(40), primary_key=True),
        sa.Column("email", sa.String(320), nullable=False, unique=True),
        sa.Column("password_hash", sa.Text(), nullable=False),
        sa.Column("created_at", TS, nullable=False),
        sa.Column("disabled_at", TS, nullable=True),
    )
    op.create_table(
        "api_token",
        sa.Column("id", sa.String(40), primary_key=True),
        sa.Column("user_id", sa.String(40), sa.ForeignKey("app_user.id"), nullable=False),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("prefix", sa.String(16), nullable=False),
        sa.Column("token_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("created_at", TS, nullable=False),
        sa.Column("expires_at", TS, nullable=True),
        sa.Column("revoked_at", TS, nullable=True),
        sa.Column("last_used_at", TS, nullable=True),
    )


def downgrade() -> None:
    for table in ("api_token", "app_user", "scan_profile"):
        op.drop_table(table)
