"""Engine, sessions, migrations, and startup seed data."""

from __future__ import annotations

from collections.abc import Iterator

from sqlalchemy import create_engine, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.config import Settings, normalize_database_url
from app.db.migrate import run_migrations
from app.db.models import User

SessionLocal = sessionmaker(autoflush=False, autocommit=False, expire_on_commit=False)
engine: Engine | None = None


def make_engine(url: str) -> Engine:
    normalized = normalize_database_url(url)
    kwargs: dict = {}
    if normalized.startswith("sqlite"):
        kwargs["connect_args"] = {"check_same_thread": False}
        if normalized in {"sqlite://", "sqlite:///:memory:"}:
            kwargs["poolclass"] = StaticPool
    return create_engine(normalized, **kwargs)


def configure_engine(url: str) -> Engine:
    global engine
    engine = make_engine(url)
    SessionLocal.configure(bind=engine)
    return engine


def get_db() -> Iterator[Session]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def seed_user(db: Session, email: str, name: str) -> User:
    """Return the user for `email`, creating it if needed."""
    user = db.scalar(select(User).where(User.email == email))
    if user is None:
        user = User(email=email, name=name)
        db.add(user)
        db.commit()
        db.refresh(user)
    elif user.name != name:
        user.name = name
        db.commit()
        db.refresh(user)
    return user


def init_db(settings: Settings) -> None:
    if engine is None:
        configure_engine(settings.database_url)
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    run_migrations(engine)
    if settings.auth_mode in {"dev", "test"}:
        with SessionLocal() as session:
            if settings.auth_mode == "test":
                seed_user(session, settings.test_user_email, settings.test_user_name)
            else:
                seed_user(session, settings.default_user_email, settings.default_user_name)
