"""Configuración de base de datos y sesiones SQLAlchemy."""
from __future__ import annotations

import os
from pathlib import Path
from typing import Generator

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

from backend.models import Base

DEFAULT_DB_PATH = Path("data") / "guardias.db"
DEFAULT_DB_URL = f"sqlite:///{DEFAULT_DB_PATH.as_posix()}"


def get_database_url() -> str:
    return os.getenv("DATABASE_URL", DEFAULT_DB_URL)


def create_db_engine(url: str | None = None) -> Engine:
    database_url = url or get_database_url()
    connect_args = {}
    if database_url.startswith("sqlite"):
        connect_args["check_same_thread"] = False
        # Si es un path de fichero sqlite, nos aseguramos de que el directorio exista
        if "///" in database_url and not database_url.startswith("sqlite:///:memory:"):
            db_path_str = database_url.split("///", 1)[1]
            if db_path_str:
                db_path = Path(db_path_str)
                db_path.parent.mkdir(parents=True, exist_ok=True)

    return create_engine(database_url, connect_args=connect_args)


engine = create_db_engine()
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def init_db(target_engine: Engine | None = None) -> None:
    """Crea todas las tablas definidas en los modelos si no existen y actualiza columnas nuevas."""
    eng = target_engine or engine
    Base.metadata.create_all(bind=eng)

    # Migración liviana: añadir columna zones si no existe
    from sqlalchemy import inspect, text
    inspector = inspect(eng)
    if "pharmacies" in inspector.get_table_names():
        cols = [c["name"] for c in inspector.get_columns("pharmacies")]
        if "zones" not in cols:
            with eng.begin() as conn:
                conn.execute(text("ALTER TABLE pharmacies ADD COLUMN zones TEXT"))


def get_db() -> Generator[Session, None, None]:
    """Generador de sesión SQLAlchemy para FastAPI Depends."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
