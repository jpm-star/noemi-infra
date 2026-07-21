"""Worker do Motor B — asyncio in-process, 1 job por vez.

ponytail: polling 1s + worker único no mesmo processo do FastAPI; RQ/arq só
quando houver volume real de geração simultânea.
"""
from __future__ import annotations

import asyncio
import os

import jobs
from shared_core import storage
from shared_core.ai import video
from shared_core.obs import log_span


async def loop() -> None:
    while True:
        try:
            job = jobs.proximo_na_fila()
            if not job:
                await asyncio.sleep(float(os.environ.get("WORKER_POLL_S", "1")))
                continue
            await processar(job)
        except Exception as e:  # ex.: sqlite locked — worker nunca morre silencioso
            log_span("motor_b.worker", ok=False, erro=str(e))
            await asyncio.sleep(1)


async def processar(job: dict) -> None:
    jid = job["id"]
    try:
        # cada transição é atômica: se o job foi cancelado, atualizar() retorna
        # False e o processamento para ali — sem checagem separada de estado.
        if not jobs.atualizar(jid, "uploading"):
            return
        origem = storage.get_asset(job["asset_origem"])
        if origem is None:
            jobs.atualizar(jid, "failed", erro="asset de origem sumiu do storage")
            return
        # estado uploading: mock não envia nada; modo real hoje é prompt-only
        # (upload da mídia pro provider = Fase 2, ver PENDENCIAS.md)
        if not jobs.atualizar(jid, "processing"):
            return
        out = await asyncio.to_thread(video.generate, origem, job["config"])
        asset_video = storage.create_asset(
            owner=origem["owner"], produto=jobs.PRODUTO, mime=out["mime"], dados=out["bytes"],
            metadata={"asset_origem": origem["id"], "job": jid,
                      "modelo": out["modelo"], **out.get("meta", {})},
        )
        if not jobs.atualizar(jid, "completed", asset_video=asset_video["id"], erro=None):
            storage.delete_asset(asset_video["id"])  # cancelado no meio: sem asset órfão
            return
        log_span("motor_b.job", job=jid, ok=True, asset_video=asset_video["id"])
    except Exception as e:
        tentativas = job["tentativas"] + 1
        if tentativas < jobs.MAX_TENTATIVAS:
            jobs.atualizar(jid, "retry", tentativas=tentativas, erro=str(e))
        else:
            jobs.atualizar(jid, "failed", tentativas=tentativas, erro=str(e))
        log_span("motor_b.job", job=jid, ok=False, tentativas=tentativas, erro=str(e))
