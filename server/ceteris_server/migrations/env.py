"""Lingkungan Alembic: koneksi disuntikkan oleh `Database.migrate()` (ADR 0020)."""

from __future__ import annotations

from alembic import context

from ceteris_server.db import Base

connection = context.config.attributes["connection"]
context.configure(connection=connection, target_metadata=Base.metadata, render_as_batch=True)
with context.begin_transaction():
    context.run_migrations()
