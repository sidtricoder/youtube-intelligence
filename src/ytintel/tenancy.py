"""Relational tenant isolation; encrypted payloads never use unscoped keys."""

import time

from sqlalchemy import Column, Float, LargeBinary, String, Table, delete, select, update

from .errors import AppError


def tables(raw):
    # Reuse the same metadata objects when constructing multiple request stores.
    for name in ("drafts", "tenant_cache", "public_cache"):
        if name not in {table.name for table in raw.metadata.tables.values()}:
            columns = (
                [] if name == "public_cache" else [Column("user_id", String, primary_key=True)]
            )
            Table(
                name,
                raw.metadata,
                *columns,
                Column("k", String, primary_key=True),
                Column("v", LargeBinary, nullable=False),
                Column("expires", Float, nullable=False),
            )
    with raw.tx() as db:
        raw.metadata.create_all(db)
    return {table.name: table for table in raw.metadata.tables.values()}


class ScopedStore:
    def __init__(self, raw, user_id, *, generation: int | None = None):
        if not user_id:
            raise ValueError("user_id required")
        self.raw, self.user_id, self.path = raw, user_id, raw.path
        self.tables = tables(raw)
        self._users = self.tables.get("users")
        with raw.tx() as db:
            self._generation = (
                generation if generation is not None else self._current_generation(db)
            )

    def _current_generation(self, db):
        if self._users is None:
            return None
        return db.execute(
            select(self._users.c.generation).where(self._users.c.user_id == self.user_id)
        ).scalar_one_or_none()

    def _guard(self, db):
        if self._generation is not None and self._current_generation(db) != self._generation:
            raise AppError(
                "reauthorization_required", "Account authorization changed; sign in again", 401
            )

    def _table(self, key):
        if key.startswith("draft:"):
            return self.tables["drafts"]
        return self.tables["tenant_cache"]

    def _where(self, table, key):
        return (table.c.k == key) & (table.c.user_id == self.user_id)

    def put(self, key, value, ttl=86400):
        table = self._table(key)
        values = dict(k=key, v=self.raw.encode(value), expires=time.time() + ttl)
        if "user_id" in table.c:
            values["user_id"] = self.user_id
        statement = self.raw._insert(table).values(**values)
        statement = statement.on_conflict_do_update(
            index_elements=list(table.primary_key.columns),
            set_={"v": statement.excluded.v, "expires": statement.excluded.expires},
        )
        with self.raw.tx() as db:
            self._guard(db)
            db.execute(statement)

    def _read(self, key, take=False):
        table = self._table(key)
        where = self._where(table, key)
        with self.raw.tx() as db:
            self._guard(db)
            row = db.execute(select(table.c.v, table.c.expires).where(where)).first()
            if take or (row and row.expires <= time.time()):
                db.execute(delete(table).where(where))
            if row and row.expires > time.time():
                return self.raw.decode(row.v)

    def get(self, key):
        return self._read(key)

    def take(self, key):
        return self._read(key, True)

    def transition(self, key, expected, target):
        table = self._table(key)
        where = self._where(table, key)
        with self.raw.tx() as db:
            self._guard(db)
            row = db.execute(select(table.c.v, table.c.expires).where(where)).first()
            if not row or row.expires <= time.time():
                return None
            value = self.raw.decode(row.v)
            if value.get("status") != expected:
                return None
            value["status"] = target
            db.execute(update(table).where(where).values(v=self.raw.encode(value)))
            return value

    def delete_prefix(self, prefix):
        with self.raw.tx() as db:
            self._guard(db)
            for name in ("drafts", "tenant_cache"):
                table = self.tables[name]
                db.execute(
                    delete(table).where(
                        (table.c.user_id == self.user_id)
                        & table.c.k.startswith(prefix, autoescape=True)
                    )
                )


class PublicStore(ScopedStore):
    """Shared API-key-only metadata cache, with no account persistence surface."""

    def __init__(self, raw):
        self.raw, self.path = raw, raw.path
        self.tables = tables(raw)

    def _guard(self, db):
        pass

    def _table(self, key):
        if not key.startswith("cache:"):
            raise AppError("authentication_required", "Sign in to persist account data", 401)
        return self.tables["public_cache"]

    def _where(self, table, key):
        return table.c.k == key

    def transition(self, key, expected, target):
        raise AppError("authentication_required", "Sign in to update account data", 401)

    def delete_prefix(self, prefix):
        self._table(prefix)
        table = self.tables["public_cache"]
        with self.raw.tx() as db:
            db.execute(delete(table).where(table.c.k.startswith(prefix, autoescape=True)))
