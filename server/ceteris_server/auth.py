"""Login R1: akun lokal dan token bearer (F-L05, US8.1; ADR 0016 K4, ADR 0020).

- Kata sandi disimpan sebagai hash Argon2id (`argon2-cffi`); panjang minimum 12 karakter.
- Token berbentuk `ctr_<acak>`. Yang disimpan hanya hash SHA-256-nya dan awalan untuk ditampilkan;
  teks token hanya muncul sekali saat dibuat.
- Token `session` (hasil login Web UI) kedaluwarsa 12 jam. Token `api` (SDK, CI) berlaku sampai
  dicabut pemiliknya.
- Kata sandi dan token tidak pernah ditulis ke log (NFR-5, NFR-9).
- Di R1 semua pengguna satu instans setara; RBAC dan OIDC menyusul di R2 (F-L09).
"""

from __future__ import annotations

import argparse
import getpass
import hashlib
import os
import secrets
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Literal

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from ceteris_server.db import ApiToken, Database, User, new_id, now
from ceteris_server.settings import Settings

SESSION_TTL = timedelta(hours=12)
MIN_PASSWORD = 12
TOKEN_PREFIX = "ctr_"
_HASHER = PasswordHasher()  # parameter bawaan argon2-cffi: Argon2id
# Hash tiruan agar verifikasi email yang tidak ada memakan waktu yang sama (hindari enumerasi).
_DUMMY_HASH = _HASHER.hash(secrets.token_urlsafe(16))

TokenKind = Literal["session", "api"]


class AuthError(RuntimeError):
    """Kredensial salah, token tidak sah, atau kata sandi terlalu lemah."""


@dataclass(frozen=True)
class IssuedToken:
    id: str
    token: str
    prefix: str
    kind: TokenKind
    expires_at: datetime | None


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def hash_password(password: str) -> str:
    if len(password) < MIN_PASSWORD:
        raise AuthError(f"kata sandi minimal {MIN_PASSWORD} karakter")
    return _HASHER.hash(password)


def _aware(value: datetime) -> datetime:
    """SQLite mengembalikan waktu tanpa zona; semua waktu disimpan dalam UTC."""
    return value if value.tzinfo else value.replace(tzinfo=UTC)


def create_user(session: Session, email: str, password: str) -> User:
    address = email.strip().lower()
    if "@" not in address:
        raise AuthError("email tidak sah")
    if session.scalar(select(User).where(User.email == address)) is not None:
        raise AuthError("email sudah terdaftar")
    user = User(id=new_id("usr"), email=address, password_hash=hash_password(password))
    session.add(user)
    session.flush()
    return user


def authenticate(session: Session, email: str, password: str) -> User:
    """Periksa email dan kata sandi; pesan galat sama untuk semua kegagalan."""
    user = session.scalar(select(User).where(User.email == email.strip().lower()))
    try:
        _HASHER.verify(user.password_hash if user else _DUMMY_HASH, password)
    except (VerificationError, InvalidHashError) as err:
        raise AuthError("email atau kata sandi salah") from err
    if user is None or user.disabled_at is not None:
        raise AuthError("email atau kata sandi salah")
    if _HASHER.check_needs_rehash(user.password_hash):
        user.password_hash = _HASHER.hash(password)
    return user


def issue_token(session: Session, user: User, kind: TokenKind, name: str) -> IssuedToken:
    token = TOKEN_PREFIX + secrets.token_urlsafe(32)
    expires = now() + SESSION_TTL if kind == "session" else None
    row = ApiToken(
        id=new_id("tok"),
        user_id=user.id,
        kind=kind,
        name=name,
        prefix=token[:12],
        token_hash=hash_token(token),
        expires_at=expires,
    )
    session.add(row)
    session.flush()
    return IssuedToken(row.id, token, row.prefix, kind, expires)


def resolve_token(session: Session, token: str) -> tuple[User, ApiToken]:
    """Token bearer → pengguna; menolak token tak dikenal, dicabut, atau kedaluwarsa."""
    if not token.startswith(TOKEN_PREFIX):
        raise AuthError("token tidak sah")
    row = session.scalar(select(ApiToken).where(ApiToken.token_hash == hash_token(token)))
    if row is None or row.revoked_at is not None:
        raise AuthError("token tidak sah")
    if row.expires_at is not None and _aware(row.expires_at) <= now():
        raise AuthError("token kedaluwarsa")
    user = session.get(User, row.user_id)
    if user is None or user.disabled_at is not None:
        raise AuthError("token tidak sah")
    row.last_used_at = now()
    return user, row


def main(argv: Sequence[str] | None = None) -> int:
    """Admin CLI: membuat pengguna. Tidak ada pendaftaran publik di R1."""
    parser = argparse.ArgumentParser(prog="python -m ceteris_server.auth")
    sub = parser.add_subparsers(dest="command", required=True)
    create = sub.add_parser("create-user", help="buat akun lokal")
    create.add_argument("--email", required=True)
    create.add_argument(
        "--password-env",
        default="CETERIS_NEW_USER_PASSWORD",
        help="variabel lingkungan berisi kata sandi; bila kosong, kata sandi diminta interaktif",
    )
    args = parser.parse_args(argv)
    password = os.environ.get(args.password_env) or getpass.getpass("Kata sandi: ")
    db = Database(Settings().database_url)
    db.migrate()
    try:
        with db.session() as session:
            user = create_user(session, args.email, password)
            print(f"pengguna dibuat: {user.email} ({user.id})")
    except AuthError as err:
        print(f"gagal: {err}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
