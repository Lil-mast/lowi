"""Engine, sessions, and startup schema creation."""

from collections.abc import Iterator

from sqlalchemy import create_engine, select
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
    with SessionLocal() as session:
        seed_default_user(session, settings)
