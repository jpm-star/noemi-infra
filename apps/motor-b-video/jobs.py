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


def proximo_na_fila() -> dict | None:
    with conn() as c:
        row = c.execute(
            "SELECT * FROM jobs WHERE estado IN ('queued','retry') ORDER BY criado_em LIMIT 1"
        ).fetchone()
    return _hidratar(row)


def requeue_orfaos() -> int:
    """Recuperação de startup: job que ficou em uploading/processing quando o
    processo morreu voltaria pra fila nunca — requeued como retry aqui."""
    with conn() as c:
        cur = c.execute(
            "UPDATE jobs SET estado='retry', atualizado_em=? WHERE estado IN ('uploading','processing')",
            (_agora(),),
        )
    return cur.rowcount


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


def marcar_aprovado(job_id: str, aprovado: bool) -> bool:
    """Marca aprovação do vídeo (aceito de primeira). Só job completed; NÃO mexe
    no estado — por isso não passa por atualizar() (que guarda terminais)."""
    with conn() as c:
        cur = c.execute(
            "UPDATE jobs SET aprovado=?, atualizado_em=? WHERE id=? AND estado='completed'",
            (1 if aprovado else 0, _agora(), job_id),
        )
    return cur.rowcount > 0


def metricas() -> dict:
    """4 indicadores do dashboard v1.1 (só motor-b)."""
    with conn() as c:
        r = c.execute(
            """SELECT
                 SUM(CASE WHEN estado='completed' THEN 1 ELSE 0 END) AS produzidos,
                 AVG(CASE WHEN estado='completed' THEN duracao_s END) AS tempo,
                 AVG(CASE WHEN estado='completed' THEN custo_creditos END) AS custo,
                 SUM(CASE WHEN aprovado=1 THEN 1 ELSE 0 END) AS aprovados,
                 SUM(CASE WHEN aprovado IS NOT NULL THEN 1 ELSE 0 END) AS avaliados
               FROM jobs WHERE produto=?""",
            (PRODUTO,),
        ).fetchone()
    avaliados = r["avaliados"] or 0
    return {
        "videos_produzidos": r["produzidos"] or 0,
        "tempo_medio_s": round(r["tempo"], 1) if r["tempo"] is not None else None,
        "custo_medio_creditos": round(r["custo"], 2) if r["custo"] is not None else None,
        "taxa_aprovacao": round((r["aprovados"] or 0) / avaliados, 2) if avaliados else None,
        "avaliados": avaliados,
    }


def _hidratar(row) -> dict | None:
    if not row:
        return None
    job = dict(row)
    job["config"] = json.loads(job["config"])
    return job
