"""Provider LOCAL de LLM (Ollama) — FALLBACK, nunca primário.

Roda um modelo 3B local (llama3.2:3b) em CPU. Entra só quando o provider
principal (Anthropic/Groq) falha (timeout/erro) — degradação graciosa, não
substituição. Texto-only (sem visão). Best-effort: Ollama fora → devolve None e
o chamador cai nas regras determinísticas.

ponytail: urllib da stdlib (sem `requests`/SDK novo); a interface fixa é uma
função `completar(prompt) -> str|None`. Provider trocável por env, nunca vaza
nome pra cima.
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request

def _url() -> str:
    return os.environ.get("OLLAMA_URL", "http://127.0.0.1:11434")


def _modelo() -> str:
    return os.environ.get("OLLAMA_MODEL", "llama3.2:3b")


def completar(prompt: str, *, max_tokens: int = 400, temperature: float = 0) -> str | None:
    """Texto do modelo local pro prompt. None se o Ollama estiver fora/erro/timeout
    (o chamador degrada). Determinístico por padrão (temperature=0). Env lido em
    tempo de chamada (OLLAMA_URL/OLLAMA_MODEL/OLLAMA_TIMEOUT_S)."""
    corpo = json.dumps({
        "model": _modelo(), "prompt": prompt, "stream": False,
        "options": {"temperature": temperature, "num_predict": max_tokens},
    }).encode("utf-8")
    req = urllib.request.Request(f"{_url()}/api/generate", data=corpo,
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=int(os.environ.get("OLLAMA_TIMEOUT_S", "30"))) as r:
            resp = json.loads(r.read().decode("utf-8"))
        texto = resp.get("response")
        return texto if isinstance(texto, str) and texto.strip() else None
    except (urllib.error.URLError, TimeoutError, ValueError, OSError):
        return None


def disponivel() -> bool:
    """True se o Ollama responde (pro health/diagnóstico)."""
    try:
        with urllib.request.urlopen(f"{_url()}/api/tags", timeout=3) as r:
            return r.status == 200
    except (urllib.error.URLError, TimeoutError, OSError):
        return False


if __name__ == "__main__":  # self-check (exige Ollama rodando)
    assert disponivel(), "Ollama não está no ar em " + OLLAMA_URL
    t = completar('Responda APENAS um JSON: {"ok": true}', max_tokens=20)
    assert t and "{" in t, t
    print("local_llm OK — resposta:", t[:80].replace("\n", " "))
