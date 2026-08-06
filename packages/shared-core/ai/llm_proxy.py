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
import logging
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


log = logging.getLogger(__name__)


def _base() -> str:
    return os.environ.get("LITELLM_URL", "http://127.0.0.1:4000")


def _master() -> str:
    """Chave do gateway LiteLLM — do ambiente OU do .env.

    Lia só de `os.environ` e o painel-operacoes não exporta essa variável: o gateway
    devolvia 401, o `except` de `completar()` engolia, e a função devolvia None como se
    o proxy estivesse fora do ar. Sintoma visível: a aba Auto-análise da Caixa de Ideias
    dizia "Sem achados ainda" com 428 análises e 15.875 chars de digest no banco.

    Mesmo remédio já aplicado em `visao.py` e no `llm_orquestrador` do motor-site: o
    segredo mora num arquivo gitignored, então quem só olha o ambiente não o encontra."""
    if k := os.environ.get("LITELLM_MASTER_KEY", "").strip():
        return k
    for env in ("/root/noemi-infra/.env", "/root/noemi-infra/infra/.env", "/root/sdr-motor/.env"):
        try:
            with open(env, encoding="utf-8", errors="ignore") as f:
                for l in f:
                    if l.strip().startswith("LITELLM_MASTER_KEY="):
                        return l.split("=", 1)[1].strip().strip('"').strip("'")
        except OSError:
            continue
    return ""


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


def _sem_think(txt: str) -> str:
    """Tira o bloco de raciocínio. O gateway pode rotear pra um modelo de reasoning a
    qualquer momento (é o que a cascata de fallback faz quando o primário satura), e
    esse bloco é rascunho — nunca pode vazar pra copy nem pro parser de JSON."""
    import re
    t = re.sub(r"<think>.*?</think>", "", txt or "", flags=re.S)
    return re.sub(r"<think>.*$", "", t, flags=re.S).strip()


# Piso de espaço pra resposta quando o modelo gasta o teto raciocinando (ver `_post`).
TETO_REASONING = int(os.environ.get("LITELLM_MAX_TOKENS_REASONING", "6000"))


def _uma_chamada(model: str, prompt: str, max_tokens: int, temperature: float) -> tuple[str, str]:
    """(texto_limpo, finish_reason). Deixa HTTPError/URLError subirem."""
    corpo = json.dumps({
        "model": model, "messages": [{"role": "user", "content": prompt}],
        "max_tokens": max_tokens, "temperature": temperature,
    }).encode("utf-8")
    req = urllib.request.Request(
        f"{_base()}/v1/chat/completions", data=corpo,
        headers={"Content-Type": "application/json",
                 "Authorization": f"Bearer {_master()}"})
    with urllib.request.urlopen(req, timeout=int(os.environ.get("LITELLM_TIMEOUT_S", "45"))) as r:
        d = json.loads(r.read().decode("utf-8"))
    escolha = d["choices"][0]
    bruto = escolha["message"]["content"]
    return (_sem_think(bruto) if isinstance(bruto, str) else ""), str(escolha.get("finish_reason") or "")


def _post(model: str, prompt: str, max_tokens: int, temperature: float) -> str | None:
    """Uma chamada ao proxy pro nome lógico `model`. Devolve texto (ou None se vier
    vazio). Deixa HTTPError/URLError subirem — quem chama decide repetir.

    TETO CURTO + MODELO DE RACIOCÍNIO = RESPOSTA VAZIA (2026-08-06). O nome lógico não
    diz qual modelo atende: quando o primário satura o TPD, a cascata do gateway cai em
    `gpt-oss-120b`, que emite um bloco <think> ANTES de responder. Com um teto apertado
    ele gasta o teto inteiro pensando e devolve `finish_reason='length'` com conteúdo
    vazio — e o chamador lê isso como "o proxy está fora".

    Foi o que manteve a aba Auto-análise dizendo "Sem achados ainda" com 428 análises no
    banco: o prompt curto do health-check passava (llama respondia), o prompt de 12 mil
    caracteres estourava o TPD, caía no modelo de raciocínio e voltava vazio.

    Não dá pra prever qual modelo vai atender, então a resposta é reativa: se veio vazio
    POR FALTA DE ESPAÇO, repete uma vez com espaço de sobra. O caso normal não paga nada."""
    texto, fim = _uma_chamada(model, prompt, max_tokens, temperature)
    if not texto and fim == "length" and max_tokens < TETO_REASONING:
        log.warning("%s devolveu só raciocínio em %d tokens; repetindo com %d.",
                    model, max_tokens, TETO_REASONING)
        texto, fim = _uma_chamada(model, prompt, TETO_REASONING, temperature)
    return texto or None


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
            if e.code in (401, 403):
                # config, não indisponibilidade: sem log isto vira "o proxy está fora"
                # e o chamador degrada em silêncio (foi o que escondeu a Auto-análise).
                log.error("gateway recusou a credencial (%s) — LITELLM_MASTER_KEY ausente "
                          "ou errada. O chamador vai receber None como se o proxy estivesse fora.",
                          e.code)
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

    # REASONING: teto curto → só <think> e finish_reason='length'. Tem que repetir
    # com espaço de sobra em vez de devolver None (era a Auto-análise morta em silêncio).
    chamadas.clear(); chamadas["n"] = 0
    vistos_tokens = []

    def _fake_reasoning(req, timeout=0):
        chamadas["n"] += 1
        vistos_tokens.append(json.loads(req.data)["max_tokens"])
        if chamadas["n"] == 1:   # 1ª: gastou o teto pensando, sem resposta
            return _Resp(json.dumps({"choices": [{"message": {"content": "<think>pensando"},
                                                  "finish_reason": "length"}]}).encode())
        return _Resp(json.dumps({"choices": [{"message": {"content": "<think>ok</think>{\"itens\":[]}"},
                                              "finish_reason": "stop"}]}).encode())

    urllib.request.urlopen = _fake_reasoning
    r = completar("analisa", model="analise", max_tokens=1000)
    assert r == '{"itens":[]}', r          # <think> removido, JSON preservado
    assert chamadas["n"] == 2, chamadas    # repetiu UMA vez
    assert vistos_tokens == [1000, TETO_REASONING], vistos_tokens

    # e não repete quando o teto já é grande (senão vira loop de custo)
    chamadas["n"] = 0; vistos_tokens.clear()
    assert completar("x", model="analise", max_tokens=TETO_REASONING) is None
    assert chamadas["n"] == 1, chamadas

    print("llm_proxy OK — 429×2→200; reasoning vazio→repete; 401 degrada em 1; gate 3×429+key→Anthropic; "
          "sem key→None; permitir_anthropic=False trava (Groq-only)")
