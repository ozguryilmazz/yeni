from collections.abc import Generator
from contextlib import contextmanager

from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from app.config import get_database_path

engine = create_engine(
    f"sqlite:///{get_database_path()}",
    connect_args={"check_same_thread": False},
)


@event.listens_for(engine, "connect")
def _enable_foreign_keys(dbapi_connection, connection_record) -> None:  # noqa: ANN001
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    pass


def init_db() -> None:
    from app import models  # noqa: F401  Base.metadata'nın modelleri görmesi için gerekli

    Base.metadata.create_all(bind=engine)


@contextmanager
def session_scope() -> Generator:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
