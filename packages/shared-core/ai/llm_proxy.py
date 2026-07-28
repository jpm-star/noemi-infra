"""Cliente da camada única de LLM (LiteLLM Proxy) — interface fixa.

Roteia por NOME LÓGICO (analise/motor-b — nunca provider cru pra cima) pro proxy
OpenAI-compatível, que faz fallback entre os cloud + registra custo/latência/
modelo/erro no dashboard. Ollama fica FORA do proxy (fallback offline em
local_llm, loopback seguro). urllib stdlib, sem dep nova. Best-effort: proxy
fora → None (chamador cai no local_llm/regras).

Cascata de disponibilidade:
  Groq primário → (retry 429/5xx) → groq-reserva (fallback do proxy) →
  Anthropic claude-haiku (SÓ após gate de N 429 seguidos, cross-provider) →
  None → chamador degrada pro local_llm (Ollama) / regras.
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

# Gate cross-provider: só cai pra Anthropic depois de N 429 SEGUIDOS na mesma
# chamada (com LITELLM_RETRIES=2 → as 3 tentativas do loop). É o que separa
# "Groq realmente rate-limited agora" de "um 429 isolado que o retry absorve" —
# evita queimar crédito Anthropic num blip. Inerte enquanto ANTHROPIC_API_KEY
# estiver vazia (a chamada ao proxy volta erro → None → degrada pro local_llm).
_GATE_429 = int(os.environ.get("ANTHROPIC_GATE_429", "3"))


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


def _post(model: str, prompt: str, max_tokens: int, temperature: float) -> str | None:
    """Uma chamada ao proxy pro nome lógico `model`. Devolve texto (ou None se
    vier vazio). Deixa HTTPError/URLError subirem — quem chama decide repetir."""
    corpo = json.dumps({
        "model": model, "messages": [{"role": "user", "content": prompt}],
        "max_tokens": max_tokens, "temperature": temperature,
    }).encode("utf-8")
    req = urllib.request.Request(
        f"{_base()}/v1/chat/completions", data=corpo,
        headers={"Content-Type": "application/json",
                 "Authorization": f"Bearer {os.environ.get('LITELLM_MASTER_KEY', '')}"})
    with urllib.request.urlopen(req, timeout=int(os.environ.get("LITELLM_TIMEOUT_S", "45"))) as r:
        d = json.loads(r.read().decode("utf-8"))
    texto = d["choices"][0]["message"]["content"]
    return texto if isinstance(texto, str) and texto.strip() else None


def completar(prompt: str, *, model: str = "analise", max_tokens: int = 400,
              temperature: float = 0, permitir_anthropic: bool = True) -> str | None:
    """Texto do proxy pro prompt (chat/completions). None se o proxy estiver
    fora/erro/timeout. `model` é o nome lógico do config (analise/motor-b).
    Repete em 429/5xx (respeitando Retry-After) até LITELLM_RETRIES; se forem
    ≥ _GATE_429 429s seguidos e houver ANTHROPIC_API_KEY, tenta claude-haiku
    uma vez antes de devolver None — o chamador só degrada quando o cloud
    (Groq E Anthropic) realmente esgotou."""
    retries = int(os.environ.get("LITELLM_RETRIES", "2"))
    n_429 = 0
    for tentativa in range(retries + 1):
        try:
            return _post(model, prompt, max_tokens, temperature)
        except urllib.error.HTTPError as e:
            if e.code == 429:
                n_429 += 1
            if e.code in _TRANSITORIO and tentativa < retries:
                time.sleep(_espera(e, tentativa))
                continue
            break  # erro duro (401/400) ou retries esgotados → sai do loop
        except (urllib.error.URLError, TimeoutError, ValueError, KeyError, IndexError, OSError):
            return None
    # Gate cross-provider: Groq esgotou por 429 seguidos → última cartada Anthropic.
    # permitir_anthropic=False TRAVA isso (caminho cliente do Insight Engine: Groq-only
    # por construção, pra não custar token Anthropic por cliente e matar a margem do tier 1).
    if permitir_anthropic and n_429 >= _GATE_429 and os.environ.get("ANTHROPIC_API_KEY"):
        try:
            return _post("fallback-anthropic", prompt, max_tokens, temperature)
        except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError,
                ValueError, KeyError, IndexError, OSError):
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
    os.environ.pop("ANTHROPIC_API_KEY", None)  # sem key: 2×429 não abre o gate
    r = completar("classifique", model="motor-b")
    assert r == "classe: luxo" and chamadas["n"] == 3, (r, chamadas)

    # erro duro (401) NÃO repete: 1 chamada só, degrada pra None
    chamadas["n"] = 0
    def _hard(req, timeout=0):
        chamadas["n"] += 1
        raise urllib.error.HTTPError(req.full_url, 401, "auth", {}, None)
    urllib.request.urlopen = _hard
    assert completar("x") is None and chamadas["n"] == 1, chamadas

    # GATE: 3×429 seguidos + ANTHROPIC_API_KEY → 4ª chamada cai no fallback-anthropic
    chamadas["n"] = 0
    os.environ["ANTHROPIC_API_KEY"] = "sk-teste"
    def _429_ate_anthropic(req, timeout=0):
        chamadas["n"] += 1
        if chamadas["n"] <= 3:  # Groq: 3 tentativas, todas 429 (esgota o gate)
            raise urllib.error.HTTPError(req.full_url, 429, "rate", {"Retry-After": "0"}, None)
        assert b"fallback-anthropic" in req.data, "4ª chamada deve ser pro modelo Anthropic"
        return _Resp(_ok)
    urllib.request.urlopen = _429_ate_anthropic
    r = completar("classifique", model="motor-b")
    assert r == "classe: luxo" and chamadas["n"] == 4, (r, chamadas)

    # GATE fechado sem key: 3×429 + sem ANTHROPIC_API_KEY → None (não tenta Anthropic)
    chamadas["n"] = 0
    os.environ.pop("ANTHROPIC_API_KEY", None)
    def _so_429(req, timeout=0):
        chamadas["n"] += 1
        raise urllib.error.HTTPError(req.full_url, 429, "rate", {"Retry-After": "0"}, None)
    urllib.request.urlopen = _so_429
    assert completar("x", model="motor-b") is None and chamadas["n"] == 3, chamadas

    # TRAVA-CUSTO: mesmo com key + 3×429, permitir_anthropic=False NÃO tenta Anthropic
    chamadas["n"] = 0
    os.environ["ANTHROPIC_API_KEY"] = "sk-teste"
    urllib.request.urlopen = _so_429  # sempre 429
    _r = completar("x", model="motor-b", permitir_anthropic=False)
    assert _r is None and chamadas["n"] == 3, chamadas  # 3 tentativas Groq, ZERO Anthropic
    os.environ.pop("ANTHROPIC_API_KEY", None)

    print("llm_proxy OK — 429×2→200; 401 degrada em 1; gate 3×429+key→Anthropic; "
          "sem key→None; permitir_anthropic=False trava (Groq-only)")
