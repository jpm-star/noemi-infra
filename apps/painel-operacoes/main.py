"""Painel de observabilidade da Noemi OS — FastAPI read-only na :8030.

Serve o snapshot agregado (/api/painel) e a tela única (/painel). Nenhuma rota de
escrita/ação: só leitura e diagnóstico. Mesmo padrão do dashboard do Motor B.
"""
from __future__ import annotations

import sys
from pathlib import Path

_AQUI = Path(__file__).resolve().parent
sys.path.insert(0, str(_AQUI))

from fastapi import FastAPI
from fastapi.responses import HTMLResponse, JSONResponse

import agg

app = FastAPI(title="Painel Noemi OS")


@app.get("/health")
def health() -> dict:
    return {"ok": True}


@app.get("/api/painel")
def painel_dados() -> JSONResponse:
    return JSONResponse(agg.snapshot())


@app.get("/painel", response_class=HTMLResponse)
@app.get("/", response_class=HTMLResponse)
def painel_pagina() -> str:
    return (_AQUI / "static" / "index.html").read_text(encoding="utf-8")
