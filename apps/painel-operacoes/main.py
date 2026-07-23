"""Painel de observabilidade da Noemi OS — FastAPI read-only na :8030.

Serve o snapshot agregado (/api/painel) e a tela única (/painel). Nenhuma rota de
escrita/ação: só leitura e diagnóstico. Mesmo padrão do dashboard do Motor B.
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

_AQUI = Path(__file__).resolve().parent
sys.path.insert(0, str(_AQUI))
sys.path.insert(0, str(_AQUI.parents[1] / "packages"))  # shared_core (llm_proxy)

from fastapi import FastAPI
from fastapi.responses import HTMLResponse, JSONResponse

import agg

app = FastAPI(title="Painel Noemi OS")

_DIAG_CACHE: dict = {"ts": 0.0, "dados": None}
_DIAG_TTL = 90  # segundos — não chama o LLM a cada refresh (custo/latência)


def _resumo(snap: dict) -> str:
    """Comprime o snapshot no sinal que importa pro diagnóstico."""
    down = [m["nome"] for m in snap["motores"] if m["status"] != "up"]
    L, F = snap["llm"], snap["fila"]
    linhas = [
        f"Serviços fora: {down or 'nenhum'}.",
        f"Fila: {F.get('em_andamento', 0)} rodando, {F.get('contagem', {}).get('failed', 0)} falharam.",
        f"Falhas agrupadas: {snap['erros']['agrupados'] or 'nenhuma'}.",
        f"Custo hoje: ${L.get('custo', {}).get('hoje', 0)}. Latência P95: {L.get('latencia', {}).get('p95', 0)}ms.",
        f"Cascata de IA (uso): {snap['fallback']}.",
        f"VPS: CPU {snap['vps'].get('cpu_pct')}%, RAM {snap['vps'].get('ram_pct')}%, disco {snap['vps'].get('disco_pct')}%.",
    ]
    return " ".join(linhas)


def _diagnostico() -> dict:
    if _DIAG_CACHE["dados"] and time.time() - _DIAG_CACHE["ts"] < _DIAG_TTL:
        return _DIAG_CACHE["dados"]
    snap = agg.snapshot()
    resumo = _resumo(snap)
    prompt = (
        "Você é o operador sênior da Noemi OS (SO que roda geração de sites, vídeos de "
        "imóvel e arbitragem). Olhe o estado AGORA e dê no máximo 3 dicas curtas, "
        "concretas e acionáveis (o que fazer já), priorizando o que impede vender ou o "
        "que quebrou. Uma dica por linha, começando com '- '. Se está tudo saudável, "
        "responda só '- Operação saudável, nada urgente.'\n\nEstado: " + resumo)
    try:
        from shared_core.ai import llm_proxy
        txt = llm_proxy.completar(prompt, model="analise", max_tokens=220, temperature=0.2)
    except Exception:
        txt = None
    if not txt:  # proxy fora → dica por regra (best-effort, nunca vazio)
        down = [m["nome"] for m in snap["motores"] if m["status"] != "up"]
        txt = ("- " + ", ".join(down) + " fora — reiniciar/checar." if down
               else "- IA indisponível; operação sem alertas críticos pelos números.")
    dicas = [l.strip("- ").strip() for l in txt.splitlines() if l.strip().startswith("-")] or [txt.strip()]
    dados = {"dicas": dicas[:3], "resumo": resumo, "gerado_em": snap["ts"], "fonte": "analise"}
    _DIAG_CACHE.update(ts=time.time(), dados=dados)
    return dados


@app.get("/health")
def health() -> dict:
    return {"ok": True}


@app.get("/api/painel")
def painel_dados() -> JSONResponse:
    return JSONResponse(agg.snapshot())


@app.get("/api/diagnostico")
def diagnostico_dados() -> JSONResponse:
    return JSONResponse(_diagnostico())


# Fila de prospecção: demos de site gerados p/ prospects (status manual do JP).
# Fonte = data/prospeccao.json (escrito pelo lote batch_demos + edição à mão).
_PROSPECCAO = _AQUI.parents[1] / "data" / "prospeccao.json"


@app.get("/api/prospeccao")
def prospeccao_dados() -> JSONResponse:
    import json
    try:
        return JSONResponse(json.loads(_PROSPECCAO.read_text(encoding="utf-8")))
    except (OSError, ValueError):
        return JSONResponse({"prospects": [], "tenant": None})


@app.get("/painel", response_class=HTMLResponse)
@app.get("/", response_class=HTMLResponse)
def painel_pagina() -> str:
    return (_AQUI / "static" / "index.html").read_text(encoding="utf-8")
