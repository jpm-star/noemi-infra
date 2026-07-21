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
        job = jobs.proximo_na_fila()
        if not job:
            await asyncio.sleep(float(os.environ.get("WORKER_POLL_S", "1")))
            continue
        await processar(job)


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
        # (mock: asset já está no bucket local; provider real faz upload aqui)
        if not jobs.atualizar(jid, "processing"):
            return
        out = await asyncio.to_thread(video.generate, origem, job["config"])
        asset_video = storage.create_asset(
            owner=origem["owner"], produto=jobs.PRODUTO, mime=out["mime"], dados=out["bytes"],
            metadata={"asset_origem": origem["id"], "job": jid,
                      "modelo": out["modelo"], **out.get("meta", {})},
        )
        jobs.atualizar(jid, "completed", asset_video=asset_video["id"], erro=None)
        log_span("motor_b.job", job=jid, ok=True, asset_video=asset_video["id"])
    except Exception as e:
        tentativas = job["tentativas"] + 1
        if tentativas < jobs.MAX_TENTATIVAS:
            jobs.atualizar(jid, "retry", tentativas=tentativas, erro=str(e))
        else:
            jobs.atualizar(jid, "failed", tentativas=tentativas, erro=str(e))
        log_span("motor_b.job", job=jid, ok=False, tentativas=tentativas, erro=str(e))
