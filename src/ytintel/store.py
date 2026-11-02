"""Encrypted JSON values with transactional transitions and expiring records."""

import json
import os
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path

from cryptography.fernet import Fernet


class Store:
    def __init__(self, path: str, key: str):
        self.path, self.cipher = path, Fernet(key.encode())
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        with self.tx() as db:
            db.execute("CREATE TABLE IF NOT EXISTS kv (k TEXT PRIMARY KEY,v BLOB,expires REAL)")
            db.execute(
                "CREATE TABLE IF NOT EXISTS quota (day TEXT PRIMARY KEY,units INTEGER,searches INTEGER)"
            )
        os.chmod(path, 0o600)

    @contextmanager
    def tx(self):
        db = sqlite3.connect(self.path, timeout=15)
        try:
            db.execute("BEGIN IMMEDIATE")
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    def encode(self, value):
        return self.cipher.encrypt(json.dumps(value).encode())

    def decode(self, value):
        return json.loads(self.cipher.decrypt(value))

    def put(self, key, value, ttl=86400):
        with self.tx() as db:
            db.execute(
                "INSERT OR REPLACE INTO kv VALUES (?,?,?)",
                (key, self.encode(value), time.time() + ttl),
            )

    def get(self, key):
        with self.tx() as db:
            row = db.execute("SELECT v,expires FROM kv WHERE k=?", (key,)).fetchone()
            if row and row[1] > time.time():
                return self.decode(row[0])
            db.execute("DELETE FROM kv WHERE k=?", (key,))

    def take(self, key):
        with self.tx() as db:
            row = db.execute("SELECT v,expires FROM kv WHERE k=?", (key,)).fetchone()
            db.execute("DELETE FROM kv WHERE k=?", (key,))
            if row and row[1] > time.time():
                return self.decode(row[0])

    def transition(self, key, expected, target):
        with self.tx() as db:
            row = db.execute("SELECT v,expires FROM kv WHERE k=?", (key,)).fetchone()
            if not row or row[1] <= time.time():
                return None
            data = self.decode(row[0])
            if data.get("status") != expected:
                return None
            data["status"] = target
            db.execute("UPDATE kv SET v=? WHERE k=?", (self.encode(data), key))
            return data

    def purge(self):
        with self.tx() as db:
            db.execute("DELETE FROM kv WHERE expires<=?", (time.time(),))

    def delete_prefix(self, prefix):
        with self.tx() as db:
            db.execute("DELETE FROM kv WHERE k LIKE ?", (prefix + "%",))
