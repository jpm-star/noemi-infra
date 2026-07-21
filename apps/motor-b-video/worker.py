"""Worker do Motor B — asyncio in-process, 1 job por vez.

ponytail: polling 1s + worker único no mesmo processo do FastAPI; RQ/arq só
quando houver volume real de geração simultânea.
"""
from __future__ import annotations

import asyncio
import os

import jobs
import media
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
        # estado uploading: normaliza a mídia de entrada in-place (resolução/codec/
        # bitrate consistentes). Best-effort — falha degrada pro original. Isto é o
        # que a Fase 2 (image-to-video real) enviará ao Higgsfield; hoje encolhe disco.
        origem = await asyncio.to_thread(_normalizar_origem, origem, jid)
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
        # logging de interação REAL (não-mock): fundação honesta pro tuning futuro.
        # Mock (modelo mock/*) NUNCA entra — a tabela fica vazia até a 1ª geração
        # Higgsfield de verdade (MOCK_MODE=false). NÃO é tuning, só guarda histórico.
        # Fire-and-forget: o job já está completed; falha aqui não pode reverter isso.
        if not out["modelo"].startswith("mock"):
            try:
                cfg = job["config"] or {}
                storage.registrar_interacao(
                    produto=jobs.PRODUTO, cliente=origem.get("owner"),
                    segmento=cfg.get("segmento"),
                    input={"prompt": cfg.get("prompt"), "config": cfg},
                    output={"asset_video": asset_video["id"], "meta": out.get("meta")},
                    modelo=out["modelo"])
            except Exception as e:
                log_span("motor_b.interacao", job=jid, ok=False, erro=str(e))
    except Exception as e:
        tentativas = job["tentativas"] + 1
        if tentativas < jobs.MAX_TENTATIVAS:
            jobs.atualizar(jid, "retry", tentativas=tentativas, erro=str(e))
        else:
            jobs.atualizar(jid, "failed", tentativas=tentativas, erro=str(e))
        log_span("motor_b.job", job=jid, ok=False, tentativas=tentativas, erro=str(e))


def _normalizar_origem(origem: dict, jid: str) -> dict:
    """Normaliza a mídia de origem in-place (mesmo asset id). Idempotente: retry
    não re-normaliza. Best-effort: erro de ffmpeg segue com o original, marcado."""
    if origem["metadata"].get("normalizado") is not None:
        return origem  # já passou pela normalização (sucesso ou degradação)
    dados = storage.asset_file(origem).read_bytes()
    try:
        novos, novo_mime = media.normalizar(dados, origem["mime"])
    except media.NormalizacaoErro as e:
        # degradação: NÃO reescreve os bytes (podem ser 25MB) — só marca metadata
        log_span("motor_b.normalizacao", job=jid, ok=False, nivel=e.nivel, erro=e.mensagem)
        return storage.update_asset_meta(
            origem["id"],
            {"normalizado": False, "normalizacao_erro": e.mensagem}) or origem
    log_span("motor_b.normalizacao", job=jid, ok=True, asset=origem["id"],
             de=len(dados), para=len(novos), mime=novo_mime)
    return storage.replace_asset_bytes(
        origem["id"], novos, novo_mime,
        extra_meta={"normalizado": True, "mime_original": origem["mime"],
                    "bytes_original": len(dados), "bytes_norm": len(novos)}) or origem
