"""Transcrição de áudio — interface fixa `transcrever(audio_path) -> str|None`.

Provider por baixo (Groq Whisper) NUNCA vaza pra cima (CLAUDE.md). Cascata de
modelo (turbo → large-v3), igual à Noemi. Best-effort: sem chave ou tudo falhou
= None (o chamador degrada). httpx já é dep (fastapi/starlette), sem dep nova.

Chave: GROQ_API_KEY_RADAR > GROQ_API_KEY_TUNING > GROQ_API_KEY.
"""
from __future__ import annotations

import os
from pathlib import Path

_STT_URL = "https://api.groq.com/openai/v1/audio/transcriptions"
_MODELOS = ["whisper-large-v3-turbo", "whisper-large-v3"]  # primário → fallback


def _chave() -> str:
    for nome in ("GROQ_API_KEY_RADAR", "GROQ_API_KEY_TUNING", "GROQ_API_KEY"):
        if v := os.environ.get(nome, "").strip():
            return v
    return ""


def transcrever(audio_path: str, *, idioma: str | None = None) -> str | None:
    """Texto transcrito do áudio. `idioma` None = auto-detect (o radar ingere
    qualquer língua). None se sem chave / arquivo inválido / falhou em todos os
    modelos. Não levanta — o Radar degrada pro que der."""
    import httpx  # import tardio: módulo importável sem httpx no path de teste puro
    chave = _chave()
    p = Path(audio_path)
    if not chave or not p.exists() or p.stat().st_size == 0:
        return None
    dados = p.read_bytes()
    headers = {"Authorization": f"Bearer {chave}", "User-Agent": "noemi-radar/1.0"}
    with httpx.Client(timeout=120.0) as cli:
        for modelo in _MODELOS:
            try:
                form = {"model": modelo, "response_format": "text"}
                if idioma:
                    form["language"] = idioma
                r = cli.post(_STT_URL, headers=headers,
                             files={"file": (p.name, dados, "audio/mpeg")}, data=form)
                r.raise_for_status()
                if txt := (r.text or "").strip():
                    return txt
            except Exception:  # noqa: BLE001 — próximo modelo / degrada
                continue
    return None


if __name__ == "__main__":  # self-check: sem chave = None, sem levantar
    for k in ("GROQ_API_KEY_RADAR", "GROQ_API_KEY_TUNING", "GROQ_API_KEY"):
        os.environ.pop(k, None)
    assert transcrever("/inexistente.mp3") is None
    print("transcricao OK — sem chave/arquivo = None, sem crash")
