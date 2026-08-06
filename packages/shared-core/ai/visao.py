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
import logging
import os
import random
import subprocess
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

log = logging.getLogger(__name__)

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
                    _post=None, _ocr_fn=None, _groq_fn=None) -> tuple[str, str]:
    """(texto_da_tela, fonte). frames = bytes JPEG.

    Cascata (do que ENTENDE pro que só LÊ), toda degradando sem crashar:
      1. Groq multimodal — GRÁTIS na key que já existe, descreve a CENA (não só o texto).
      2. Gemini — só se VISAO_GEMINI=1 e a chave tiver quota (hoje o projeto está sem).
      3. OCR local (Tesseract) — grátis, lê o TEXTO na imagem.
    ('', 'sem_visao') se nada legível."""
    if not frames:
        return "", "sem_visao"
    # 1) Groq multimodal: entende a cena de graça (default ON — a key já é a da operação)
    # o gateway serve como credencial: quem tem a master key não precisa da GROQ_API_KEY
    if os.environ.get("VISAO_GROQ", "1") == "1" and (
            os.environ.get("GROQ_API_KEY", "").strip() or _master()):
        txt = (_groq_fn or _groq)(frames, prompt)
        if txt:
            return txt, "groq"
    # 2) upgrade pago (opcional): Gemini, se ligado e com crédito
    if os.environ.get("VISAO_GEMINI") == "1" and os.environ.get("GEMINI_API_KEY", "").strip():
        txt = _gemini(frames, prompt, _post)
        if txt:
            return txt, "gemini"
    # 3) padrão GRÁTIS: OCR local do texto na tela
    ocr = (_ocr_fn or _ocr)(frames)
    return (ocr, "ocr") if ocr else ("", "sem_visao")


_GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
_GROQ_MODELO = os.environ.get("VISAO_GROQ_MODELO", "qwen/qwen3.6-27b")
_GATEWAY_URL = os.environ.get("LITELLM_BASE", "http://127.0.0.1:4000") + "/v1/chat/completions"


def _master() -> str:
    """Chave do gateway LiteLLM. Procura no .env porque quem chama a visão (painel,
    motor-site, Radar) não exporta essa variável — e sem ela o gateway devolve 401."""
    if k := os.environ.get("LITELLM_MASTER_KEY", "").strip():
        return k
    for env in ("/root/noemi-infra/.env", "/root/noemi-infra/infra/.env", "/root/sdr-motor/.env"):
        p = Path(env)
        if not p.is_file():
            continue
        for l in p.read_text(errors="ignore").splitlines():
            if l.strip().startswith("LITELLM_MASTER_KEY="):
                return l.split("=", 1)[1].strip().strip('"').strip("'")
    return ""


def _groq(frames: list[bytes], prompt: str | None) -> str:
    """Visão multimodal via Groq (grátis na key da operação). '' em qualquer falha.

    Cuidados aprendidos na marra: (a) o WAF da Cloudflare bloqueia o UA padrão do
    urllib (403/1010) — manda UA explícito; (b) o modelo emite bloco <think>, que é
    raciocínio e NÃO pode vazar pra copy do site."""
    # GATEWAY PRIMEIRO (2026-08-06). O provider cru usa UMA chave, e o TPM de 8000
    # estoura já na segunda imagem de uma mesma rodada — o 429 caía em silêncio e a
    # visão virava 'sem_visao'. O gateway roda o mesmo modelo sobre as 10 chaves do
    # pool em round-robin. Sem gateway no ar, segue no provider cru (melhor que nada).
    url, key, modelo = _GROQ_URL, os.environ.get("GROQ_API_KEY", "").strip(), _GROQ_MODELO
    if mk := _master():
        url, key, modelo = _GATEWAY_URL, mk, "visao"
    if not key:
        return ""
    conteudo: list[dict] = [{"type": "text", "text": prompt or _PROMPT_PADRAO}]
    for b in frames[:4]:  # visão é cara em token: 4 imagens já dão o contexto
        conteudo.append({"type": "image_url", "image_url":
                         {"url": "data:image/jpeg;base64," + base64.b64encode(b).decode()}})
    # 6000 e não 900: ver o bloco RACIOCÍNIO abaixo. O teto antigo cabia no <think> e
    # não na resposta — e um teto que corta a resposta é indistinguível de "sem visão".
    base = {"model": modelo, "temperature": 0.2, "max_tokens": 6000,
            "messages": [{"role": "user", "content": conteudo}]}

    def _pedir(extra: dict) -> str:
        req = urllib.request.Request(url, data=json.dumps({**base, **extra}).encode(),
                                     headers={"Authorization": f"Bearer {key}",
                                              "Content-Type": "application/json",
                                              # UA explícito: sem isso o WAF devolve 403/1010
                                              "User-Agent": "curl/8.5.0"})
        with urllib.request.urlopen(req, timeout=int(os.environ.get("VISAO_TIMEOUT_S", "60"))) as r:
            return json.loads(r.read().decode("utf-8"))["choices"][0]["message"]["content"] or ""

    # RACIOCÍNIO (2026-08-06). O qwen3.6 é o ÚNICO multimodal do Groq e é modelo de
    # reasoning: emite um bloco <think> antes de responder. Com o teto antigo de 900
    # tokens ele gastava os 900 pensando, e `_sem_think` (corretamente) devolvia "" pro
    # think truncado. A visão inteira ficou muda em produção — sem erro, sem log, caindo
    # pro OCR e virando 'sem_visao'.
    # DOIS cintos, porque cada um cobre um caminho:
    #   `reasoning_effort=none` corta o think na origem (~20 tokens) — vale no provider
    #      cru, mas o gateway o descarta (`drop_params: true` do router), então não dá
    #      pra depender dele;
    #   `max_tokens=6000` dá espaço pro think TERMINAR e a resposta sair depois — é o
    #      que faz funcionar pelo gateway. Medido nos dois caminhos.
    # `extra_body` não é usado de propósito: só o gateway o entende, e o provider cru
    # rejeitaria — um corpo que serve aos dois vale mais que a economia de tokens.
    try:
        txt = _pedir({"reasoning_effort": "none"})
    except urllib.error.HTTPError as e:
        if e.code != 400:  # 429/500/... → próximo nível da cascata
            return ""
        try:  # provider que nem conhece o parâmetro: repete sem ele
            txt = _pedir({})
        except Exception:  # noqa: BLE001
            return ""
    except Exception:  # noqa: BLE001 — timeout/rede → cai pro próximo nível
        return ""
    limpo = _sem_think(txt)
    if txt and not limpo:  # o sintoma que ficou invisível por meses: nunca mais em silêncio
        log.warning("visão devolveu só raciocínio (%d chars) e nada de resposta — "
                    "modelo %s ignorou reasoning_effort?", len(txt), _GROQ_MODELO)
    return limpo


def _sem_think(txt: str) -> str:
    """Remove o raciocínio <think>…</think> (e um <think> sem fechamento)."""
    import re
    t = re.sub(r"<think>.*?</think>", "", txt, flags=re.S)
    t = re.sub(r"<think>.*$", "", t, flags=re.S)  # truncado por max_tokens
    return t.strip()


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


if __name__ == "__main__":  # self-check: cascata Groq -> Gemini -> OCR; honesto sem frames
    os.environ.pop("VISAO_GEMINI", None)
    os.environ["VISAO_GROQ"] = "0"  # nos testes de baixo, Groq desligado (sem rede)
    assert analisar_frames([]) == ("", "sem_visao")
    # <think> do modelo NUNCA vaza pra copy
    assert _sem_think("<think>raciocinio interno</think>Sala de musculação.") == "Sala de musculação."
    assert _sem_think("Academia.<think>truncado sem fechar") == "Academia."
    # nível 1: Groq entende a cena e VENCE o OCR quando responde
    os.environ["VISAO_GROQ"] = "1"; os.environ["GROQ_API_KEY"] = "fake"
    t, f = analisar_frames([b"jpg"], _groq_fn=lambda fr, p: "Sala de musculação com 3 racks",
                           _ocr_fn=lambda fr: "TEXTO NA PLACA")
    assert f == "groq" and "racks" in t, (t, f)
    # Groq falhou (429/rede) -> degrada pro OCR sem crashar
    t, f = analisar_frames([b"jpg"], _groq_fn=lambda fr, p: "", _ocr_fn=lambda fr: "PLANO R$ 89")
    assert f == "ocr" and "89" in t, (t, f)
    os.environ["VISAO_GROQ"] = "0"
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
