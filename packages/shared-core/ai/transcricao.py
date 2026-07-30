"""Transcrição de áudio — interface fixa `transcrever(audio_path) -> str|None`.

Provider por baixo (Groq Whisper) NUNCA vaza pra cima (CLAUDE.md). Best-effort:
sem chave ou tudo falhou = None (o chamador degrada). httpx já é dep, sem dep nova.

RESILIÊNCIA (o "falha às vezes" do Radar): retry de N tentativas (default 10)
tentando FORMAS DIFERENTES a cada vez — combina {modelos} × {todas as chaves Groq
disponíveis, incl. RESERVA} — porque o limite de TPM é POR CHAVE: um 429 numa chave
é contornado usando outra. Backoff exponencial + jitter, honrando Retry-After.

Chaves (ordem de preferência): GROQ_API_KEY_RADAR > _TUNING > GROQ_API_KEY > _RESERVA.
"""
from __future__ import annotations

import os
import random
import time
from pathlib import Path

_STT_URL = "https://api.groq.com/openai/v1/audio/transcriptions"
_MODELOS = ["whisper-large-v3-turbo", "whisper-large-v3"]  # primário → fallback
_TRANSITORIO = {429, 500, 502, 503, 504}  # rate-limit/sobrecarga → vale repetir


def _chaves() -> list[str]:
    """Todas as chaves Groq disponíveis, sem repetir. Rotacionar entre elas é o
    que contorna o TPM por chave (a causa do 'instabilidade' da memória)."""
    out: list[str] = []
    vistos: set[str] = set()
    for nome in ("GROQ_API_KEY_RADAR", "GROQ_API_KEY_TUNING", "GROQ_API_KEY", "GROQ_API_KEY_RESERVA"):
        if (v := os.environ.get(nome, "").strip()) and v not in vistos:
            vistos.add(v)
            out.append(v)
    return out


def _espera(tentativa_de_combo: int, retry_after: str | None) -> float:
    """Backoff: honra Retry-After do Groq; senão exponencial (1,2,4…) capado."""
    teto = float(os.environ.get("STT_BACKOFF_TETO_S", "8"))
    if retry_after:
        try:
            return min(float(retry_after), teto)
        except ValueError:
            pass
    return min(2.0 ** tentativa_de_combo, teto)


def _enviar_http(modelo: str, chave: str, nome: str, dados: bytes,
                 idioma: str | None) -> tuple[int, str, str | None]:
    """Uma chamada ao Groq STT → (status, texto, retry_after). Import tardio de httpx."""
    import httpx
    form = {"model": modelo, "response_format": "text"}
    if idioma:
        form["language"] = idioma
    with httpx.Client(timeout=float(os.environ.get("STT_TIMEOUT_S", "90"))) as cli:
        r = cli.post(_STT_URL,
                     headers={"Authorization": f"Bearer {chave}", "User-Agent": "noemi-radar/1.0"},
                     files={"file": (nome, dados, "audio/mpeg")}, data=form)
        return r.status_code, (r.text or ""), (r.headers.get("Retry-After") if r.headers else None)


def transcrever(audio_path: str, *, idioma: str | None = None,
                tentativas: int = 10, _enviar=None) -> str | None:
    """Texto transcrito. None se sem chave / arquivo inválido / todas as tentativas
    falharam. Não levanta. `tentativas` (default 10) rotaciona modelo×chave com
    backoff — resiliente a 429/blip. `_enviar` injetável pra teste."""
    chaves = _chaves()
    p = Path(audio_path)
    if not chaves or not p.exists() or p.stat().st_size == 0:
        return None
    dados = p.read_bytes()
    enviar = _enviar or _enviar_http
    combos = [(m, k) for k in chaves for m in _MODELOS]  # as "formas diferentes"
    n_combos = len(combos)
    for i in range(max(1, tentativas)):
        modelo, chave = combos[i % n_combos]
        ciclo = i // n_combos  # já passou por todas as formas → sobe o backoff
        try:
            status, texto, retry_after = enviar(modelo, chave, p.name, dados, idioma)
            if status == 200:
                if txt := texto.strip():
                    return txt
                # 200 vazio: áudio sem fala nesse modelo — tenta a próxima forma sem esperar
                continue
            if status in _TRANSITORIO:
                time.sleep(_espera(ciclo, retry_after) + random.uniform(0, 0.4))
                continue
            # erro duro (401/400/413…) nessa forma: não adianta repetir a MESMA,
            # mas outra chave/modelo pode passar (ex: 413 num modelo) → segue sem dormir
            continue
        except Exception:  # noqa: BLE001 — timeout/rede: espera leve e tenta outra forma
            time.sleep(min(2.0 ** ciclo, 8) * 0.3 + random.uniform(0, 0.3))
            continue
    return None


if __name__ == "__main__":  # self-check: sem rede (injeta _enviar), backoff zerado
    os.environ["STT_BACKOFF_TETO_S"] = "0"
    for k in ("GROQ_API_KEY_RADAR", "GROQ_API_KEY_TUNING", "GROQ_API_KEY", "GROQ_API_KEY_RESERVA"):
        os.environ.pop(k, None)
    # 1) sem chave = None, sem crash
    assert transcrever("/inexistente.mp3") is None
    # 2) dedup de chaves + rotação: 2 chaves distintas → 4 formas (2 modelos × 2 chaves)
    os.environ["GROQ_API_KEY"] = "kA"
    os.environ["GROQ_API_KEY_RESERVA"] = "kB"
    os.environ["GROQ_API_KEY_TUNING"] = "kA"  # duplicada → ignorada
    assert _chaves() == ["kA", "kB"]
    # 3) retry: falha 429 três vezes (formas diferentes), 4ª dá certo
    import tempfile
    fp = tempfile.NamedTemporaryFile(suffix=".mp3", delete=False)
    fp.write(b"x" * 100)
    fp.close()
    tentadas = []

    def fake(modelo, chave, nome, dados, idioma):
        tentadas.append((modelo, chave))
        if len(tentadas) < 4:
            return 429, "", None
        return 200, "  transcrição ok  ", None
    r = transcrever(fp.name, tentativas=10, _enviar=fake)
    assert r == "transcrição ok", r
    assert len(tentadas) == 4 and len({c for _, c in tentadas}) == 2  # rotacionou as 2 chaves
    # 4) tudo falha (429 sempre) → None após 'tentativas' tentativas
    tentadas.clear()
    assert transcrever(fp.name, tentativas=5, _enviar=lambda *a: (429, "", None)) is None
    assert len(tentadas) == 0  # (lambda não registra; conta abaixo)
    calls = {"n": 0}

    def sempre_429(*a):
        calls["n"] += 1
        return 503, "", None
    assert transcrever(fp.name, tentativas=6, _enviar=sempre_429) is None and calls["n"] == 6
    os.unlink(fp.name)
    print("transcricao OK — sem chave=None, dedup+rotação de chaves, retry 429 até acertar, esgota em N")
