"""Motor B — Vídeo IA. FastAPI na :8010 (API + front estático).

Fluxo: POST /api/upload → POST /api/jobs → GET /api/jobs/{id} (polling)
       → GET /api/assets/{id}/file (vídeo pronto).
"""
from __future__ import annotations

import asyncio
import os
import sys
from contextlib import asynccontextmanager
from pathlib import Path

_AQUI = Path(__file__).resolve().parent
sys.path.insert(0, str(_AQUI.parents[1] / "packages"))  # shared_core (symlink)
sys.path.insert(0, str(_AQUI))

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

import jobs
import worker
from shared_core import storage

# Fronteira de confiança do upload: allowlist de mime + teto de tamanho.
MIMES_ACEITOS = {
    "image/jpeg", "image/png", "image/webp", "image/heic",
    "video/mp4", "video/quicktime", "video/webm",
}


def _max_bytes() -> int:
    # ponytail: 25MB default e upload inteiro em RAM; streaming pra disco quando
    # vídeo bruto grande virar caso real (aí sobe o teto junto com o Caddy)
    return int(os.environ.get("MAX_UPLOAD_MB", "25")) * 1024 * 1024


@asynccontextmanager
async def _vida(app: FastAPI):
    requeued = jobs.requeue_orfaos()  # jobs em voo quando o processo morreu
    if requeued:
        print(f"[motor-b] {requeued} job(s) órfão(s) devolvidos à fila como retry")
    tarefa = asyncio.create_task(worker.loop())
    yield
    tarefa.cancel()


app = FastAPI(title="Motor B — Vídeo IA", lifespan=_vida)


@app.get("/health")
def health() -> dict:
    return {"ok": True, "mock": os.environ.get("MOCK_MODE", "true").lower() != "false"}


@app.post("/api/upload")
async def upload(file: UploadFile = File(...), owner: str = Form("cliente")) -> dict:
    if file.content_type not in MIMES_ACEITOS:
        raise HTTPException(415, f"tipo não aceito: {file.content_type} (aceitos: imagem ou vídeo)")
    dados = await file.read(_max_bytes() + 1)
    if len(dados) > _max_bytes():
        raise HTTPException(413, f"arquivo acima de {os.environ.get('MAX_UPLOAD_MB', '200')}MB")
    if not dados:
        raise HTTPException(400, "arquivo vazio")
    asset = storage.create_asset(
        owner=owner.strip()[:120] or "cliente", produto=jobs.PRODUTO,
        mime=file.content_type, dados=dados,
        metadata={"filename": Path(file.filename or "upload").name[:200]},
    )
    return {"asset_id": asset["id"], "hash": asset["hash"], "bytes": len(dados)}


@app.post("/api/jobs")
def criar_job(corpo: dict) -> dict:
    asset_id = corpo.get("asset_id", "")
    if not storage.get_asset(asset_id):
        raise HTTPException(404, "asset não encontrado — faça o upload primeiro")
    config = corpo.get("config") or {}
    if not isinstance(config, dict):
        raise HTTPException(422, "config deve ser um objeto")
    if "duration" in config:  # fronteira: duration ilimitada = ffmpeg/crédito bomb
        try:
            config["duration"] = max(1, min(15, int(config["duration"])))
        except (TypeError, ValueError):
            raise HTTPException(422, "duration deve ser número de segundos")
    job = jobs.criar(asset_id, config)
    return {"job_id": job["id"], "estado": job["estado"]}


# (sem GET /api/jobs de listagem: público vazaria jobs/assets de todos os
#  clientes; histórico fica no DB e entra no painel do operador COM auth)


@app.get("/api/jobs/{job_id}")
def status_job(job_id: str) -> dict:
    job = jobs.obter(job_id)
    if not job:
        raise HTTPException(404, "job não encontrado")
    if job["estado"] == "completed" and job["asset_video"]:
        job["video_url"] = f"/api/assets/{job['asset_video']}/file"
    if job.get("erro"):  # detalhe cru só no obs.jsonl; público recebe genérico
        job["erro"] = "falha na geração — detalhes no log do operador"
    return job


@app.post("/api/jobs/{job_id}/cancel")
def cancelar_job(job_id: str) -> dict:
    if not jobs.obter(job_id):
        raise HTTPException(404, "job não encontrado")
    cancelou = jobs.atualizar(job_id, "cancelled")
    return {"job_id": job_id, "cancelado": cancelou,
            "estado": jobs.obter(job_id)["estado"]}


@app.get("/api/assets/{asset_id}/file")
def baixar_asset(asset_id: str):
    asset = storage.get_asset(asset_id)
    if not asset:
        raise HTTPException(404, "asset não encontrado")
    caminho = storage.asset_file(asset)
    if not caminho.exists():
        raise HTTPException(410, "arquivo do asset não está mais no bucket")
    return FileResponse(caminho, media_type=asset["mime"],
                        filename=f"{asset['id']}.{asset['mime'].split('/')[-1]}")


app.mount("/", StaticFiles(directory=_AQUI / "static", html=True))
