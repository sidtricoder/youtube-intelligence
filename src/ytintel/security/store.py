"""Relational security records; bearer secrets are persisted only as SHA-256 digests."""

import hashlib
import secrets
import time
from typing import Protocol

from sqlalchemy import Column, Float, Integer, LargeBinary, String, Table, delete, select, update

from ..errors import AppError


def digest(secret):
    return hashlib.sha256(secret.encode()).hexdigest()


class Clock(Protocol):
    def now(self) -> float: ...


class SystemClock:
    def now(self):
        return time.time()


class SecurityStore:
    def __init__(self, raw, clock=None):
        self.raw = raw
        self.clock = clock or SystemClock()
        self.users = Table(
            "users",
            raw.metadata,
            Column("user_id", String, primary_key=True),
            Column("google_sub", String, unique=True, nullable=False),
            Column("generation", Integer, nullable=False, server_default="0"),
            extend_existing=True,
        )
        self.user_google_tokens = Table(
            "user_google_tokens",
            raw.metadata,
            Column("user_id", String, primary_key=True),
            Column("payload", LargeBinary, nullable=False),
            extend_existing=True,
        )
        self.oauth_clients = self._records("oauth_clients", "client_id")
        self.auth_codes = self._records("auth_codes")
        self.access_tokens = self._records("access_tokens")
        self.refresh_tokens = self._records("refresh_tokens")
        self.web_sessions = self._records("web_sessions")
        self.login_transactions = self._records("login_transactions")
        self.token_families = self._records("token_families", "family")
        with raw.tx() as db:
            raw.metadata.create_all(db)

    def _records(self, name, key="digest"):
        return Table(
            name,
            self.raw.metadata,
            Column(key, String, primary_key=True),
            Column("user_id", String),
            Column("payload", LargeBinary, nullable=False),
            Column("expires", Float, nullable=False),
            extend_existing=True,
        )

    def _put(self, table, key, value, ttl, db=None, user_id=None):
        col = list(table.primary_key.columns)[0].name
        stmt = self.raw._insert(table).values(
            **{
                col: key,
                "payload": self.raw.encode(value),
                "expires": self.clock.now() + ttl,
                "user_id": user_id,
            }
        )
        stmt = stmt.on_conflict_do_update(
            index_elements=[col],
            set_={
                "payload": stmt.excluded.payload,
                "expires": stmt.excluded.expires,
                "user_id": stmt.excluded.user_id,
            },
        )
        if db is not None:
            db.execute(stmt)
        else:
            with self.raw.tx() as conn:
                conn.execute(stmt)

    def _get(self, table, key, db=None, consume=False):
        if db is None:
            with self.raw.tx() as conn:
                return self._get(table, key, conn, consume)
        col = list(table.primary_key.columns)[0]
        row = db.execute(select(table).where(col == key)).mappings().first()
        if consume:
            db.execute(delete(table).where(col == key))
        if row and row["expires"] > self.clock.now():
            return self.raw.decode(row["payload"])
        return None

    def upsert_user(self, sub):
        with self.raw.tx() as db:
            row = db.execute(
                select(self.users.c.user_id).where(self.users.c.google_sub == sub)
            ).first()
            if row:
                return row.user_id
            user_id = secrets.token_urlsafe(24)
            db.execute(self.users.insert().values(user_id=user_id, google_sub=sub))
            return user_id

    def save_google(self, user_id, tokens, expected_generation: int | None = None) -> bool:
        stmt = self.raw._insert(self.user_google_tokens).values(
            user_id=user_id, payload=self.raw.encode(tokens)
        )
        stmt = stmt.on_conflict_do_update(
            index_elements=["user_id"], set_={"payload": stmt.excluded.payload}
        )
        with self.raw.tx() as db:
            where = self.users.c.user_id == user_id
            if expected_generation is not None:
                where &= self.users.c.generation == expected_generation
            changed = db.execute(
                update(self.users).where(where).values(generation=self.users.c.generation + 1)
            )
            if not changed.rowcount:
                return False
            db.execute(stmt)
            return True

    def generation(self, user_id):
        with self.raw.tx() as db:
            return db.execute(
                select(self.users.c.generation).where(self.users.c.user_id == user_id)
            ).scalar_one_or_none()

    def save_google_if_current(self, user_id, previous, tokens, expected_generation=None):
        """Commit a refresh only while its original authorization still exists."""
        with self.raw.tx() as db:
            generation = db.execute(
                select(self.users.c.generation).where(self.users.c.user_id == user_id)
            ).scalar_one_or_none()
            if generation is None or (
                expected_generation is not None and generation != expected_generation
            ):
                return False
            payload = db.execute(
                select(self.user_google_tokens.c.payload).where(
                    self.user_google_tokens.c.user_id == user_id
                )
            ).scalar_one_or_none()
            if payload is None or self.raw.decode(payload) != previous:
                return False
            db.execute(
                update(self.user_google_tokens)
                .where(self.user_google_tokens.c.user_id == user_id)
                .values(payload=self.raw.encode(tokens))
            )
            return True

    def google(self, user_id):
        with self.raw.tx() as db:
            row = db.execute(
                select(self.user_google_tokens.c.payload).where(
                    self.user_google_tokens.c.user_id == user_id
                )
            ).first()
            return self.raw.decode(row.payload) if row else None

    def current_grant_generation(self, user_id):
        with self.raw.tx() as db:
            return db.execute(
                select(self.users.c.generation)
                .select_from(
                    self.users.join(
                        self.user_google_tokens,
                        self.users.c.user_id == self.user_google_tokens.c.user_id,
                    )
                )
                .where(self.users.c.user_id == user_id)
            ).scalar_one_or_none()

    def create_session(self, user_id, expected_generation=None):
        opaque, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
        with self.raw.tx() as db:
            generation = db.execute(
                select(self.users.c.generation).where(self.users.c.user_id == user_id)
            ).scalar_one_or_none()
            if generation is None or (
                expected_generation is not None and generation != expected_generation
            ):
                raise AppError(
                    "reauthorization_required", "Authorization changed; sign in again", 401
                )
            self._put(
                self.web_sessions,
                digest(opaque),
                {"user_id": user_id, "csrf": csrf, "generation": generation},
                43200,
                db=db,
                user_id=user_id,
            )
        return opaque, csrf

    def session(self, opaque):
        if not opaque:
            return None
        with self.raw.tx() as db:
            value = self._get(self.web_sessions, digest(opaque), db=db)
            if not value:
                return None
            generation = db.execute(
                select(self.users.c.generation).where(self.users.c.user_id == value["user_id"])
            ).scalar_one_or_none()
            if generation is None or generation != value.get("generation"):
                return None
            return {"user_id": value["user_id"], "csrf": value["csrf"], "generation": generation}

    def delete_session(self, opaque):
        self._get(self.web_sessions, digest(opaque), consume=True)

    def create_login(self, value, ttl=600):
        opaque = secrets.token_urlsafe(32)
        self._put(self.login_transactions, digest(opaque), value, ttl)
        return opaque

    def get_login(self, opaque):
        return self._get(self.login_transactions, digest(opaque))

    def take_login(self, opaque):
        return self._get(self.login_transactions, digest(opaque), consume=True)

    def update_login(self, opaque, value, ttl=600):
        self._put(self.login_transactions, digest(opaque), value, ttl)

    def revoke_user(self, user_id, expected_generation=None):
        with self.raw.tx() as db:
            where = self.users.c.user_id == user_id
            if expected_generation is not None:
                where &= self.users.c.generation == expected_generation
            changed = db.execute(
                update(self.users).where(where).values(generation=self.users.c.generation + 1)
            )
            if not changed.rowcount:
                return False
            for table in (
                self.user_google_tokens,
                self.web_sessions,
                self.access_tokens,
                self.refresh_tokens,
                self.auth_codes,
                self.token_families,
            ):
                db.execute(delete(table).where(table.c.user_id == user_id))
            return True

    delete_user = revoke_user
