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
from fastapi.responses import FileResponse, HTMLResponse
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


@app.post("/api/jobs/{job_id}/aprovar")
def aprovar_job(job_id: str, corpo: dict | None = None) -> dict:
    """Marca se o cliente aceitou o vídeo de primeira (taxa de aprovação)."""
    aprovado = True if corpo is None else bool(corpo.get("aprovado", True))
    if not jobs.marcar_aprovado(job_id, aprovado):
        raise HTTPException(404, "job não encontrado ou ainda não concluído")
    return {"job_id": job_id, "aprovado": aprovado}


@app.get("/api/dashboard")
def dashboard_dados() -> dict:
    return jobs.metricas()


@app.get("/dashboard", response_class=HTMLResponse)
def dashboard_pagina() -> str:
    return _DASHBOARD_HTML


_DASHBOARD_HTML = """<!doctype html><html lang="pt-BR"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>Motor B — Dashboard</title>
<style>:root{color-scheme:dark}*{box-sizing:border-box;margin:0}body{font-family:system-ui,sans-serif;
background:#0b0f1a;color:#e6e9f0;padding:32px;max-width:760px;margin:0 auto}h1{font-size:1.3rem;margin-bottom:4px}
h1 span{color:#7c5cff}p.sub{color:#8b93a7;font-size:.9rem;margin-bottom:24px}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:16px}
.card{background:#131a2b;border:1px solid #232d45;border-radius:14px;padding:20px}
.card .v{font-size:2rem;font-weight:800;color:#fff}.card .l{color:#8b93a7;font-size:.82rem;margin-top:4px}
.na{color:#5b647d;font-size:1.1rem;font-weight:600}</style></head><body>
<h1>🎥 Motor B — <span>Dashboard</span></h1><p class="sub">Indicadores de produção de vídeo.</p>
<div class="grid" id="g"></div>
<script>
const fmt=(v,suf='')=>v===null||v===undefined?'<span class=na>—</span>':v+suf;
fetch('/api/dashboard').then(r=>r.json()).then(d=>{
  const cards=[
    ['Vídeos produzidos',fmt(d.videos_produzidos)],
    ['Tempo médio de geração',fmt(d.tempo_medio_s,'s')],
    ['Custo médio',fmt(d.custo_medio_creditos,' cr')],
    ['Taxa de aprovação',d.taxa_aprovacao===null?'<span class=na>sem avaliações</span>':(Math.round(d.taxa_aprovacao*100)+'%')],
  ];
  document.getElementById('g').innerHTML=cards.map(([l,v])=>
    `<div class=card><div class=v>${v}</div><div class=l>${l}</div></div>`).join('');
});
</script></body></html>"""


app.mount("/", StaticFiles(directory=_AQUI / "static", html=True))
