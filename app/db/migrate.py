"""Small SQL migration runner.

Migrations are plain `.sql` files under `app/db/migrations`. The runner records
each applied version in `schema_migrations` and refuses to run if a previously
applied file changed.
"""

from __future__ import annotations

import hashlib
import logging
from pathlib import Path

from sqlalchemy import inspect, text
from sqlalchemy.engine import Connection, Engine

logger = logging.getLogger(__name__)

MIGRATIONS_DIR = Path(__file__).parent / "migrations"
BASELINE_VERSION = "0001_baseline"


def _statements(sql: str) -> list[str]:
    """Split a migration file into statements, ignoring `--` comments."""
    without_comments = "\n".join(
        line for line in sql.splitlines() if not line.strip().startswith("--")
    )
    return [statement.strip() for statement in without_comments.split(";") if statement.strip()]


def _checksum(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _migration_files() -> list[Path]:
    return sorted(MIGRATIONS_DIR.glob("*.sql"))


def _ensure_table(connection: Connection) -> None:
    connection.exec_driver_sql(
        """
        CREATE TABLE IF NOT EXISTS schema_migrations (
            version VARCHAR(255) PRIMARY KEY,
            checksum VARCHAR(64) NOT NULL,
            applied_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """
    )


def _applied(connection: Connection) -> dict[str, str]:
    rows = connection.execute(text("SELECT version, checksum FROM schema_migrations")).all()
    return {row[0]: row[1] for row in rows}


def _legacy_schema(connection: Connection) -> bool:
    inspector = inspect(connection)
    return inspector.has_table("users") and inspector.has_table("meetings")


def _lock(connection: Connection) -> None:
    if connection.dialect.name == "postgresql":
        connection.exec_driver_sql("SELECT pg_advisory_xact_lock(hashtext('lowi_migrations'))")


def run_migrations(engine: Engine) -> list[str]:
    """Apply pending migrations and return the versions applied in this run."""
    applied_now: list[str] = []
    files = _migration_files()
    if not files:
        return applied_now

    with engine.begin() as connection:
        _lock(connection)
        _ensure_table(connection)
        applied = _applied(connection)

        if not applied and _legacy_schema(connection):
            baseline = MIGRATIONS_DIR / f"{BASELINE_VERSION}.sql"
            checksum = _checksum(baseline)
            connection.execute(
                text(
                    "INSERT INTO schema_migrations (version, checksum) "
                    "VALUES (:version, :checksum)"
                ),
                {"version": BASELINE_VERSION, "checksum": checksum},
            )
            applied[BASELINE_VERSION] = checksum
            logger.info("Baselined existing schema at %s", BASELINE_VERSION)

        for path in files:
            version = path.stem
            checksum = _checksum(path)
            if version in applied:
                if applied[version] != checksum:
                    raise RuntimeError(
                        f"Migration {version} changed after it was applied "
                        f"({applied[version][:12]} -> {checksum[:12]})"
                    )
                continue

            logger.info("Applying migration %s", version)
            for statement in _statements(path.read_text()):
                connection.exec_driver_sql(statement)
            connection.execute(
                text(
                    "INSERT INTO schema_migrations (version, checksum) "
                    "VALUES (:version, :checksum)"
                ),
                {"version": version, "checksum": checksum},
            )
            applied_now.append(version)

    return applied_now
