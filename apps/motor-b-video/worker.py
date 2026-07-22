"""Worker do Motor B — asyncio in-process, 1 job por vez.

ponytail: polling 1s + worker único no mesmo processo do FastAPI; RQ/arq só
quando houver volume real de geração simultânea.
"""
from __future__ import annotations

import asyncio
import json
import os
import time

import brand
import jobs
import media
import metadados
import pos
import prompt_builder
import storyboard
import templates
from shared_core import storage
from shared_core.ai import classificacao, video
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
        # v1.1: classifica o imóvel → escolhe template → constrói o prompt específico,
        # ANTES do Higgsfield. Substitui prompt genérico por prompt ajustado ao segmento.
        cfg = await asyncio.to_thread(_planejar, origem, job)
        if not jobs.atualizar(jid, "processing", config=json.dumps(cfg, ensure_ascii=False)):
            return
        t0 = time.monotonic()
        # item 4: storyboard = várias cenas encadeadas num walkthrough; senão, 1 clipe.
        if storyboard.eh_storyboard(cfg):
            out = await asyncio.to_thread(
                storyboard.gerar_walkthrough, origem, cfg, cfg.get("brand") or {}, jid,
                get_asset=storage.get_asset, asset_file=storage.asset_file)
        else:
            out = await asyncio.to_thread(video.generate, origem, cfg)
        duracao_s = round(time.monotonic() - t0, 2)
        # Onda 1: acabamento de marca (reframe/watermark/legenda) — best-effort,
        # falha degrada pro vídeo cru, nunca derruba o job.
        pos_meta = await asyncio.to_thread(_finalizar, out, cfg, jid)
        asset_video = storage.create_asset(
            owner=origem["owner"], produto=jobs.PRODUTO, mime=out["mime"], dados=out["bytes"],
            metadata={"asset_origem": origem["id"], "job": jid, "brand": cfg.get("brand"),
                      "titulo": cfg.get("titulo"),
                      "modelo": out["modelo"], "pos": pos_meta, **out.get("meta", {})},
        )
        if not jobs.atualizar(jid, "completed", asset_video=asset_video["id"], erro=None,
                              duracao_s=duracao_s, custo_creditos=out.get("custo_creditos") or 0):
            storage.delete_asset(asset_video["id"])  # cancelado no meio: sem asset órfão
            return
        job = {**job, "config": cfg}  # o registro de interação usa o cfg enriquecido
        log_span("motor_b.job", job=jid, ok=True, asset_video=asset_video["id"], dur_s=duracao_s)
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


def _planejar(origem: dict, job: dict) -> dict:
    """v1.1: classifica o imóvel → escolhe template → constrói o prompt específico.
    Devolve o config ENRIQUECIDO (prompt ajustado ao segmento) que vai pro generate."""
    base = dict(job.get("config") or {})
    # _imagem_path só vai pra classificar (visão no modo real); NÃO entra no config
    # persistido/logado (é interno) — o cfg de retorno usa `base`, não `entrada`.
    entrada = {**base, "asset_origem": origem["id"], "owner": origem.get("owner"),
               "_imagem_path": str(storage.asset_file(origem))}
    clas = classificacao.classificar(entrada)
    template = templates.escolher_template(clas, base.get("template"))
    kit = brand.brand_kit(origem.get("owner"), base)  # Brand Kit automático
    plano = prompt_builder.construir_prompt(clas, template, entrada, brand=kit)
    return {**base, "prompt": plano["prompt"], "duration": plano["duration"],
            "aspect_ratio": plano["aspect_ratio"], "template": template["id"],
            "movimento": plano["movimento"], "brand": kit, "classificacao": clas,
            "titulo": metadados.titulo(clas, base),  # metadado de publicação
            "segmento": base.get("segmento") or clas.get("padrao")}


def _finalizar(out: dict, cfg: dict, jid: str) -> dict:
    """Pós-processa o vídeo pronto (marca + reframe + legenda). Muta out['bytes']/
    out['mime'] in-place. Best-effort: PosErro degrada pro vídeo cru. Devolve o
    meta do que foi aplicado (entra na metadata do asset)."""
    kit = cfg.get("brand") or {}
    legenda = kit.get("cta_texto") if (cfg.get("classificacao") or {}).get("cta", True) else None
    try:
        novos, novo_mime, meta = pos.pos_processar(
            out["bytes"], out["mime"], aspect=cfg.get("aspect_ratio"),
            brand=kit, legenda=legenda)
    except pos.PosErro as e:
        log_span("motor_b.pos", job=jid, ok=False, nivel=e.nivel, erro=e.mensagem)
        return {"aplicado": [], "erro": e.mensagem}
    out["bytes"], out["mime"] = novos, novo_mime
    log_span("motor_b.pos", job=jid, ok=True, aplicado=meta["aplicado"])
    return meta


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
