"""Database engine, session helpers, and settings accessors."""
from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator

from sqlmodel import Session, SQLModel, create_engine, select

from . import config
from .models import Setting

config.DATA_DIR.mkdir(parents=True, exist_ok=True)
config.THUMBS_DIR.mkdir(parents=True, exist_ok=True)

# check_same_thread=False so the background worker thread can share the engine.
engine = create_engine(
    f"sqlite:///{config.DB_PATH}",
    connect_args={"check_same_thread": False},
)


def init_db() -> None:
    SQLModel.metadata.create_all(engine)
    _migrate_schema()
    # Seed any missing settings from env-derived defaults.
    with Session(engine) as session:
        rows = session.exec(select(Setting)).all()
        existing = {s.key for s in rows}
        # Migrate a legacy single "input_dir" setting to "input_dirs".
        if "input_dirs" not in existing and "input_dir" in existing:
            legacy = next(s.value for s in rows if s.key == "input_dir")
            session.add(Setting(key="input_dirs", value=legacy))
            existing.add("input_dirs")
        for key, value in config.DEFAULTS.items():
            if key not in existing:
                session.add(Setting(key=key, value=value))
        session.commit()


def _migrate_schema() -> None:
    """Add columns introduced after a DB was first created (SQLite ALTER)."""
    with engine.connect() as conn:
        cols = {row[1] for row in conn.exec_driver_sql("PRAGMA table_info(video)").fetchall()}
        if "original_path" not in cols:
            conn.exec_driver_sql("ALTER TABLE video ADD COLUMN original_path VARCHAR")
            conn.commit()


@contextmanager
def get_session() -> Iterator[Session]:
    session = Session(engine)
    try:
        yield session
    finally:
        session.close()


def get_all_settings() -> dict[str, str]:
    with Session(engine) as session:
        return {s.key: s.value for s in session.exec(select(Setting)).all()}


def set_settings(values: dict[str, str]) -> None:
    with Session(engine) as session:
        for key, value in values.items():
            row = session.get(Setting, key)
            if row is None:
                session.add(Setting(key=key, value=value))
            else:
                row.value = value
                session.add(row)
        session.commit()
