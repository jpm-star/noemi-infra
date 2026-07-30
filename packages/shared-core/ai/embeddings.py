"""Embeddings — interface fixa `gerar(textos) -> list[vetor]`. Provider (Gemini)
escondido (CLAUDE.md: nunca vaza provider pra cima). stdlib (urllib), sem dep nova.

Base da Fase 0 do Knowledge OS: vetoriza a Caixa de Ideias (video_analises) pra
busca semântica + dedup. Best-effort: sem chave/erro → [] (o chamador degrada).
Chave: GEMINI_API_KEY. Modelo: EMBED_MODELO (default text-embedding-004).
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import re
import urllib.error
import urllib.request

_MODELO = os.environ.get("EMBED_MODELO", "gemini-embedding-001")
_DIM = int(os.environ.get("EMBED_DIM", "768"))
_DIM_LOCAL = int(os.environ.get("EMBED_DIM_LOCAL", "512"))
_URL = "https://generativelanguage.googleapis.com/v1beta/models/{m}:embedContent?key={k}"
# BACKEND: "local" (bag-of-words por hashing, zero-dep, sempre disponível) é o padrão —
# a chave Gemini atual tem embeddings NEGADO (403). "gemini" = upgrade semântico quando
# a Embeddings API for habilitada no projeto (ou uma key com acesso for provida).
_BACKEND = os.environ.get("EMBED_BACKEND", "local")


def _backend_padrao():
    if _BACKEND == "gemini" and os.environ.get("GEMINI_API_KEY", "").strip():
        return _embed_one_http
    return _embed_one_local


def gerar(textos: list[str], *, _embed_one=None) -> list[list[float]]:
    """Lista de vetores (1 por texto). Vetor vazio [] p/ o texto que falhar (o chamador
    pula). `_embed_one(texto)->vec` injetável p/ teste. Backend por env EMBED_BACKEND."""
    if not textos:
        return []
    fn = _embed_one or _backend_padrao()
    out: list[list[float]] = []
    for t in textos:
        try:
            out.append(fn(str(t or "")[:8000]))
        except Exception:  # noqa: BLE001 — texto falha isolado → vetor vazio, os outros seguem
            out.append([])
    return out


def _embed_one_local(texto: str) -> list[float]:
    """Embedding LOCAL: bag-of-words normalizado por hashing (zero-dep, determinístico).
    Não é semântico (é lexical: palavras em comum), mas dá busca/dedup funcional já."""
    vec = [0.0] * _DIM_LOCAL
    for tok in re.findall(r"[a-zà-ú0-9]{3,}", texto.lower()):
        vec[int(hashlib.md5(tok.encode()).hexdigest(), 16) % _DIM_LOCAL] += 1.0
    return vec


def _embed_one_http(texto: str) -> list[float]:
    key = os.environ.get("GEMINI_API_KEY", "").strip()
    corpo = json.dumps({"model": f"models/{_MODELO}", "content": {"parts": [{"text": texto}]},
                        "outputDimensionality": _DIM}).encode()
    req = urllib.request.Request(_URL.format(m=_MODELO, k=key), data=corpo,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=int(os.environ.get("EMBED_TIMEOUT_S", "30"))) as r:
        return json.loads(r.read().decode("utf-8"))["embedding"]["values"]


def cosseno(a: list[float], b: list[float]) -> float:
    """Similaridade cosseno entre dois vetores. 0.0 se algum for vazio/degenerado."""
    if not a or not b or len(a) != len(b):
        return 0.0
    num = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    return num / (na * nb) if na and nb else 0.0


if __name__ == "__main__":  # self-check offline (mocka o POST — sem rede)
    vs = gerar(["gato", "cachorro"], _embed_one=lambda t: [1.0, 0.0, 0.0] if "gato" in t else [0.0, 1.0, 0.0])
    assert len(vs) == 2 and vs[0] == [1.0, 0.0, 0.0]
    assert abs(cosseno([1, 0, 0], [1, 0, 0]) - 1.0) < 1e-9   # idênticos = 1
    assert abs(cosseno([1, 0, 0], [0, 1, 0])) < 1e-9          # ortogonais = 0
    assert cosseno([], [1, 2]) == 0.0                          # degenerado = 0
    # backend LOCAL (sem chave, sempre funciona): iguais -> sim 1; diferente -> < 0.5
    a, b, c = gerar(["site que converte visitante", "site que converte visitante", "escassez urgencia na oferta"])
    assert a and abs(cosseno(a, b) - 1.0) < 1e-9 and cosseno(a, c) < 0.5
    print("embeddings OK — mock, cosseno, backend local (bag-of-words) funcional sem chave")
