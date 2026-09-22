"""SQLAlchemy engine/session wiring and migration (init) mechanism."""
from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, declarative_base, sessionmaker

Base = declarative_base()


class NovaSession(Session):
    """Session that commits on clean ``with``-block exit.

    Call sites across the codebase open sessions with ``with sf() as s:`` and
    expect writes to persist. The default Session only *closes* on exit, so we
    commit (or roll back on error) here to keep the service layer terse.
    """

    def __exit__(self, exc_type, exc, tb):
        try:
            if exc_type is None:
                self.commit()
            else:
                self.rollback()
        finally:
            super().__exit__(exc_type, exc, tb)


def make_engine(database_url: str) -> Engine:
    kwargs: dict = {"future": True}
    if database_url.startswith("sqlite"):
        kwargs["connect_args"] = {"check_same_thread": False}
    return create_engine(database_url, **kwargs)


def make_session_factory(engine: Engine) -> sessionmaker:
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False,
                        class_=NovaSession)


@event.listens_for(Engine, "connect")
def _sqlite_pragmas(dbapi_conn, _record):  # pragma: no cover - sqlite only
    try:
        cursor = dbapi_conn.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()
    except Exception:
        pass


class Database:
    """Thin wrapper owning engine + session factory + schema management."""

    def __init__(self, url: str | None = None) -> None:
        if url is None:
            from core.config import settings
            url = settings.get_str("database.url", "")
            if not url:
                url = f"sqlite:///{settings.database_path}"
        self.url = url
        self.engine = make_engine(url)
        self.session_factory = make_session_factory(self.engine)

    def set_url(self, url: str) -> None:
        self.url = url
        self.engine = make_engine(url)
        self.session_factory = make_session_factory(self.engine)

    def create_all(self) -> None:
        Base.metadata.create_all(self.engine)

    def drop_all(self) -> None:
        Base.metadata.drop_all(self.engine)

    def apply_migrations(self) -> list[str]:
        """Additive schema migrations (V2 §67): never destructive.

        ``create_all`` creates missing *tables* but cannot add *columns* to
        tables that already exist in a user's database.  This pass compares
        the live schema against the models and issues ``ADD COLUMN`` for
        anything missing — existing rows are untouched (new columns are
        nullable).  Returns the list of applied statements for diagnostics.
        """
        from sqlalchemy import inspect, text
        applied: list[str] = []
        insp = inspect(self.engine)
        existing_tables = set(insp.get_table_names())
        with self.engine.begin() as conn:
            for table_name, table in Base.metadata.tables.items():
                if table_name not in existing_tables:
                    continue  # create_all already handled new tables
                present = {c["name"] for c in insp.get_columns(table_name)}
                for col in table.columns:
                    if col.name in present:
                        continue
                    coltype = col.type.compile(self.engine.dialect)
                    stmt = f'ALTER TABLE "{table_name}" ADD COLUMN "{col.name}" {coltype}'
                    conn.execute(text(stmt))
                    applied.append(stmt)
        return applied

    @contextmanager
    def session(self) -> Iterator[Session]:
        s = self.session_factory()
        try:
            yield s
            s.commit()
        except Exception:
            s.rollback()
            raise
        finally:
            s.close()

    def migration_status(self) -> dict:
        """Report which tables exist vs the full schema (used by diagnostics)."""
        from sqlalchemy import inspect
        insp = inspect(self.engine)
        existing = set(insp.get_table_names())
        expected = set(Base.metadata.tables.keys())
        return {"current_version": 1, "tables_expected": sorted(expected),
                "tables_present": sorted(existing),
                "missing_tables": sorted(expected - existing),
                "up_to_date": expected <= existing}


# Convenience used by the settings service
def ensure_schema(database: Database) -> None:
    database.create_all()
