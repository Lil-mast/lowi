from __future__ import annotations

import pytest
from app.db.migrate import MIGRATIONS_DIR, run_migrations
from app.db.session import make_engine
from sqlalchemy import inspect, text


def _baseline_statements() -> list[str]:
    sql = (MIGRATIONS_DIR / "0001_baseline.sql").read_text()
    without_comments = "\n".join(
        line for line in sql.splitlines() if not line.strip().startswith("--")
    )
    return [part.strip() for part in without_comments.split(";") if part.strip()]


def test_fresh_database_migrates_and_is_idempotent(tmp_path):
    engine = make_engine(f"sqlite:///{tmp_path / 'fresh.db'}")

    applied = run_migrations(engine)
    assert applied == [
        "0001_baseline",
        "0002_auth",
        "0003_storage",
        "0004_pipeline",
        "0005_live",
    ]

    tables = set(inspect(engine).get_table_names())
    assert {"users", "meetings", "sessions", "schema_migrations", "live_sessions", "live_segments"} <= tables

    columns = {column["name"] for column in inspect(engine).get_columns("users")}
    assert {"neon_auth_user_id", "last_login_at"} <= columns

    assert run_migrations(engine) == []


def test_existing_schema_is_baselined_without_recreating_tables(tmp_path):
    engine = make_engine(f"sqlite:///{tmp_path / 'legacy.db'}")
    with engine.begin() as connection:
        for statement in _baseline_statements():
            connection.exec_driver_sql(statement)
        connection.execute(
            text(
                "INSERT INTO users (id, email, name) "
                "VALUES ('legacy-user', 'local@lowi.local', 'Local')"
            )
        )

    applied = run_migrations(engine)
    assert applied == [
        "0002_auth",
        "0003_storage",
        "0004_pipeline",
        "0005_live",
    ]

    tables = set(inspect(engine).get_table_names())
    assert "sessions" in tables
    columns = {column["name"] for column in inspect(engine).get_columns("users")}
    assert {"neon_auth_user_id", "last_login_at"} <= columns

    with engine.connect() as connection:
        email = connection.execute(text("SELECT email FROM users")).scalar_one()
    assert email == "local@lowi.local"


def test_changed_migration_is_rejected(tmp_path):
    engine = make_engine(f"sqlite:///{tmp_path / 'checksum.db'}")
    run_migrations(engine)

    with engine.begin() as connection:
        connection.execute(
            text("UPDATE schema_migrations SET checksum = 'wrong' WHERE version = '0002_auth'")
        )

    with pytest.raises(RuntimeError, match="changed after it was applied"):
        run_migrations(engine)
