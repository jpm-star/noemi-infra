"""Retenção de disco do Motor B — roda por systemd timer (ver deploy/).

Política (documentada no README):
- Asset de ORIGEM de job TERMINAL (completed/failed/cancelled) mais velho que
  RETENTION_DIAS (default 30) tem o ARQUIVO purgado; o VÍDEO final é preservado,
  e a linha do asset fica (proveniência + FK jobs.asset_origem intacta).
- obs.jsonl acima de OBS_MAX_MB (default 50) é rotacionado pra obs.jsonl.1
  (mantém 1 geração; a próxima rotação sobrescreve).

ponytail: GC por idade, sem storage frio/S3 — o risco era enche-disco silencioso
(auditoria N2). Nuvem só quando houver volume que pague o serviço a mais.
"""
from __future__ import annotations

import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "packages"))

from shared_core import storage
from shared_core.obs import log_span
from shared_core.storage.db import conn, data_dir


def limpar(dias: int | None = None, obs_max_mb: int | None = None) -> dict:
    dias = int(os.environ.get("RETENTION_DIAS", "30")) if dias is None else dias
    obs_max_mb = int(os.environ.get("OBS_MAX_MB", "50")) if obs_max_mb is None else obs_max_mb
    corte = (datetime.now(timezone.utc) - timedelta(days=dias)).isoformat()
    resumo = {
        "origens_purgadas": _purgar_origens_velhas(corte),
        "obs_rotacionado": _rotacionar_obs(obs_max_mb),
        "corte": corte,
    }
    log_span("motor_b.retencao", **resumo)
    return resumo


def _purgar_origens_velhas(corte: str) -> int:
    with conn() as c:
        rows = c.execute(
            "SELECT DISTINCT asset_origem FROM jobs "
            "WHERE estado IN ('completed','failed','cancelled') AND atualizado_em < ?",
            (corte,),
        ).fetchall()
    return sum(storage.purge_asset_file(r["asset_origem"]) for r in rows)


def _rotacionar_obs(max_mb: int) -> bool:
    obs = data_dir() / "obs.jsonl"
    if not obs.exists() or obs.stat().st_size < max_mb * 1024 * 1024:
        return False
    obs.replace(data_dir() / "obs.jsonl.1")
    return True


if __name__ == "__main__":
    print(limpar())
