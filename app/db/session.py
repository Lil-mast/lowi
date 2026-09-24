"""Engine, sessions, and startup schema creation."""

from collections.abc import Iterator

from sqlalchemy import create_engine, inspect, select, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.config import Settings, normalize_database_url
from app.db.models import Base, User

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


def _ensure_agenda_column() -> None:
    """Add agenda on databases created before that column existed."""
    if engine is None or not inspect(engine).has_table("meetings"):
        return
    columns = {column["name"] for column in inspect(engine).get_columns("meetings")}
    if "agenda" in columns:
        return
    with engine.begin() as connection:
        connection.execute(text("ALTER TABLE meetings ADD COLUMN agenda TEXT"))


def seed_default_user(session: Session, settings: Settings) -> User:
    user = session.scalar(select(User).where(User.email == settings.default_user_email))
    if user is None:
        user = User(email=settings.default_user_email, name=settings.default_user_name)
        session.add(user)
        session.commit()
        session.refresh(user)
    return user


def init_db(settings: Settings) -> None:
    if engine is None:
        configure_engine(settings.database_url)
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    Base.metadata.create_all(engine)
    _ensure_agenda_column()
    with SessionLocal() as session:
        seed_default_user(session, settings)
