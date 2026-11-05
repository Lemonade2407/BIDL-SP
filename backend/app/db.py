from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import Column, DateTime, String, create_engine, event
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from .config import settings


def now():
    return datetime.now(timezone.utc)


def uid():
    return str(uuid4())


class Base(DeclarativeBase):
    pass


class Entity:
    id = Column(String(36), primary_key=True, default=uid)
    created_at = Column(DateTime(timezone=True), default=now, nullable=False, index=True)
    updated_at = Column(DateTime(timezone=True), default=now, onupdate=now, nullable=False)


engine = create_engine(
    settings.database_url,
    pool_pre_ping=True,
    connect_args={"check_same_thread": False, "timeout": 30}
    if settings.database_url.startswith("sqlite")
    else {},
)
if engine.dialect.name == "sqlite":

    @event.listens_for(engine, "connect")
    def sqlite_constraints(connection, _):
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA journal_mode=WAL")


SessionLocal = sessionmaker(engine, expire_on_commit=False)


def get_db():
    with SessionLocal() as session:
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
