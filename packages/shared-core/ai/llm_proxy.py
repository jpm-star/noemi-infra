"""Cliente da camada única de LLM (LiteLLM Proxy) — interface fixa.

Roteia por NOME LÓGICO (analise/motor-b — nunca provider cru pra cima) pro proxy
OpenAI-compatível, que faz fallback entre os cloud + registra custo/latência/
modelo/erro no dashboard. Ollama fica FORA do proxy (fallback offline em
local_llm, loopback seguro). urllib stdlib, sem dep nova. Best-effort: proxy
fora → None (chamador cai no local_llm/regras).
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request


def _base() -> str:
    return os.environ.get("LITELLM_URL", "http://127.0.0.1:4000")


def completar(prompt: str, *, model: str = "analise", max_tokens: int = 400,
              temperature: float = 0) -> str | None:
    """Texto do proxy pro prompt (chat/completions). None se o proxy estiver
    fora/erro/timeout. `model` é o nome lógico do config (analise/motor-b)."""
    corpo = json.dumps({
        "model": model, "messages": [{"role": "user", "content": prompt}],
        "max_tokens": max_tokens, "temperature": temperature,
    }).encode("utf-8")
    req = urllib.request.Request(
        f"{_base()}/v1/chat/completions", data=corpo,
        headers={"Content-Type": "application/json",
                 "Authorization": f"Bearer {os.environ.get('LITELLM_MASTER_KEY', '')}"})
    try:
        with urllib.request.urlopen(req, timeout=int(os.environ.get("LITELLM_TIMEOUT_S", "45"))) as r:
            d = json.loads(r.read().decode("utf-8"))
        texto = d["choices"][0]["message"]["content"]
        return texto if isinstance(texto, str) and texto.strip() else None
    except (urllib.error.URLError, TimeoutError, ValueError, KeyError, IndexError, OSError):
        return None


def disponivel() -> bool:
    try:
        with urllib.request.urlopen(f"{_base()}/health/liveliness", timeout=3) as r:
            return r.status == 200
    except (urllib.error.URLError, TimeoutError, OSError):
        return False
