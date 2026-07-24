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
import time
import urllib.error
import urllib.request

# 429/503 = rate-limit/sobrecarga TRANSITÓRIA: vale tentar de novo antes de
# degradar pro Ollama 3B (senão um blip de TPM derruba o cloud calado — o
# "fallback mentiroso" da memória). Erro duro (401/400) NÃO repete: degrada já.
_TRANSITORIO = {429, 500, 502, 503, 504}


def _base() -> str:
    return os.environ.get("LITELLM_URL", "http://127.0.0.1:4000")


def _espera(e: urllib.error.HTTPError, tentativa: int) -> float:
    """Segundos a esperar: honra Retry-After do provider; senão backoff
    exponencial (1s, 2s, 4s…), tudo capado pra não pendurar o pipeline."""
    teto = float(os.environ.get("LITELLM_BACKOFF_TETO_S", "8"))
    ra = e.headers.get("Retry-After") if e.headers else None
    if ra:
        try:
            return min(float(ra), teto)
        except ValueError:
            pass
    return min(2.0 ** tentativa, teto)


def completar(prompt: str, *, model: str = "analise", max_tokens: int = 400,
              temperature: float = 0) -> str | None:
    """Texto do proxy pro prompt (chat/completions). None se o proxy estiver
    fora/erro/timeout. `model` é o nome lógico do config (analise/motor-b).
    Repete em 429/5xx (respeitando Retry-After) até LITELLM_RETRIES antes de
    devolver None — o chamador só degrada quando o cloud realmente esgotou."""
    corpo = json.dumps({
        "model": model, "messages": [{"role": "user", "content": prompt}],
        "max_tokens": max_tokens, "temperature": temperature,
    }).encode("utf-8")
    retries = int(os.environ.get("LITELLM_RETRIES", "2"))
    for tentativa in range(retries + 1):
        req = urllib.request.Request(
            f"{_base()}/v1/chat/completions", data=corpo,
            headers={"Content-Type": "application/json",
                     "Authorization": f"Bearer {os.environ.get('LITELLM_MASTER_KEY', '')}"})
        try:
            with urllib.request.urlopen(req, timeout=int(os.environ.get("LITELLM_TIMEOUT_S", "45"))) as r:
                d = json.loads(r.read().decode("utf-8"))
            texto = d["choices"][0]["message"]["content"]
            return texto if isinstance(texto, str) and texto.strip() else None
        except urllib.error.HTTPError as e:
            if e.code in _TRANSITORIO and tentativa < retries:
                time.sleep(_espera(e, tentativa))
                continue
            return None  # erro duro (401/400) ou retries esgotados → degrada
        except (urllib.error.URLError, TimeoutError, ValueError, KeyError, IndexError, OSError):
            return None
    return None


def disponivel() -> bool:
    try:
        with urllib.request.urlopen(f"{_base()}/health/liveliness", timeout=3) as r:
            return r.status == 200
    except (urllib.error.URLError, TimeoutError, OSError):
        return False


if __name__ == "__main__":  # self-check: 429 duas vezes → 200 (sem sleep real)
    import io
    os.environ["LITELLM_RETRIES"] = "2"
    os.environ["LITELLM_BACKOFF_TETO_S"] = "0"  # não pendura o teste

    class _Resp(io.BytesIO):
        def __enter__(self): return self
        def __exit__(self, *a): return False

    chamadas = {"n": 0}
    _ok = json.dumps({"choices": [{"message": {"content": "classe: luxo"}}]}).encode()

    def _fake(req, timeout=0):
        chamadas["n"] += 1
        if chamadas["n"] <= 2:  # dois 429 seguidos
            raise urllib.error.HTTPError(req.full_url, 429, "rate", {"Retry-After": "0"}, None)
        return _Resp(_ok)

    urllib.request.urlopen = _fake
    r = completar("classifique", model="motor-b")
    assert r == "classe: luxo" and chamadas["n"] == 3, (r, chamadas)

    # erro duro (401) NÃO repete: 1 chamada só, degrada pra None
    chamadas["n"] = 0
    def _hard(req, timeout=0):
        chamadas["n"] += 1
        raise urllib.error.HTTPError(req.full_url, 401, "auth", {}, None)
    urllib.request.urlopen = _hard
    assert completar("x") is None and chamadas["n"] == 1, chamadas
    print("llm_proxy OK — 429×2→200 em 3 chamadas; 401 degrada em 1 (sem repetir)")
