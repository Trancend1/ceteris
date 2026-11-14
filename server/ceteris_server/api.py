"""REST API `/v1` (F-L01; architecture.md 6.4).

API hanya memvalidasi permintaan, menyimpan snapshot unggahan ke object store, membuat job, dan
menyajikan hasil. API tidak menghitung profil atau estimasi (tabel kontainer architecture.md 3).
Semua galat berbentuk `{"error": {"code", "message", "details"}}`. Alias endpoint draf awal tidak
ada (ADR 0016 K6). Semua endpoint kecuali `GET /v1/health` dan `POST /v1/auth/login` butuh token
bearer (US8.1, ADR 0020). Histori dan perbandingan antar-scan: `GET /v1/datasets/{id}/scans`
(US2.1, BR-61, BR-62).
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Awaitable, Callable
from datetime import datetime
from pathlib import PurePosixPath
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, FastAPI, File, Form, Query, Request, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, Response
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, ConfigDict, Field
from starlette.exceptions import HTTPException as StarletteHTTPException

from ceteris.scan import SCHEMA_VERSION, ScanReport
from ceteris_server.auth import AuthError, authenticate, issue_token, resolve_token
from ceteris_server.db import ApiToken, Dataset, Scan, User, new_id, now
from ceteris_server.history import DatasetHistory, dataset_history
from ceteris_server.worker import ServerContext, build_context

log = logging.getLogger("ceteris_server.api")

ALLOWED_SUFFIXES = {".csv", ".parquet", ".pq"}  # BR-10
CHUNK = 1 << 20


class ErrorBody(BaseModel):
    code: str
    message: str
    details: list[Any] = Field(default_factory=list)


class ErrorResponse(BaseModel):
    error: ErrorBody


class DatasetIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=200)
    target: str = Field(min_length=1, max_length=200)


class DatasetOut(BaseModel):
    id: str
    name: str
    target: str
    created_at: datetime


class ScanOut(BaseModel):
    id: str
    dataset_id: str
    status: Literal["queued", "running", "done", "failed"]
    model_version: str | None
    report_schema_version: str = SCHEMA_VERSION
    error: ErrorBody | None
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None


class LoginIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: str = Field(min_length=3, max_length=320)
    password: str = Field(min_length=1, max_length=1024)


class TokenIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=200)


class IssuedTokenOut(BaseModel):
    """Teks token hanya muncul di respons ini; simpan sekarang."""

    id: str
    token: str
    prefix: str
    kind: Literal["session", "api"]
    expires_at: datetime | None


class TokenOut(BaseModel):
    id: str
    name: str
    prefix: str
    kind: Literal["session", "api"]
    created_at: datetime
    expires_at: datetime | None
    last_used_at: datetime | None


class MeOut(BaseModel):
    id: str
    email: str


class Principal(BaseModel):
    user_id: str
    email: str
    token_id: str


class Health(BaseModel):
    status: Literal["ok"]
    report_schema_version: str


class ApiError(Exception):
    def __init__(self, status: int, code: str, message: str, details: list[Any] | None = None):
        super().__init__(message)
        self.status, self.code, self.message, self.details = status, code, message, details or []


def _error(status: int, code: str, message: str, details: list[Any] | None = None) -> JSONResponse:
    body = ErrorResponse(error=ErrorBody(code=code, message=message, details=details or []))
    return JSONResponse(status_code=status, content=body.model_dump())


ERRORS: dict[int | str, dict[str, Any]] = {
    code: {"model": ErrorResponse} for code in (400, 401, 404, 409, 413, 415, 422, 501)
}
_BEARER = HTTPBearer(auto_error=False, description="Token `ctr_...` dari login atau token API")


def create_app(context: ServerContext | None = None) -> FastAPI:
    """Pabrik aplikasi; uji menyuntikkan konteks sendiri (SQLite, object store lokal)."""
    ctx = context or build_context()
    app = FastAPI(
        title="Ceteris API",
        version="1",
        summary="Estimasi dampak kekotoran data pada ΔAUC model (eksperimental, BR-35).",
    )

    @app.middleware("http")
    async def trace(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        """NFR-9: setiap permintaan punya `trace_id` yang diteruskan ke job scan."""
        trace_id = request.headers.get("x-request-id") or uuid.uuid4().hex
        request.state.trace_id = trace_id
        response = await call_next(request)
        response.headers["x-request-id"] = trace_id
        return response

    @app.exception_handler(ApiError)
    async def api_error(_: Request, exc: ApiError) -> JSONResponse:
        return _error(exc.status, exc.code, exc.message, exc.details)

    @app.exception_handler(RequestValidationError)
    async def validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
        details = [
            {"loc": [str(p) for p in e.get("loc", ())], "msg": str(e.get("msg", ""))}
            for e in exc.errors()
        ]
        return _error(422, "validation", "permintaan tidak sah", details)

    @app.exception_handler(StarletteHTTPException)
    async def http_error(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        response = _error(exc.status_code, "http", str(exc.detail))
        response.headers.update(exc.headers or {})
        if exc.status_code == 405:  # RFC 9110: `Allow` memuat semua metode untuk path ini
            response.headers["Allow"] = ", ".join(_allowed_methods(app, request))
        return response

    def current_user(
        credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_BEARER)],
    ) -> Principal:
        """US8.1: token bearer yang sah, belum dicabut, dan belum kedaluwarsa."""
        if credentials is None or credentials.scheme.lower() != "bearer":
            raise ApiError(401, "unauthorized", "butuh token bearer")
        with ctx.db.session() as session:
            try:
                user, token = resolve_token(session, credentials.credentials)
            except AuthError as err:
                raise ApiError(401, "unauthorized", str(err)) from err
            return Principal(user_id=user.id, email=user.email, token_id=token.id)

    @app.get("/v1/health", response_model=Health)
    def health() -> Health:
        return Health(status="ok", report_schema_version=SCHEMA_VERSION)

    @app.post("/v1/auth/login", response_model=IssuedTokenOut, status_code=201, responses=ERRORS)
    def login(body: LoginIn) -> IssuedTokenOut:
        """Akun lokal → token sesi 12 jam (ADR 0016 K4, ADR 0020)."""
        with ctx.db.session() as session:
            try:
                user = authenticate(session, body.email, body.password)
            except AuthError as err:
                raise ApiError(401, "unauthorized", str(err)) from err
            issued = issue_token(session, user, "session", "login")
            return IssuedTokenOut(**issued.__dict__)

    v1 = APIRouter(prefix="/v1", dependencies=[Depends(current_user)], responses=ERRORS)

    @v1.post("/auth/logout", status_code=204)
    def logout(me: Principal = Depends(current_user)) -> Response:
        with ctx.db.session() as session:
            token = session.get(ApiToken, me.token_id)
            if token is not None:
                token.revoked_at = now()
        return Response(status_code=204)

    @v1.get("/me", response_model=MeOut)
    def whoami(me: Principal = Depends(current_user)) -> MeOut:
        return MeOut(id=me.user_id, email=me.email)

    @v1.post("/tokens", response_model=IssuedTokenOut, status_code=201)
    def create_token(body: TokenIn, me: Principal = Depends(current_user)) -> IssuedTokenOut:
        with ctx.db.session() as session:
            user = session.get(User, me.user_id)
            if user is None:
                raise ApiError(401, "unauthorized", "pengguna tidak ada")
            issued = issue_token(session, user, "api", body.name)
            return IssuedTokenOut(**issued.__dict__)

    @v1.get("/tokens", response_model=list[TokenOut])
    def list_tokens(me: Principal = Depends(current_user)) -> list[TokenOut]:
        with ctx.db.session() as session:
            rows = (
                session.query(ApiToken)
                .filter(ApiToken.user_id == me.user_id, ApiToken.revoked_at.is_(None))
                .order_by(ApiToken.created_at)
            )
            return [
                TokenOut(
                    id=r.id,
                    name=r.name,
                    prefix=r.prefix,
                    kind=r.kind,  # type: ignore[arg-type]
                    created_at=r.created_at,
                    expires_at=r.expires_at,
                    last_used_at=r.last_used_at,
                )
                for r in rows
            ]

    @v1.delete("/tokens/{token_id}", status_code=204)
    def revoke_token(token_id: str, me: Principal = Depends(current_user)) -> Response:
        with ctx.db.session() as session:
            token = session.get(ApiToken, token_id)
            if token is None or token.user_id != me.user_id or token.revoked_at is not None:
                raise ApiError(404, "not_found", f"token {token_id} tidak ada")
            token.revoked_at = now()
        return Response(status_code=204)

    @v1.get("/datasets/{dataset_id}/scans", response_model=DatasetHistory)
    def history(dataset_id: str) -> DatasetHistory:
        with ctx.db.session() as session:
            if _dataset(session, dataset_id) is None:
                raise ApiError(404, "not_found", f"dataset {dataset_id} tidak ada")
            return dataset_history(session, ctx.registry, dataset_id)

    @v1.post("/datasets", response_model=DatasetOut, status_code=201)
    def create_dataset(body: DatasetIn) -> DatasetOut:
        with ctx.db.session() as session:
            row = Dataset(id=new_id("ds"), name=body.name, target=body.target)
            session.add(row)
            session.flush()
            return DatasetOut(
                id=row.id, name=row.name, target=row.target, created_at=row.created_at
            )

    @v1.post("/scans", response_model=ScanOut, status_code=202)
    async def create_scan(
        request: Request,
        dataset_id: Annotated[str, Form(min_length=1, max_length=40)],
        file: Annotated[UploadFile, File(description="CSV atau Parquet (BR-10), ≤ 500 MB")],
    ) -> ScanOut:
        suffix = PurePosixPath(file.filename or "").suffix.lower()
        if suffix not in ALLOWED_SUFFIXES:
            raise ApiError(415, "input_contract", "BR-10 format_unsupported", [suffix or "?"])
        with ctx.db.session() as session:
            if _dataset(session, dataset_id) is None:
                raise ApiError(404, "not_found", f"dataset {dataset_id} tidak ada")
        scan_id = new_id("scn")
        key = f"snapshots/{scan_id}{'.parquet' if suffix == '.pq' else suffix}"
        data = await _read_limited(file, ctx.settings.max_upload_bytes)
        ctx.store.put_bytes(key, data)
        trace_id = str(request.state.trace_id)
        with ctx.db.session() as session:
            row = Scan(
                id=scan_id,
                dataset_id=dataset_id,
                status="queued",
                snapshot_key=key,
                snapshot_uri=ctx.store.uri(key),
                trace_id=trace_id,
            )
            session.add(row)
        log.info("scan dibuat", extra={"scan_id": scan_id, "trace_id": trace_id})
        ctx.queue.enqueue(scan_id, trace_id)
        return _scan_out(ctx, scan_id)

    @v1.get("/scans/{scan_id}", response_model=ScanOut)
    def get_scan(scan_id: str) -> ScanOut:
        return _scan_out(ctx, scan_id)

    @v1.get(
        "/scans/{scan_id}/report",
        response_model=ScanReport,
        responses={409: {"model": ErrorResponse, "description": "scan belum selesai"}},
    )
    def get_report(
        scan_id: str, format: Annotated[Literal["json", "html"], Query()] = "json"
    ) -> dict[str, Any]:
        if format == "html":
            raise ApiError(501, "not_implemented", "laporan HTML dibangun di Phase 11 (F-L02)")
        with ctx.db.session() as session:
            scan = _live_scan(session, scan_id)
            if scan.status != "done" or scan.report is None:
                raise ApiError(409, "not_ready", f"scan berstatus {scan.status}")
            return dict(scan.report)

    app.include_router(v1)
    return app


def _allowed_methods(app: FastAPI, request: Request) -> list[str]:
    """Gabungan metode semua route yang cocok dengan path (Starlette hanya memakai yang pertama)."""
    from starlette.routing import Match, Route

    methods: set[str] = set()
    for route in app.router.routes:
        if isinstance(route, Route) and route.methods:
            match, _ = route.matches({"type": "http", "path": request.url.path, "method": ""})
            if match != Match.NONE:
                methods.update(route.methods)
    return sorted(methods)


async def _read_limited(file: UploadFile, limit: int) -> bytes:
    """ADR 0016 K5: tolak unggahan di atas batas tanpa membaca seluruhnya ke memori."""
    chunks: list[bytes] = []
    size = 0
    while chunk := await file.read(CHUNK):
        size += len(chunk)
        if size > limit:
            raise ApiError(
                413,
                "upload_too_large",
                f"berkas melebihi {limit} byte; pakai SDK/CLI untuk data besar (ADR 0016 K5)",
            )
        chunks.append(chunk)
    return b"".join(chunks)


def _dataset(session: Any, dataset_id: str) -> Dataset | None:
    row = session.get(Dataset, dataset_id)
    return None if row is None or row.deleted_at is not None else row


def _live_scan(session: Any, scan_id: str) -> Scan:
    scan = session.get(Scan, scan_id)
    if scan is None or scan.deleted_at is not None:
        raise ApiError(404, "not_found", f"scan {scan_id} tidak ada")
    return scan  # type: ignore[no-any-return]


def _scan_out(ctx: ServerContext, scan_id: str) -> ScanOut:
    with ctx.db.session() as session:
        scan = _live_scan(session, scan_id)
        return ScanOut(
            id=scan.id,
            dataset_id=scan.dataset_id,
            status=scan.status,  # type: ignore[arg-type]
            model_version=scan.model_version,
            error=ErrorBody(**scan.error) if scan.error else None,
            created_at=scan.created_at,
            started_at=scan.started_at,
            finished_at=scan.finished_at,
        )
