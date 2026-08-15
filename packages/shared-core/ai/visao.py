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
import re
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
                    _post=None, _ocr_fn=None, _groq_fn=None,
                    _diag: dict | None = None) -> tuple[str, str]:
    """(texto_da_tela, fonte). frames = bytes JPEG.

    Cascata (do que ENTENDE pro que só LÊ), toda degradando sem crashar:
      1. Groq multimodal — GRÁTIS na key que já existe, descreve a CENA (não só o texto).
      2. Gemini — só se VISAO_GEMINI=1 e a chave tiver quota (hoje o projeto está sem).
      3. OCR local (Tesseract) — grátis, lê o TEXTO na imagem.
    ('', 'sem_visao') se nada legível.

    `_diag`: dict opcional que a chamada preenche com por que a visão falhou —
    {'erro': 'permanente'|'transitorio'|'', 'detalhe': str, 'espera_s': float}.
    Quem chama usa isso pra decidir se ESPERAR faz sentido (só 'transitorio' faz)."""
    if _diag is not None:
        _diag.clear()
    if not frames:
        return "", "sem_visao"
    # 1) Groq multimodal: entende a cena de graça (default ON — a key já é a da operação)
    # o gateway serve como credencial: quem tem a master key não precisa da GROQ_API_KEY
    if os.environ.get("VISAO_GROQ", "1") == "1" and (
            os.environ.get("GROQ_API_KEY", "").strip() or _master()):
        f = _groq_fn or _groq
        txt = f(frames, prompt, _diag) if f is _groq else f(frames, prompt)
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

# ORÇAMENTO DE TOKENS POR REQUISIÇÃO (medido no gateway em 2026-08-07, não estimado).
#
# O erro que matou a visão era `429 Request too large ... Limit 8000, Requested 8422`.
# Parecia falta de compressão da imagem. NÃO ERA — medido:
#   imagem de 59.690B  -> Requested 8422      imagem de 4.424B -> Requested 8422
#   imagem de 213.814B -> prompt_tokens 1814  recomprimida p/ 68.578B -> prompt_tokens 1814
# O tamanho em bytes não entra na conta. Recomprimir não muda um único token, e também
# não muda a latência (4,5s contra 4,6s na mesma foto). Por isso não há recompressão aqui.
#
# A conta real é:  Requested = prompt_tokens + max_tokens.
# Cada imagem custa ~1.800 tokens reais (~2.400 na estimativa que o Groq usa pro teto),
# fixos, seja ela 170x256 ou 638x960. Com `max_tokens=6000` sobravam 2.000 pro conteúdo:
# UMA imagem já estourava o teto de 8.000, sempre, pra qualquer foto. Era um teto
# permanente — e o chamador dormia 60s esperando uma janela de TPM que nunca era o problema.
_TETO_TPM = int(os.environ.get("VISAO_TETO_TPM", "8000"))
_CUSTO_IMAGEM = int(os.environ.get("VISAO_CUSTO_IMAGEM", "2500"))  # estimativa do Groq, com folga
_RESERVA_TEXTO = 400        # o prompt de texto mais longo em uso (o juiz do acervo) dá ~200
_RESPOSTA_MIN = 2000        # abaixo disto o <think> come a resposta inteira (medido: 1.200 -> "")
# 4 imagens devolvem `400 Too many images` — outro erro permanente que dormir não conserta.
_MAX_IMAGENS = int(os.environ.get("VISAO_MAX_IMAGENS", "2"))


def _orcamento(n_frames: int) -> tuple[int, int]:
    """(quantas imagens mandar, max_tokens) que CABEM no teto por requisição.

    Menos imagem = mais espaço pra resposta. Se nem 1 imagem couber com resposta
    mínima, ainda manda 1: o erro honesto vale mais que a chamada não feita."""
    n = max(1, min(n_frames, _MAX_IMAGENS))
    while n > 1 and _TETO_TPM - n * _CUSTO_IMAGEM - _RESERVA_TEXTO < _RESPOSTA_MIN:
        n -= 1
    return n, max(_RESPOSTA_MIN, min(6000, _TETO_TPM - n * _CUSTO_IMAGEM - _RESERVA_TEXTO))


_RE_ESPERA = re.compile(r"try again in ([\d.]+)s", re.I)


def _classifica(code: int, corpo: str) -> tuple[str, float]:
    """('permanente'|'transitorio', segundos de espera). O coração do conserto.

    PERMANENTE = repetir a MESMA requisição dá o mesmo erro pra sempre (payload grande
    demais, imagens demais, parâmetro que o provider não conhece). Esperar não muda o
    tamanho do que se mandou: tem que mandar MENOS, ou desistir e seguir.
    TRANSITORIO = a janela de TPM/RPM encheu; em segundos ela abre sozinha. Só aqui
    dormir é o recurso certo — e pelo tempo que a própria API informa, não por 60s de chute.

    Atenção: 'Request too large' chega com HTTP 429, o mesmo código do rate limit de
    verdade. É por isso que a mensagem é lida ANTES do código."""
    c = corpo.lower()
    if "too large" in c or "too many images" in c or code == 413:
        return "permanente", 0.0
    if code == 429:
        m = _RE_ESPERA.search(corpo)
        return "transitorio", min(float(m.group(1)) + 1.0 if m else 20.0, 60.0)
    if code in (400, 401, 403, 404, 422):
        return "permanente", 0.0
    return "transitorio", 5.0   # 5xx/rede: a próxima chamada pode dar certo


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


def _groq(frames: list[bytes], prompt: str | None, diag: dict | None = None) -> str:
    """Visão multimodal via Groq (grátis na key da operação). '' em qualquer falha.

    Cuidados aprendidos na marra: (a) o WAF da Cloudflare bloqueia o UA padrão do
    urllib (403/1010) — manda UA explícito; (b) o modelo emite bloco <think>, que é
    raciocínio e NÃO pode vazar pra copy do site."""
    # GATEWAY PRIMEIRO (2026-08-06). O provider cru usa UMA chave, e o TPM de 8000
    # estoura já na segunda imagem de uma mesma rodada — o 429 caía em silêncio e a
    # visão virava 'sem_visao'. O gateway roda o mesmo modelo sobre as 10 chaves do
    # pool em round-robin. Sem gateway no ar, segue no provider cru (melhor que nada).
    d = diag if diag is not None else {}
    url, key, modelo = _GROQ_URL, os.environ.get("GROQ_API_KEY", "").strip(), _GROQ_MODELO
    if mk := _master():
        url, key, modelo = _GATEWAY_URL, mk, "visao"
    if not key:
        # sem credencial nenhuma: repetir daqui a 1 minuto dá exatamente o mesmo nada
        d.update(erro="permanente", detalhe="sem chave de visão", espera_s=0.0)
        return ""

    def _pedir(n: int, max_tokens: int, extra: dict) -> str:
        conteudo: list[dict] = [{"type": "text", "text": prompt or _PROMPT_PADRAO}]
        for b in frames[:n]:
            conteudo.append({"type": "image_url", "image_url":
                             {"url": "data:image/jpeg;base64," + base64.b64encode(b).decode()}})
        corpo = {"model": modelo, "temperature": 0.2, "max_tokens": max_tokens,
                 "messages": [{"role": "user", "content": conteudo}], **extra}
        req = urllib.request.Request(url, data=json.dumps(corpo).encode(),
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
    #   um `max_tokens` FOLGADO dá espaço pro think terminar e a resposta sair depois —
    #      é o que faz funcionar pelo gateway. Mas folgado não é infinito: em 2026-08-07 o
    #      valor era 6000 fixo, e 6000 + o custo da imagem ESTOURA o teto de 8.000 por
    #      requisição, derrubando toda chamada com `429 Request too large`. Agora quem
    #      define o teto é `_orcamento()`, que desconta o que as imagens já custam.
    # `extra_body` não é usado de propósito: só o gateway o entende, e o provider cru
    # rejeitaria — um corpo que serve aos dois vale mais que a economia de tokens.
    n, teto = _orcamento(len(frames))
    teto_um = _orcamento(1)[1]
    # Os planos vão do maior pro menor, e SÓ erro permanente faz descer de plano — porque
    # erro permanente é o único que muda de resposta quando se manda menos. MENOS IMAGEM É
    # MAIS RESPOSTA: com 1 imagem sobram ~5.100 tokens pro modelo pensar e responder,
    # contra ~2.600 com 2 — e o <think> do qwen3.6 estoura os 2.600 com frequência.
    planos = [(n, teto, {"reasoning_effort": "none"})]
    if n > 1:
        planos.append((1, teto_um, {"reasoning_effort": "none"}))
    planos.append((1, teto_um, {}))   # provider que não conhece o parâmetro (400)
    for n_i, teto_i, extra in planos:
        try:
            bruto = _pedir(n_i, teto_i, extra)
        except urllib.error.HTTPError as e:
            corpo = e.read().decode(errors="ignore")[:400]
            classe, espera = _classifica(e.code, corpo)
            d.update(erro=classe, detalhe=f"HTTP {e.code}: {corpo[:160]}", espera_s=espera)
            if classe == "transitorio":
                # a janela abre sozinha, mas quem espera é quem chamou (sabe se vale a pena)
                log.warning("visão em rate limit (espera sugerida %.0fs): %s", espera, corpo[:120])
                return ""
            log.warning("visão recusou o pedido (permanente, tentando plano menor): %s", corpo[:120])
        except Exception as e:  # noqa: BLE001 — timeout/rede → transitório, cai pro próximo nível
            d.update(erro="transitorio", detalhe=f"{type(e).__name__}: {e}", espera_s=5.0)
            return ""
        else:
            txt = _sem_think(bruto)
            if txt:
                d.update(erro="", detalhe="", espera_s=0.0)
                return txt
            # 200 OK e ainda assim vazio: o <think> comeu o teto de resposta inteiro. Isso é
            # PERMANENTE pra este plano (repetir igual dá igual) e some no plano seguinte,
            # que manda menos imagem e sobra mais espaço. Nunca mais em silêncio.
            log.warning("visão devolveu só raciocínio (%d chars) e nada de resposta — "
                        "%d imagem(ns) com teto de %d tokens", len(bruto), n_i, teto_i)
            d.update(erro="permanente", detalhe="só raciocínio, resposta truncada", espera_s=0.0)
    return ""   # todos os planos falharam: nada a esperar, o diag já diz o porquê


def _sem_think(txt: str) -> str:
    """Remove o raciocínio <think>…</think> (e um <think> sem fechamento)."""
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


# --- vídeo NATIVO ----------------------------------------------------------
# `analisar_frames` vê ESTADOS: o que estava na tela naquele instante. Vídeo nativo
# vê MOVIMENTO — velocidade de transição, ordem dos eventos, easing, quanto tempo o
# olho fica em cada coisa. Pra "o que este site faz de motion" ou "por que este reel
# prende", a diferença não é de grau: frame nenhum mostra timing.
# Acima de 20 MB não cabe embutido no JSON, então sobe pela File API primeiro.
# `gemini-flash-latest`, não um número fixo: contas criadas depois de certa data
# recebem 404 "no longer available to new users" em modelos antigos, e o erro NÃO
# se parece com erro de modelo — parece falta de acesso. O alias acompanha o flash
# atual e imuniza contra essa classe inteira de quebra silenciosa.
_MODELO_VIDEO = os.environ.get("VISAO_MODELO_VIDEO", "gemini-flash-latest")
_UPLOAD = "https://generativelanguage.googleapis.com/upload/v1beta/files?key={k}"
_ARQUIVO = "https://generativelanguage.googleapis.com/v1beta/{n}?key={k}"

_PROMPT_VIDEO = (
    "Assista ao vídeo inteiro e descreva o que ACONTECE AO LONGO DO TEMPO, não só o que "
    "aparece. Cite momentos em segundos. Priorize: 1) transições e animações (o QUE se move, "
    "COMO e em quanto tempo); 2) ordem dos acontecimentos; 3) texto legível na tela; 4) o "
    "gancho — o que prende a atenção e por quê. Específico, sem inventar o que não está lá."
)


def _upload_arquivo(caminho: Path, mime: str, key: str, timeout: int) -> str | None:
    """Sobe pela File API (resumable, 2 passos) e devolve o URI. None se falhar."""
    tam = caminho.stat().st_size
    req = urllib.request.Request(
        _UPLOAD.format(k=key), data=json.dumps({"file": {"display_name": caminho.name}}).encode(),
        headers={"X-Goog-Upload-Protocol": "resumable", "X-Goog-Upload-Command": "start",
                 "X-Goog-Upload-Header-Content-Length": str(tam),
                 "X-Goog-Upload-Header-Content-Type": mime, "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        destino = r.headers.get("X-Goog-Upload-URL")
    if not destino:
        return None
    envio = urllib.request.Request(
        destino, data=caminho.read_bytes(),
        headers={"Content-Length": str(tam), "X-Goog-Upload-Offset": "0",
                 "X-Goog-Upload-Command": "upload, finalize"})
    with urllib.request.urlopen(envio, timeout=timeout) as r:
        d = json.loads(r.read().decode("utf-8"))
    return d.get("file", {}).get("uri")


def _esperar_ativo(uri: str, key: str, limite_s: int) -> bool:
    """O provider transcodifica antes de conseguir ler. Perguntar cedo devolve
    FAILED_PRECONDITION — daí a espera explícita em vez de um sleep chutado."""
    nome = "files/" + uri.rstrip("/").split("/")[-1]
    fim = time.time() + limite_s
    while time.time() < fim:
        try:
            with urllib.request.urlopen(_ARQUIVO.format(n=nome, k=key), timeout=30) as r:
                estado = json.loads(r.read().decode("utf-8")).get("state", "")
            if estado == "ACTIVE":
                return True
            if estado == "FAILED":
                return False
        except Exception:  # noqa: BLE001 — instabilidade na consulta não é falha do upload
            pass
        time.sleep(3)
    return False


def analisar_video(caminho: str, *, prompt: str | None = None,
                   mime: str = "video/mp4") -> tuple[str, str]:
    """(texto, fonte) lendo o VÍDEO INTEIRO. fonte='gemini_video' | 'sem_visao'.

    Nunca levanta exceção: quem chama decide se cai pro caminho de frames, que
    continua valendo e é de graça.
    """
    key = os.environ.get("GEMINI_API_KEY", "").strip()
    p = Path(caminho)
    if not key or not p.exists():
        return "", "sem_visao"
    timeout = int(os.environ.get("VISAO_VIDEO_TIMEOUT_S", "600"))
    try:
        uri = _upload_arquivo(p, mime, key, timeout)
        if not uri or not _esperar_ativo(uri, key, int(os.environ.get("VISAO_VIDEO_ESPERA_S", "300"))):
            log.warning("vídeo não ficou pronto no provider — caindo pro caminho de frames")
            return "", "sem_visao"
        corpo = json.dumps({
            "contents": [{"parts": [{"text": prompt or _PROMPT_VIDEO},
                                    {"file_data": {"mime_type": mime, "file_uri": uri}}]}],
            "generationConfig": {"temperature": 0.25, "maxOutputTokens": 2400},
        }).encode()
        req = urllib.request.Request(_ENDPOINT.format(m=_MODELO_VIDEO, k=key), data=corpo,
                                     headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            d = json.loads(r.read().decode("utf-8"))
        txt = (d["candidates"][0]["content"]["parts"][0]["text"] or "").strip()
        return (txt, "gemini_video") if txt else ("", "sem_visao")
    except Exception as e:  # noqa: BLE001
        log.warning("análise de vídeo falhou (%s: %s) — caminho de frames segue valendo",
                    type(e).__name__, str(e)[:160])
        return "", "sem_visao"


if __name__ == "__main__":  # self-check: cascata Groq -> Gemini -> OCR; honesto sem frames
    os.environ.pop("VISAO_GEMINI", None)
    os.environ["VISAO_GROQ"] = "0"  # nos testes de baixo, Groq desligado (sem rede)
    assert analisar_frames([]) == ("", "sem_visao")
    # <think> do modelo NUNCA vaza pra copy
    assert _sem_think("<think>raciocinio interno</think>Sala de musculação.") == "Sala de musculação."
    assert _sem_think("Academia.<think>truncado sem fechar") == "Academia."
    # ORÇAMENTO: o pedido inteiro tem que caber no teto, com qualquer nº de frames
    for _n in range(1, 9):
        _img, _tok = _orcamento(_n)
        assert _img * _CUSTO_IMAGEM + _RESERVA_TEXTO + _tok <= _TETO_TPM, (_n, _img, _tok)
        assert 1 <= _img <= _MAX_IMAGENS and _tok >= _RESPOSTA_MIN, (_n, _img, _tok)
    # PERMANENTE vs TRANSITÓRIO: 'Request too large' chega como 429 e NÃO é pra esperar
    assert _classifica(429, "Request too large ... Limit 8000, Requested 8422") == ("permanente", 0.0)
    assert _classifica(400, "Too many images") == ("permanente", 0.0)
    _cl, _esp = _classifica(429, "Rate limit reached ... please try again in 7.5s")
    assert _cl == "transitorio" and _esp == 8.5, (_cl, _esp)
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
