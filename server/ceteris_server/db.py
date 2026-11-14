"""Metadata store online (architecture.md 6.3): dataset, scan, finding, impact_estimate,
model_version.

Postgres di Docker Compose dan produksi; SQLite untuk pengembangan dan uji. Store ini tidak
menyimpan data mentah yang dipindai (AC-6): snapshot hanya di object store, dirujuk lewat
`snapshot_uri`; yang tersimpan di sini hanya hasil agregat `ScanReport`. Store online terpisah dari
run store riset (AC-11).

Skema dibuat dengan `create_all` di R1 (ADR 0018); migrasi berversi menyusul bila skema mulai
berubah setelah data pengguna ada.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    String,
    Text,
    create_engine,
)
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker

SCAN_STATUSES = ("queued", "running", "done", "failed")


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex}"


def now() -> datetime:
    return datetime.now(UTC)


class Base(DeclarativeBase):
    pass


class Dataset(Base):
    __tablename__ = "dataset"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    target: Mapped[str] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ModelVersion(Base):
    __tablename__ = "model_version"

    version: Mapped[str] = mapped_column(String(64), primary_key=True)
    profile_schema_version: Mapped[str] = mapped_column(String(32))
    experimental: Mapped[bool] = mapped_column(Boolean)
    registered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class Scan(Base):
    __tablename__ = "scan"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    dataset_id: Mapped[str] = mapped_column(ForeignKey("dataset.id"))
    status: Mapped[str] = mapped_column(String(16), default="queued")
    snapshot_uri: Mapped[str] = mapped_column(Text)
    snapshot_key: Mapped[str] = mapped_column(Text)
    model_version: Mapped[str | None] = mapped_column(
        ForeignKey("model_version.version"), nullable=True
    )
    report: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    error: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    trace_id: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Finding(Base):
    __tablename__ = "finding"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    scan_id: Mapped[str] = mapped_column(ForeignKey("scan.id"))
    issue_type: Mapped[str] = mapped_column(String(64))
    column: Mapped[str | None] = mapped_column(String(200), nullable=True)
    rows_affected_pct: Mapped[float] = mapped_column(Float)
    observed_or_estimated: Mapped[str] = mapped_column(String(16))
    recovery_potential: Mapped[float | None] = mapped_column(Float, nullable=True)
    rank: Mapped[int] = mapped_column()


class ImpactEstimate(Base):
    """`finding_id = null` berarti estimasi total scan (architecture.md 6.3)."""

    __tablename__ = "impact_estimate"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    scan_id: Mapped[str] = mapped_column(ForeignKey("scan.id"))
    finding_id: Mapped[str | None] = mapped_column(ForeignKey("finding.id"), nullable=True)
    metric: Mapped[str] = mapped_column(String(16))
    delta: Mapped[float] = mapped_column(Float)
    lo: Mapped[float] = mapped_column(Float)
    hi: Mapped[float] = mapped_column(Float)
    ood_score: Mapped[float] = mapped_column(Float)
    status: Mapped[str] = mapped_column(String(32))
    threshold: Mapped[float] = mapped_column(Float)
    model_version: Mapped[str] = mapped_column(ForeignKey("model_version.version"))


class Database:
    """Engine dan pabrik sesi; satu per proses."""

    def __init__(self, url: str) -> None:
        if url.startswith("sqlite:///") and not url.startswith("sqlite:///:memory:"):
            Path(url.removeprefix("sqlite:///")).parent.mkdir(parents=True, exist_ok=True)
        kwargs: dict[str, Any] = {}
        if url.startswith("sqlite"):
            kwargs["connect_args"] = {"check_same_thread": False}
        self.engine: Engine = create_engine(url, **kwargs)
        self._sessions = sessionmaker(self.engine, expire_on_commit=False)

    def create_all(self) -> None:
        Base.metadata.create_all(self.engine)

    @contextmanager
    def session(self) -> Iterator[Session]:
        session = self._sessions()
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()
