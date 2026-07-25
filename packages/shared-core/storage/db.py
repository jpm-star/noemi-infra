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
        -- Log de interação REAL (não-mock): fundação honesta pra decidir tuning
        -- no futuro (quando houver volume). NÃO é tuning — só guarda o histórico
        -- pra não precisar reconstruir depois. Fica vazio enquanto tudo é mock.
        CREATE TABLE IF NOT EXISTS interacoes (
          id        INTEGER PRIMARY KEY AUTOINCREMENT,
          ts        TEXT NOT NULL,
          produto   TEXT NOT NULL,   -- 'motor-b-video' | 'assistente-virtual'
          cliente   TEXT,            -- owner/tenant
          segmento  TEXT,            -- vertical, quando aplicável
          input     TEXT,            -- entrada recebida (JSON)
          output    TEXT,            -- saída gerada (JSON)
          modelo    TEXT,            -- provider/modelo real usado
          handoff_whatsapp INTEGER   -- 1/0/NULL (só faz sentido no Assistente)
        );
        -- Histórico do Site Studio (motor-isca): cada site publicado pelo JP.
        CREATE TABLE IF NOT EXISTS sites_gerados (
          id        INTEGER PRIMARY KEY AUTOINCREMENT,
          cliente   TEXT NOT NULL,
          segmento  TEXT,
          slug      TEXT NOT NULL,
          url       TEXT NOT NULL,
          criado_em TEXT NOT NULL
        );
        -- Radar de Vídeo: cada análise (transcrição + insight) fica salva pra
        -- virar CONTEXTO das próximas (memória persistente, não fine-tuning).
        CREATE TABLE IF NOT EXISTS video_analises (
          id          INTEGER PRIMARY KEY AUTOINCREMENT,
          origem      TEXT,            -- conta/concorrente/tema (agrupa o radar)
          url         TEXT NOT NULL,
          data        TEXT NOT NULL,
          transcricao TEXT,
          insight     TEXT,            -- resumo/insight gerado (texto)
          categoria   TEXT,
          score       INTEGER,
          tags        TEXT,            -- palavras-chave p/ busca e matching de contexto
          detalhe     TEXT             -- JSON: onde_usar/verticais/axioma/assimilacao/comparacao
        );
        """
    )
    # colunas do dashboard v1.1 (ALTER idempotente — CREATE não adiciona a tabela já existente)
    for col, tipo in (("aprovado", "INTEGER"), ("duracao_s", "REAL"), ("custo_creditos", "REAL")):
        _add_column(c, "jobs", col, tipo)
    _add_column(c, "video_analises", "detalhe", "TEXT")  # insight rico (tabela já existe em prod)


def _add_column(c: sqlite3.Connection, tabela: str, col: str, tipo: str) -> None:
    existentes = {r[1] for r in c.execute(f"PRAGMA table_info({tabela})")}
    if col not in existentes:
        c.execute(f"ALTER TABLE {tabela} ADD COLUMN {col} {tipo}")
