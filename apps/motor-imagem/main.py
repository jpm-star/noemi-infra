"""Motor Imagem — STUB (porta 8011 reservada, ainda sem processo).

Uso real indefinido até o teste com Pé Di. Mesma forma do Motor B quando
nascer: upload → fila → status, via shared_core (video vira image aqui).
ponytail: esqueleto sem carne de propósito — não adivinhar caso de uso.
"""
from __future__ import annotations

import sys
from pathlib import Path

_AQUI = Path(__file__).resolve().parent
sys.path.insert(0, str(_AQUI.parents[1] / "packages"))

from fastapi import FastAPI, HTTPException

app = FastAPI(title="Motor Imagem — em construção")


@app.get("/health")
def health() -> dict:
    return {"ok": True, "status": "stub"}


@app.post("/api/upload")
@app.post("/api/jobs")
def ainda_nao() -> dict:
    raise HTTPException(501, "Motor Imagem sem caso de uso definido ainda (aguardando teste com Pé Di)")
