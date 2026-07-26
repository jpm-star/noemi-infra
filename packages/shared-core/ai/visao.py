"""Visão — analisa FRAMES de um vídeo (o que está na TELA: produto, UI, código,
texto), não o áudio. Interface fixa `analisar_frames()` — o provider (Gemini)
fica escondido aqui (CLAUDE.md: nada de nome de provider em cima; troca por baixo).

Motivo de existir: vídeo de screen-recording/produto tem o valor 100% na imagem;
o Whisper só ouve a música de fundo. Isto dá OLHOS ao Radar.

Degrada honesto: sem GEMINI_API_KEY ou API fora → ('', 'sem_visao'). Nunca crasha.
"""
from __future__ import annotations

import base64
import json
import os
import urllib.error
import urllib.request

_MODELO = os.environ.get("VISAO_MODELO", "gemini-2.0-flash")
_ENDPOINT = "https://generativelanguage.googleapis.com/v1beta/models/{m}:generateContent?key={k}"

_PROMPT_PADRAO = (
    "Estes são frames de um vídeo curto (reel/screen-recording). LEIA A TELA e "
    "descreva o que dá pra EXTRAIR de concreto, priorizando TEXTO visível:\n"
    "1) NOME DO PRODUTO/marca/oferta exatamente como aparece escrito na tela "
    "(preço, '$X', nome do app/site) — se houver, cite literal.\n"
    "2) O que está na tela: UI/site (estilo, tipografia, seções), código/IDE "
    "(framework visível), ou cena real.\n"
    "3) O gancho/mensagem principal do vídeo.\n"
    "Seja específico e curto. Se um item não aparece, diga que não aparece. "
    "NÃO invente: só o que está VISÍVEL nos frames."
)


def analisar_frames(frames: list[bytes], *, prompt: str | None = None,
                    _post=None) -> tuple[str, str]:
    """(texto_da_visao, fonte). frames = lista de bytes JPEG/PNG. `_post` injetável
    (teste). ('', 'sem_visao') se não houver chave/frames ou a API falhar."""
    key = os.environ.get("GEMINI_API_KEY", "").strip()
    if not key or not frames:
        return "", "sem_visao"
    partes: list[dict] = [{"text": prompt or _PROMPT_PADRAO}]
    for b in frames[:8]:  # teto de 8 frames (custo/payload)
        partes.append({"inline_data": {"mime_type": "image/jpeg",
                                       "data": base64.b64encode(b).decode()}})
    corpo = json.dumps({"contents": [{"parts": partes}],
                        "generationConfig": {"temperature": 0.2, "maxOutputTokens": 700}}).encode()
    url = _ENDPOINT.format(m=_MODELO, k=key)
    try:
        texto = (_post or _post_http)(url, corpo)
    except Exception:  # noqa: BLE001 — visão é best-effort; áudio+legenda seguem
        return "", "sem_visao"
    return (texto.strip(), "gemini") if texto and texto.strip() else ("", "sem_visao")


def _post_http(url: str, corpo: bytes) -> str:
    req = urllib.request.Request(url, data=corpo, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=int(os.environ.get("VISAO_TIMEOUT_S", "60"))) as r:
        d = json.loads(r.read().decode("utf-8"))
    return d["candidates"][0]["content"]["parts"][0]["text"]


if __name__ == "__main__":  # self-check: honesto sem key; parseia resposta mock
    os.environ.pop("GEMINI_API_KEY", None)
    assert analisar_frames([b"x"]) == ("", "sem_visao")
    os.environ["GEMINI_API_KEY"] = "fake"
    assert analisar_frames([]) == ("", "sem_visao")  # sem frames
    fake = lambda u, c: json.dumps and "Produto: MOLDURA LED $18. Site de luxo, tipografia serifada."
    t, fonte = analisar_frames([b"jpegbytes"], _post=lambda u, c: "Produto: MOLDURA LED $18 na tela.")
    assert fonte == "gemini" and "MOLDURA LED" in t, (t, fonte)
    assert analisar_frames([b"x"], _post=lambda u, c: (_ for _ in ()).throw(RuntimeError("api fora")))[1] == "sem_visao"
    print("visao OK — honesto sem key/frames, parseia gemini, degrada em erro")
