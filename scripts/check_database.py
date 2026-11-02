"""Opt-in PostgreSQL persistence probe in a disposable schema; never touches account records."""

import argparse
import json
import uuid
from pathlib import Path

from sqlalchemy.schema import DropSchema

from ytintel.config import Settings
from ytintel.errors import AppError
from ytintel.quota import Quota
from ytintel.store import Store


def check(output: Path):
    settings = Settings()
    if not settings.database_connection:
        raise AppError(
            "database_not_configured",
            "Set DATABASE_URL or DATABASE_URL_POOLED before running this PostgreSQL check",
            400,
        )
    schema = "ytintel_probe_" + uuid.uuid4().hex
    store = None
    report = {"database": "postgresql", "status": "FAIL", "account_records_touched": False}
    try:
        store = Store.from_url(settings.database_connection, settings.encryption_key, schema=schema)
        store.put("probe", {"marker": "synthetic-persistence-check"})
        store.close()
        reopened = Store.from_url(
            settings.database_connection, settings.encryption_key, schema=schema
        )
        try:
            assert reopened.get("probe") == {"marker": "synthetic-persistence-check"}
            q = Quota(reopened, units=2, searches=0)
            with q.reserve(2, 0) as ticket:
                ticket.consume(1, 0)
            assert q.status()["units_used"] == 1
            report.update(status="PASS", encrypted_persistence=True, quota_transaction=True)
        finally:
            reopened.close()
    except AppError as exc:
        report.update(code=exc.code, message=exc.message)
    finally:
        if store is not None:
            try:
                with store.tx() as db:
                    db.execute(DropSchema(schema, cascade=True))
                report["test_schema_removed"] = True
            finally:
                store.close()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))
    return report["status"] == "PASS"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("docs/DATABASE_CHECKS.json"))
    args = parser.parse_args()
    try:
        passed = check(args.output)
    except AppError as exc:
        print(json.dumps({"status": "FAIL", "code": exc.code, "message": exc.message}))
        raise SystemExit(1) from None
    raise SystemExit(0 if passed else 1)


if __name__ == "__main__":
    main()
