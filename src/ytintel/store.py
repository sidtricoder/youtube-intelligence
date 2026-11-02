"""Encrypted durable records and atomic quota operations on SQLite or PostgreSQL."""

import hashlib
import json
import os
import time
from contextlib import contextmanager
from pathlib import Path

from cryptography.fernet import Fernet
from sqlalchemy import (
    Column,
    Float,
    Integer,
    LargeBinary,
    MetaData,
    String,
    Table,
    create_engine,
    delete,
    select,
    text,
    update,
)
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.engine import make_url
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.schema import CreateSchema

from .errors import AppError


class Store:
    """One encrypted record contract; configured PostgreSQL failures never use local storage."""

    def __init__(self, path: str, key: str):
        self.path = path
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self._initialize("sqlite:///" + str(Path(path).absolute()), key, None)
        os.chmod(path, 0o600)

    @classmethod
    def from_url(cls, url: str, key: str, *, schema: str = "ytintel"):
        try:
            parsed = make_url(url)
            if parsed.drivername not in {"postgres", "postgresql", "postgresql+psycopg"}:
                raise ValueError("PostgreSQL URL required")
            parsed = parsed.set(drivername="postgresql+psycopg")
        except (ValueError, SQLAlchemyError):
            raise AppError(
                "invalid_database_configuration",
                "Provide a valid PostgreSQL DATABASE_URL; no local fallback is used",
                503,
            ) from None
        store = cls.__new__(cls)
        store.path = None
        store._initialize(parsed, key, schema)
        return store

    def _initialize(self, url, key, schema):
        self.cipher = Fernet(key.encode())
        self.schema = schema
        self.backend = "postgresql" if schema else "sqlite"
        self._insert = pg_insert if schema else sqlite_insert
        self.metadata = MetaData(schema=schema)
        self.records = Table(
            "kv",
            self.metadata,
            Column("k", String, primary_key=True),
            Column("v", LargeBinary, nullable=False),
            Column("expires", Float, nullable=False),
        )
        self.quotas = Table(
            "quota",
            self.metadata,
            Column("day", String, primary_key=True),
            Column("units", Integer, nullable=False),
            Column("searches", Integer, nullable=False),
        )
        options = {"pool_pre_ping": True, "hide_parameters": True}
        if schema:
            options.update(
                pool_size=3,
                max_overflow=2,
                pool_recycle=240,
                connect_args={"connect_timeout": 15, "prepare_threshold": None},
            )
        else:
            options["connect_args"] = {"timeout": 15, "check_same_thread": False}
        self.engine = create_engine(url, **options)
        self._lock = int.from_bytes(
            hashlib.blake2b((schema or "local").encode(), digest_size=8).digest(), "big"
        ) & ((1 << 63) - 1)
        try:
            with self.tx() as db:
                if schema:
                    db.execute(CreateSchema(schema, if_not_exists=True))
                self.metadata.create_all(db)
        except BaseException:
            self.engine.dispose()
            raise

    @contextmanager
    def tx(self):
        try:
            with self.engine.connect() as db:
                with db.begin():
                    if self.backend == "postgresql":
                        # Transaction-level lock works with Neon's transaction pooler.
                        db.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": self._lock})
                    else:
                        db.exec_driver_sql("BEGIN IMMEDIATE")
                    yield db
        except SQLAlchemyError:
            raise AppError(
                "database_unavailable",
                "Database operation failed; verify database credentials, TLS and connectivity. No local fallback is used.",
                503,
            ) from None

    def close(self):
        self.engine.dispose()

    def encode(self, value):
        return self.cipher.encrypt(json.dumps(value).encode())

    def decode(self, value):
        return json.loads(self.cipher.decrypt(bytes(value)))

    def put(self, key, value, ttl=86400):
        statement = self._insert(self.records).values(
            k=key, v=self.encode(value), expires=time.time() + ttl
        )
        statement = statement.on_conflict_do_update(
            index_elements=["k"],
            set_={"v": statement.excluded.v, "expires": statement.excluded.expires},
        )
        with self.tx() as db:
            db.execute(statement)

    def get(self, key):
        with self.tx() as db:
            row = db.execute(
                select(self.records.c.v, self.records.c.expires).where(self.records.c.k == key)
            ).first()
            if row and row.expires > time.time():
                return self.decode(row.v)
            db.execute(delete(self.records).where(self.records.c.k == key))

    def take(self, key):
        with self.tx() as db:
            row = db.execute(
                select(self.records.c.v, self.records.c.expires).where(self.records.c.k == key)
            ).first()
            db.execute(delete(self.records).where(self.records.c.k == key))
            if row and row.expires > time.time():
                return self.decode(row.v)

    def transition(self, key, expected, target):
        with self.tx() as db:
            row = db.execute(
                select(self.records.c.v, self.records.c.expires).where(self.records.c.k == key)
            ).first()
            if not row or row.expires <= time.time():
                return None
            data = self.decode(row.v)
            if data.get("status") != expected:
                return None
            data["status"] = target
            db.execute(
                update(self.records).where(self.records.c.k == key).values(v=self.encode(data))
            )
            return data

    def purge(self):
        with self.tx() as db:
            db.execute(delete(self.records).where(self.records.c.expires <= time.time()))

    def delete_prefix(self, prefix):
        with self.tx() as db:
            db.execute(
                delete(self.records).where(self.records.c.k.startswith(prefix, autoescape=True))
            )

    def reserve_quota(self, day, units, searches, unit_limit, search_limit):
        with self.tx() as db:
            db.execute(
                self._insert(self.quotas)
                .values(day=day, units=0, searches=0)
                .on_conflict_do_nothing(index_elements=["day"])
            )
            u, s = db.execute(
                select(self.quotas.c.units, self.quotas.c.searches).where(self.quotas.c.day == day)
            ).one()
            if u + units > unit_limit or s + searches > search_limit:
                raise AppError(
                    "quota_exceeded",
                    "Insufficient quota for the entire workflow; no API call made",
                    429,
                )
            db.execute(
                update(self.quotas)
                .where(self.quotas.c.day == day)
                .values(units=u + units, searches=s + searches)
            )

    def release_quota(self, day, units, searches):
        with self.tx() as db:
            db.execute(
                update(self.quotas)
                .where(self.quotas.c.day == day)
                .values(
                    units=self.quotas.c.units - units, searches=self.quotas.c.searches - searches
                )
            )

    def quota_usage(self, day):
        with self.tx() as db:
            row = db.execute(
                select(self.quotas.c.units, self.quotas.c.searches).where(self.quotas.c.day == day)
            ).first()
            return tuple(row) if row else (0, 0)
