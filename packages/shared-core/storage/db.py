"""Conexão SQLite única do monorepo (data/noemi.db).

ponytail: SQLite local, não o Postgres de produção — zero risco pros DBs da
Noemi. Migrar = trocar conn() por psycopg quando 2+ produtos precisarem.
"""
from __future__ import annotations

import os
import sqlite3
from pathlib import Path

_RAIZ = Path(__file__).resolve().parents[3]  # raiz do monorepo


def data_dir() -> Path:
    d = Path(os.environ.get("NOEMI_DATA_DIR", str(_RAIZ / "data")))
    d.mkdir(parents=True, exist_ok=True)
    return d


def conn() -> sqlite3.Connection:
    c = sqlite3.connect(data_dir() / "noemi.db", timeout=10)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA journal_mode=WAL")
    c.execute("PRAGMA foreign_keys=ON")
    _migrar(c)
    return c


def _migrar(c: sqlite3.Connection) -> None:
    c.executescript(
        """
        CREATE TABLE IF NOT EXISTS assets (
          id       TEXT PRIMARY KEY,
          owner    TEXT NOT NULL,
          produto  TEXT NOT NULL,
          bucket   TEXT NOT NULL,
          mime     TEXT NOT NULL,
          hash     TEXT NOT NULL,
          metadata TEXT NOT NULL DEFAULT '{}',
          criado_em TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS jobs (
          id            TEXT PRIMARY KEY,
          produto       TEXT NOT NULL,
          estado        TEXT NOT NULL,
          asset_origem  TEXT NOT NULL REFERENCES assets(id),
          asset_video   TEXT REFERENCES assets(id),
          config        TEXT NOT NULL DEFAULT '{}',
          tentativas    INTEGER NOT NULL DEFAULT 0,
          erro          TEXT,
          criado_em     TEXT NOT NULL,
          atualizado_em TEXT NOT NULL
        );
        """
    )
