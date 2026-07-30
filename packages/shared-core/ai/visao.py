"""Visão — lê o que está na TELA de um vídeo (produto, preço, UI), não o áudio.
Interface fixa `analisar_frames()`; o provider fica escondido (CLAUDE.md).

DOIS caminhos, o grátis é o padrão:
  - OCR local (Tesseract): lê o TEXTO na tela (nome do produto/preço). R$0, sem API,
    roda na CPU do servidor. É o que resolve a métrica "nome do produto sai certo".
  - Gemini (opcional, VISAO_GEMINI=1 + chave com crédito): descreve a cena inteira
    (UI/código/design) — upgrade pago, ligado só quando houver crédito.

Motivo: vídeo de produto/screen-recording tem o valor na imagem; o Whisper só ouve
a música de fundo. Isto dá OLHOS ao Radar — de graça.
Degrada honesto: nada legível → ('', 'sem_visao'). Nunca crasha.
"""
from __future__ import annotations

import base64
import json
import os
import random
import subprocess
import tempfile
import time
import urllib.request

_MODELO = os.environ.get("VISAO_MODELO", "gemini-2.0-flash")
# fallback de modelo (a "forma diferente" da visão quando o primário 429/erra)
_MODELOS_VISAO = list(dict.fromkeys([_MODELO, os.environ.get("VISAO_MODELO_FALLBACK", "gemini-1.5-flash")]))
_ENDPOINT = "https://generativelanguage.googleapis.com/v1beta/models/{m}:generateContent?key={k}"

_PROMPT_PADRAO = (
    "Frames de um vídeo curto. LEIA A TELA e extraia, priorizando TEXTO visível: "
    "1) NOME DO PRODUTO/marca/preço exatamente como escrito ('$X', nome do app/site); "
    "2) o que aparece (UI/site, código/IDE, ou cena real); 3) o gancho. "
    "Curto e específico. NÃO invente: só o que está VISÍVEL."
)


def analisar_frames(frames: list[bytes], *, prompt: str | None = None,
                    _post=None, _ocr_fn=None) -> tuple[str, str]:
    """(texto_da_tela, fonte). frames = bytes JPEG. Padrão = OCR grátis; Gemini só se
    VISAO_GEMINI=1 e houver chave. ('', 'sem_visao') se nada legível."""
    if not frames:
        return "", "sem_visao"
    # upgrade pago (opcional): Gemini descreve a cena inteira, se ligado e com crédito
    if os.environ.get("VISAO_GEMINI") == "1" and os.environ.get("GEMINI_API_KEY", "").strip():
        txt = _gemini(frames, prompt, _post)
        if txt:
            return txt, "gemini"
    # padrão GRÁTIS: OCR local do texto na tela
    ocr = (_ocr_fn or _ocr)(frames)
    return (ocr, "ocr") if ocr else ("", "sem_visao")


def _preproc_ocr(b: bytes) -> bytes:
    """Pré-processa o frame pro OCR: escala de cinza + upscale 2x (lanczos) +
    autocontraste → Tesseract lê texto pequeno/overlay muito melhor. Fallback pro
    bytes cru se PIL não estiver disponível (nunca quebra)."""
    try:
        import io

        from PIL import Image, ImageOps
        im = Image.open(io.BytesIO(b)).convert("L")
        im = im.resize((im.width * 2, im.height * 2), Image.LANCZOS)
        im = ImageOps.autocontrast(im, cutoff=2)
        buf = io.BytesIO()
        im.save(buf, "PNG")
        return buf.getvalue()
    except Exception:  # noqa: BLE001 — sem PIL/erro → OCR no frame original
        return b


def _ocr(frames: list[bytes]) -> str:
    """Tesseract em cada frame → texto na tela, dedup entre frames. '' se falhar."""
    import hashlib
    vistos: set[str] = set()
    unicos: list[str] = []
    frames_vistos: set[str] = set()  # dedup de frame idêntico (reel repete) → menos OCR
    for b in frames[:8]:
        h = hashlib.md5(b).hexdigest()
        if h in frames_vistos:
            continue
        frames_vistos.add(h)
        caminho = None
        try:
            with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
                f.write(_preproc_ocr(b))  # upscale+cinza+contraste → Tesseract lê texto pequeno melhor
                caminho = f.name
            out = subprocess.run(["tesseract", caminho, "stdout", "-l", "por+eng"],
                                 capture_output=True, text=True, timeout=30).stdout
        except Exception:  # noqa: BLE001 — um frame falha, os outros seguem
            continue
        finally:
            if caminho:
                try:
                    os.unlink(caminho)
                except OSError:
                    pass
        for linha in out.splitlines():
            t = " ".join(linha.split())
            if len(t) >= 3 and t.lower() not in vistos:  # ignora ruído de 1-2 chars
                vistos.add(t.lower())
                unicos.append(t)
    return " | ".join(unicos)[:2000]


def _gemini(frames: list[bytes], prompt: str | None, _post) -> str:
    """Chamada Gemini (visão rica). '' em qualquer falha (sem crédito/chave/erro)."""
    key = os.environ.get("GEMINI_API_KEY", "").strip()
    partes: list[dict] = [{"text": prompt or _PROMPT_PADRAO}]
    for b in frames[:8]:
        partes.append({"inline_data": {"mime_type": "image/jpeg",
                                       "data": base64.b64encode(b).decode()}})
    corpo = json.dumps({"contents": [{"parts": partes}],
                        "generationConfig": {"temperature": 0.2, "maxOutputTokens": 700}}).encode()
    poster = _post or _post_http
    tentativas = int(os.environ.get("VISAO_TENTATIVAS", "4"))  # retry: formas diferentes
    for i in range(max(1, tentativas)):
        modelo = _MODELOS_VISAO[i % len(_MODELOS_VISAO)]
        try:
            if txt := (poster(_ENDPOINT.format(m=modelo, k=key), corpo) or "").strip():
                return txt
            # 200 vazio → tenta a próxima forma (outro modelo) sem esperar
        except Exception:  # noqa: BLE001 — 429/sem crédito/timeout → backoff leve + próxima forma
            time.sleep(min(2.0 ** (i // len(_MODELOS_VISAO)), 6) * 0.3 + random.uniform(0, 0.3))
    return ""  # esgotou → cai no OCR grátis


def _post_http(url: str, corpo: bytes) -> str:
    req = urllib.request.Request(url, data=corpo, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=int(os.environ.get("VISAO_TIMEOUT_S", "60"))) as r:
        d = json.loads(r.read().decode("utf-8"))
    return d["candidates"][0]["content"]["parts"][0]["text"]


if __name__ == "__main__":  # self-check: OCR grátis por padrão; honesto sem frames
    os.environ.pop("VISAO_GEMINI", None)
    assert analisar_frames([]) == ("", "sem_visao")
    # OCR mockado (não depende do tesseract no self-check)
    t, fonte = analisar_frames([b"jpg"], _ocr_fn=lambda fr: "GALLERY LED FRAME $18")
    assert fonte == "ocr" and "GALLERY LED FRAME" in t, (t, fonte)
    assert analisar_frames([b"jpg"], _ocr_fn=lambda fr: "") == ("", "sem_visao")
    # retry do Gemini: 429 duas vezes (formas diferentes) → 3ª acerta (sem sleep real)
    os.environ["VISAO_GEMINI"] = "1"
    os.environ["GEMINI_API_KEY"] = "fake"
    os.environ["VISAO_TENTATIVAS"] = "5"
    chamadas = {"n": 0}

    def flaky_post(url, corpo):
        chamadas["n"] += 1
        if chamadas["n"] < 3:
            raise RuntimeError("429")
        return "PRODUTO X · R$ 18"
    txt, fonte = analisar_frames([b"jpg"], _post=flaky_post)
    assert fonte == "gemini" and "PRODUTO X" in txt and chamadas["n"] == 3, (txt, fonte, chamadas)
    for k in ("VISAO_GEMINI", "GEMINI_API_KEY", "VISAO_TENTATIVAS"):
        os.environ.pop(k, None)
    print("visao OK — OCR padrão, honesto sem frames, retry Gemini (formas diferentes) até acertar")
    # Gemini só quando ligado
    os.environ["VISAO_GEMINI"] = "1"; os.environ["GEMINI_API_KEY"] = "fake"
    t2, f2 = analisar_frames([b"jpg"], _post=lambda u, c: "cena: site de luxo", _ocr_fn=lambda fr: "x")
    assert f2 == "gemini" and "luxo" in t2, (t2, f2)
    print("visao OK — OCR grátis por padrão, Gemini opcional, honesto sem frames")
