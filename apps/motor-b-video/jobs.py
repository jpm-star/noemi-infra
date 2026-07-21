"""Fila de jobs do Motor B — SQLite, transições atômicas.

Estados: queued → uploading → processing → completed | failed | cancelled
                         ↘ retry (volta pra fila, até MAX_TENTATIVAS)

ponytail: helpers de job moram no app (não em shared-core) até um 2º produto
usar fila de verdade — critério de Core do CLAUDE.md.
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone

from shared_core.storage.db import conn

ESTADOS = {"queued", "uploading", "processing", "retry", "completed", "failed", "cancelled"}
ESTADOS_TERMINAIS = {"completed", "failed", "cancelled"}
MAX_TENTATIVAS = 3
PRODUTO = "motor-b-video"


def _agora() -> str:
    return datetime.now(timezone.utc).isoformat()


def criar(asset_origem: str, config: dict | None = None) -> dict:
    job = {
        "id": uuid.uuid4().hex,
        "produto": PRODUTO,
        "estado": "queued",
        "asset_origem": asset_origem,
        "asset_video": None,
        "config": config or {},
        "tentativas": 0,
        "erro": None,
        "criado_em": _agora(),
        "atualizado_em": _agora(),
    }
    with conn() as c:
        c.execute(
            "INSERT INTO jobs (id, produto, estado, asset_origem, asset_video, config, tentativas, erro, criado_em, atualizado_em) "
            "VALUES (:id, :produto, :estado, :asset_origem, :asset_video, :config_json, :tentativas, :erro, :criado_em, :atualizado_em)",
            {**job, "config_json": json.dumps(job["config"], ensure_ascii=False)},
        )
    return job


def obter(job_id: str) -> dict | None:
    with conn() as c:
        row = c.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
    return _hidratar(row)


def listar(limite: int = 50) -> list[dict]:
    with conn() as c:
        rows = c.execute("SELECT * FROM jobs ORDER BY criado_em DESC LIMIT ?", (limite,)).fetchall()
    return [_hidratar(r) for r in rows]


def proximo_na_fila() -> dict | None:
    with conn() as c:
        row = c.execute(
            "SELECT * FROM jobs WHERE estado IN ('queued','retry') ORDER BY criado_em LIMIT 1"
        ).fetchone()
    return _hidratar(row)


def atualizar(job_id: str, estado: str, **campos) -> bool:
    """Transição atômica. Estado terminal nunca é sobrescrito — se o job foi
    cancelado no meio do processamento, o UPDATE não pega e retorna False."""
    assert estado in ESTADOS, f"estado inválido: {estado}"
    sets = ", ".join(f"{k}=:{k}" for k in campos)
    with conn() as c:
        cur = c.execute(
            f"UPDATE jobs SET estado=:estado, atualizado_em=:agora{', ' + sets if sets else ''} "
            "WHERE id=:id AND estado NOT IN ('completed','failed','cancelled')",
            {"estado": estado, "agora": _agora(), "id": job_id, **campos},
        )
    return cur.rowcount > 0


def _hidratar(row) -> dict | None:
    if not row:
        return None
    job = dict(row)
    job["config"] = json.loads(job["config"])
    return job
