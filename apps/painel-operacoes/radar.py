"""Radar de Vídeo — analisa um link (yt-dlp → Whisper → insight) e GUARDA.

Memória persistente: cada análise vai pra tabela video_analises (storage.conn).
Ao gerar um insight novo, injeta no prompt um resumo das análises anteriores da
MESMA origem (conta/concorrente) + as mais recentes — o LLM "aprende" padrão ao
longo do tempo em vez de olhar cada vídeo do zero. Isto é CONTEXTO injetado, não
fine-tuning (CLAUDE.md).

Reuso puro: yt-dlp/ffmpeg (já no host), transcricao (shared-core/ai), llm_proxy
(camada LLM sancionada, com retry), storage.conn (SQLite do monorepo). Sem dep nova.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

_AQUI = Path(__file__).resolve().parent
sys.path.insert(0, str(_AQUI.parents[1] / "packages"))

CATEGORIAS = {"marketing", "vendas", "produto", "mindset", "operação", "concorrente", "outro"}
# Motores do JP pra onde um insight pode ser ROTEADO (upgrade c). O Radar deixa de
# ser só um digest e vira distribuidor: cada sacada ganha o(s) motor(es) onde é
# acionável, e a Caixa de Ideias consome isso agrupado por motor.
MOTORES = {"arbitragem", "motor-site", "motor-b", "noemi"}
# Verticais catalogadas (Radar Omnisciente cam.1). O LLM encaixa numa destas OU
# devolve um nome novo => marcado vertical_nova (nunca força encaixe). Lista base
# das verticais do JP; sincronizar com cartuchos quando crescer.
VERTICAIS = {"marmoraria", "clinica", "contabilidade", "imobiliaria", "energia_solar",
             "odontologia", "estetica", "fisioterapia", "harmonizacao", "advocacia",
             "restaurante", "ecommerce", "dropshipping", "mecanica", "psicologia"}


def _origem_da_url(url: str) -> str:
    """Deriva a origem (conta/domínio) pra agrupar o radar. Instagram → @handle."""
    try:
        u = urlparse(url)
        if "instagram.com" in u.netloc:
            partes = [p for p in u.path.split("/") if p and p not in ("reel", "p", "reels", "tv")]
            if partes and partes[0] not in ("", "explore"):
                return "@" + partes[0]
        return u.netloc or "desconhecida"
    except ValueError:
        return "desconhecida"


def _yt_extra() -> list[str]:
    """Args comuns do yt-dlp: cookies (RADAR_COOKIES) + proxy (RADAR_PROXY). O proxy
    faz o download SAIR por um IP que o IG/YT não bloqueia (o IP do servidor toma 429).
    Com RADAR_PROXY setado, o link volta a funcionar automático — sem enviar vídeo."""
    extra: list[str] = []
    cookies = os.environ.get("RADAR_COOKIES", "/root/noemi-infra/infra/cookies.txt")
    if cookies and Path(cookies).exists():
        extra += ["--cookies", cookies]
    proxy = os.environ.get("RADAR_PROXY", "").strip()
    if proxy:
        extra += ["--proxy", proxy]
    return extra


def _baixar_audio(link: str, destino: Path) -> Path:
    """Só o áudio em mp3. Drive tem caminho próprio (yt-dlp não baixa Drive /view);
    IG/YT usam yt-dlp com cookies (RADAR_COOKIES) + proxy opcional (RADAR_PROXY)."""
    if "drive.google.com" in link:
        return _baixar_drive(link, destino)
    saida = destino / "audio.%(ext)s"
    # --write-info-json: guarda o metadado (autor/conta) do post junto do áudio
    cmd = ["yt-dlp", "-x", "--audio-format", "mp3", "--no-playlist",
           "--write-info-json", "-o", str(saida)] + _yt_extra()
    try:
        subprocess.run([*cmd, link], check=True, capture_output=True, text=True, timeout=300)
    except subprocess.CalledProcessError as e:
        err = (e.stderr or "")[-400:]
        if "403" in err or "login" in err.lower() or "sign in" in err.lower() or "cookies" in err.lower():
            raise RuntimeError("IG/YouTube exigem sessão: suba um cookies.txt em "
                               "infra/cookies.txt (extensão 'Get cookies.txt'). Detalhe: " + err[:150])
        raise RuntimeError(f"yt-dlp falhou: {err[:200]}")
    mp3s = list(destino.glob("*.mp3"))
    if not mp3s:
        raise RuntimeError("yt-dlp não gerou mp3")
    return mp3s[0]


def _metadados(link: str) -> tuple[str, str]:
    """(legenda, @handle) via `yt-dlp --dump-json --skip-download` — pega caption/
    título SEM baixar mídia. No IG isso funciona bem mais que baixar o vídeo (que
    dá 403). ('', '') se nem o metadado sair. É a fonte do nome-do-produto/oferta."""
    if "drive.google.com" in link:
        return "", ""
    cmd = ["yt-dlp", "--dump-json", "--skip-download", "--no-playlist", "--no-warnings"] + _yt_extra()
    try:
        out = subprocess.run([*cmd, link], capture_output=True, text=True, timeout=120).stdout
        d = json.loads(out.splitlines()[0]) if out.strip() else {}
    except Exception:  # noqa: BLE001 — metadado é best-effort; falha vira ('','')
        return "", ""
    legenda = " ".join(filter(None, [d.get("title"), d.get("description")]))[:6000]
    h = (d.get("uploader_id") or d.get("channel") or d.get("uploader") or "").strip()
    return legenda, ("@" + h.lstrip("@") if h else "")


def _frames(video_path: str, destino: Path, n: int = 6) -> list[bytes]:
    """~n frames JPEG do vídeo, um por CENA (upgrade a). É o que dá OLHOS pro radar:
    lê o que está na TELA (produto/UI/código). Amostragem por scene-detect (pega o
    instante em que a tela MUDA — produto novo, preço, corte) em vez de 1 a cada 2s
    (que num reel estático devolve o mesmo frame repetido). Cai pra amostragem
    uniforme se o vídeo tiver poucos cortes. [] se ffmpeg falhar de vez."""
    padrao = str(destino / "f_%03d.jpg")

    def _rodar(vf: str) -> list[bytes]:
        try:
            subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(video_path),
                            "-vf", vf, "-vsync", "vfr", "-frames:v", str(n), padrao],
                           check=True, capture_output=True, timeout=120)
        except Exception:  # noqa: BLE001 — visão é best-effort; áudio/legenda seguem
            return []
        return [p.read_bytes() for p in sorted(destino.glob("f_*.jpg"))[:n]]

    fr = _rodar("select='gt(scene,0.3)',scale=768:-1")  # 1 frame por troca de cena
    if len(fr) >= 2:
        return fr
    for p in destino.glob("f_*.jpg"):  # limpa os poucos da tentativa de cena
        try:
            p.unlink()
        except OSError:
            pass
    return _rodar("fps=1/2,scale=768:-1")  # fallback: vídeo estático/sem cortes


def _combinar(visao: str, legenda: str, audio: str) -> str:
    """Junta as 3 fontes ROTULADAS pro LLM saber a origem de cada coisa — o nome do
    produto vem da VISÃO/legenda (tela), não do áudio (que pode ser só música)."""
    return "\n".join(filter(None, [
        ("O QUE APARECE NA TELA (visão): " + visao) if visao else "",
        ("LEGENDA/TÍTULO: " + legenda) if legenda else "",
        ("TRANSCRIÇÃO DO ÁUDIO: " + audio) if audio else ""]))


def _conta_do_dir(destino: Path) -> str:
    """Lê a conta/autor do post no .info.json que o yt-dlp gravou. '' se não houver.
    Prefere o @handle (channel/uploader_id) ao nome de exibição."""
    for j in destino.glob("*.info.json"):
        try:
            d = json.loads(j.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        h = d.get("channel") or d.get("uploader_id") or d.get("uploader") or ""
        if h:
            return "@" + str(h).lstrip("@") if not str(h).startswith("@") else str(h)
    return ""


def _baixar_drive(link: str, destino: Path) -> Path:
    """Baixa vídeo do Google Drive (yt-dlp não pega /view) e extrai o áudio em mp3.
    Público = funciona; privado (página de Sign-in) = erro claro pro JP resolver."""
    import re as _re

    import httpx
    m = _re.search(r"/d/([a-zA-Z0-9_-]+)", link) or _re.search(r"[?&]id=([a-zA-Z0-9_-]+)", link)
    if not m:
        raise RuntimeError("não achei o ID do arquivo no link do Drive")
    fid = m.group(1)
    bruto = destino / "drive_video"
    with httpx.Client(timeout=120.0, follow_redirects=True,
                      headers={"User-Agent": "Mozilla/5.0 (noemi-radar/1.0)"}) as c:
        r = c.get("https://drive.google.com/uc", params={"export": "download", "id": fid})
        ct = r.headers.get("content-type", "")
        if "text/html" in ct:  # confirm-token (arquivo grande) OU página de login
            html = r.text
            if "Sign-in" in html or "sign in" in html.lower() or "Faça login" in html:
                raise RuntimeError("vídeo do Drive é PRIVADO — deixe 'qualquer um com o "
                                   "link' (Compartilhar → Acesso geral) ou reautorize o conector Google.")
            tok = _re.search(r'name="confirm"\s+value="([^"]+)"', html) or _re.search(r'confirm=([0-9A-Za-z_-]+)', html)
            uuid = _re.search(r'name="uuid"\s+value="([^"]+)"', html)
            params = {"export": "download", "id": fid, "confirm": tok.group(1) if tok else "t"}
            if uuid:
                params["uuid"] = uuid.group(1)
            r = c.get("https://drive.usercontent.google.com/download", params=params)
            if "text/html" in r.headers.get("content-type", ""):
                raise RuntimeError("Drive não liberou o download (arquivo privado ou muito grande).")
        bruto.write_bytes(r.content)
    saida = destino / "audio.mp3"  # extrai o áudio do vídeo baixado
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(bruto),
                    "-vn", "-acodec", "libmp3lame", "-q:a", "4", str(saida)],
                   check=True, capture_output=True, timeout=180)
    return saida


def _contexto_anterior(origem: str, limite: int = 6) -> list[dict]:
    """Análises passadas relevantes (mesma origem primeiro, completadas com as mais
    recentes) — o 'radar' que acumula padrão. Read-only, best-effort."""
    from shared_core.storage import db
    vistos: dict[int, dict] = {}
    try:
        with db.conn() as c:
            q = ("SELECT id, origem, data, resumo_curto, categoria, score, tags FROM "
                 "(SELECT id, origem, data, categoria, score, tags, substr(insight,1,240) resumo_curto "
                 " FROM video_analises {onde} ORDER BY id DESC LIMIT ?)")
            for onde, params in ((f"WHERE origem = ?", (origem, limite)), ("", (limite,))):
                for r in c.execute(q.format(onde=onde), params):
                    vistos.setdefault(r["id"], dict(r))
    except Exception:  # noqa: BLE001 — sem contexto ainda é OK
        return []
    return list(vistos.values())[:limite]


_PROMPT_BASE = (
    "Você é o Radar de Vídeo do JP (Noemi OS: SDR/IA no WhatsApp que ele VENDE pra "
    "clínicas/PMEs; também geração de site/vídeo, growth, arbitragem). Dada a TRANSCRIÇÃO "
    "de um vídeo (dica de marketing/vendas/produto) e o histórico, seja AFIADO e prático.\n"
    "REGRA DE FUSÃO DE SINAIS: as fontes vêm rotuladas (TELA/visão, LEGENDA/título, "
    "ÁUDIO/transcrição). Se divergirem sobre O QUE é o produto/oferta, priorize "
    "TELA > LEGENDA > ÁUDIO (o áudio pode ser só música de fundo — não deixe ele "
    "definir o produto se a tela mostra outra coisa). Produza UMA análise coesa.\n"
    "Responda SOMENTE JSON com as chaves:\n"
    '"insight" (2-4 frases acionáveis — a sacada central, conectando com o histórico), '
    '"resumo" (1 frase), '
    '"onde_usar" (lista de 2-4 usos concretos no negócio do JP: ex "abertura de prospecção", '
    '"copy de anúncio", "script da Noemi", "post"), '
    '"verticais" (lista de nichos onde aplica: ex "odontologia", "estética", "imobiliária"), '
    '"axioma" (1 frase — o princípio atemporal por trás da dica), '
    '"assimilacao" (1 frase — o próximo passo concreto pra ABSORVER isso no sistema/operação), '
    '"comparacao" (1 frase — como se relaciona com o histórico: reforça? contradiz? é novo?), '
    '"modelos" (objeto com o TEMPLATE REPLICÁVEL específico que dá pra tirar disso. '
    "REGRA DURA: se o conteúdo não dá uma ação ESPECÍFICA pra um domínio, deixe \"\" — "
    "vazio é MELHOR que genérico. PROIBIDO platitude tipo 'criar conteúdo atraente', "
    "'desenvolver site coerente', 'processos eficientes'. Cada valor tem que citar algo "
    "concreto DO conteúdo (um número, um produto, um gancho, um passo). "
    '{"video":"gancho/formato específico","site":"seção/oferta específica","negocio":'
    '"como monetiza, concreto","produto":"produto/feature nomeável","operacao":'
    '"automação/passo concreto","projeto":"experimento testável"}), '
    f'"motores" (lista dos motores do JP onde ESTE insight é acionável, subconjunto '
    f'de {sorted(MOTORES)} — arbitragem=garimpo/revenda, motor-site=gerador de sites, '
    f'motor-b=gerador de vídeo, noemi=SDR/IA no WhatsApp. [] se nenhum for claro; '
    f'NÃO chute — só quando o insight realmente serve pra aquele motor), '
    f'"vertical" (a vertical/nicho do conteúdo: um de {sorted(VERTICAIS)} se casar, '
    f'senão o nome NOVO que você propor em 1 palavra; "" se não der pra dizer — não force), '
    '"marketing" (o PADRÃO replicável, NÃO a cópia — objeto '
    '{"angulo":"o ângulo/promessa","hook":"a fisgada dos 3s","oferta":"a estrutura da oferta",'
    '"cta":"a chamada","funil":"o tipo de funil"}; cada campo curto e concreto, "" se ausente. '
    'É munição de copy, não plágio do post), '
    '"ferramentas" (lista de softwares/ferramentas CITADOS ou implicados no conteúdo, '
    'ex ["Shopify","Ruflo"]; [] se nenhum — cada um vira produto candidato), '
    f'"categoria" (um de {sorted(CATEGORIAS)}), '
    '"score" (inteiro 1-5 de relevância pro JP), '
    '"tags" (lista de 3-6 palavras-chave minúsculas).'
)


def _prompt(transcricao: str, contexto: list[dict], instrucao: str = "") -> str:
    hist = ""
    if contexto:
        linhas = [f"- [{a.get('categoria','?')}/{a.get('score','?')}] {a.get('origem','?')}: "
                  f"{(a.get('resumo_curto') or '').strip()[:160]}" for a in contexto]
        hist = "\n\nHISTÓRICO (análises anteriores relevantes):\n" + "\n".join(linhas)
    # Se o JP mandou uma INSTRUÇÃO junto (legenda), ela MANDA: o campo "insight"
    # responde o pedido dele especificamente (replicar/adaptar/comparar), não um
    # digest genérico. Os outros campos seguem preenchidos pro radar acumular.
    pedido = ""
    if instrucao and instrucao.strip():
        pedido = (f"\n\n⚠️ O JP PEDIU ISTO (responda no campo 'insight', "
                  f"concreto e específico, usando o vídeo): \"{instrucao.strip()[:400]}\"")
    return f"{_PROMPT_BASE}{pedido}{hist}\n\nTRANSCRIÇÃO:\n{transcricao[:9000]}"


def _insight(transcricao: str, contexto: list[dict], instrucao: str = "") -> dict:
    """LLM (via proxy sancionado, com retry) → dict validado. Degrada pra resumo
    extrativo se o proxy estiver fora — nunca crasha a análise."""
    from shared_core.ai import llm_proxy
    txt = llm_proxy.completar(_prompt(transcricao, contexto, instrucao), model="analise",
                              max_tokens=800, temperature=0.3)
    bruto = _extrair_json(txt) if txt else None
    if not bruto:  # proxy fora / saída ilegível → resumo extrativo honesto
        frase = re.split(r"(?<=[.!?])\s+", transcricao.strip())[:2]
        return {"insight": " ".join(frase)[:400] or "(sem insight — LLM indisponível)",
                "resumo": (frase[0] if frase else "")[:160], "categoria": "outro",
                "score": 1, "tags": [], "fonte": "extrativo",
                "onde_usar": [], "verticais": [], "axioma": "", "assimilacao": "", "comparacao": "",
                "modelos": {}, "motores": [], "vertical": "", "vertical_nova": False,
                "marketing": {}, "ferramentas": []}
    cat = str(bruto.get("categoria", "outro")).strip().lower()
    try:
        score = max(1, min(5, int(bruto.get("score", 1))))
    except (TypeError, ValueError):
        score = 1

    def _lista(v):
        return [str(x).strip()[:40] for x in v if str(x).strip()][:5] if isinstance(v, list) else []

    def _modelos(v):  # 6 domínios, cada um 1 frase (ordem de trabalho) ou ausente
        d = v if isinstance(v, dict) else {}
        out = {k: str(d.get(k, "")).strip()[:200] for k in
               ("video", "site", "negocio", "produto", "operacao", "projeto")}
        return {k: val for k, val in out.items() if val}  # só os que têm ação real

    def _motores(v):  # roteamento (upgrade c): só os motores válidos, sem duplicar
        if not isinstance(v, list):
            return []
        vistos = []
        for x in v:
            m = str(x).strip().lower().replace("_", "-")
            if m in MOTORES and m not in vistos:
                vistos.append(m)
        return vistos

    def _mkt(v):  # cam.3: PADRÃO replicável de marketing (angulo/hook/oferta/cta/funil)
        d = v if isinstance(v, dict) else {}
        out = {k: str(d.get(k, "")).strip()[:160] for k in
               ("angulo", "hook", "oferta", "cta", "funil")}
        return {k: val for k, val in out.items() if val}

    vertical = str(bruto.get("vertical", "")).strip().lower()[:40]
    return {"insight": str(bruto.get("insight", "")).strip()[:1200] or "(sem insight)",
            "modelos": _modelos(bruto.get("modelos")),
            "motores": _motores(bruto.get("motores")),
            "vertical": vertical,  # cam.1
            "vertical_nova": bool(vertical) and vertical not in VERTICAIS,
            "marketing": _mkt(bruto.get("marketing")),  # cam.3
            "ferramentas": _lista(bruto.get("ferramentas")),  # cam.4
            "resumo": str(bruto.get("resumo", "")).strip()[:200],
            "onde_usar": _lista(bruto.get("onde_usar")), "verticais": _lista(bruto.get("verticais")),
            "axioma": str(bruto.get("axioma", "")).strip()[:240],
            "assimilacao": str(bruto.get("assimilacao", "")).strip()[:240],
            "comparacao": str(bruto.get("comparacao", "")).strip()[:240],
            "categoria": cat if cat in CATEGORIAS else "outro",
            "score": score, "tags": _lista(bruto.get("tags")), "fonte": "llm"}


def _extrair_json(texto: str) -> dict | None:
    m = re.search(r"\{.*\}", texto or "", re.S)
    if not m:
        return None
    try:
        d = json.loads(m.group(0))
        return d if isinstance(d, dict) else None
    except (ValueError, TypeError):
        return None


def _limpar_url(url: str) -> str:
    """(1) Higiene: tira tracking (utm_*, igshid, fbclid, si, feature) e fragmento →
    dedup mais confiável + URL limpa. Preserva os params que identificam o vídeo."""
    from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse
    try:
        p = urlparse(url)
    except ValueError:
        return url
    lixo = ("utm_", "igshid", "fbclid", "gclid", "si", "feature", "ref", "ref_src")
    q = [(k, v) for k, v in parse_qsl(p.query)
         if not any(k == b or k.startswith(b) for b in lixo)]
    return urlunparse(p._replace(query=urlencode(q), fragment=""))


def _ja_analisada(url: str) -> dict | None:
    """(2) Dedup: se essa URL já foi analisada, devolve a análise existente (evita
    gastar LLM/Whisper de novo). None se é nova."""
    from shared_core.storage import db
    try:
        with db.conn() as c:
            r = c.execute("SELECT id FROM video_analises WHERE url = ? ORDER BY id DESC LIMIT 1",
                          (url,)).fetchone()
    except Exception:  # noqa: BLE001
        return None
    return obter(r["id"]) if r else None


def analisar(url: str, origem: str | None = None, instrucao: str = "",
             forcar: bool = False) -> dict:
    """Pipeline por URL: baixa → transcreve → contexto → insight → GRAVA.
    `instrucao` = pedido do JP na legenda (replicar/adaptar/comparar). `forcar`=True
    reanalisa mesmo se a URL já existe (senão devolve a análise anterior — economia)."""
    from shared_core.ai import transcricao as trans
    url = _limpar_url((url or "").strip())  # (1) higiene
    if not url.startswith("http"):
        raise ValueError("url inválida")
    if not forcar:  # (2) dedup: não regasta LLM num link já analisado
        ja = _ja_analisada(url)
        if ja:
            return {**ja, "reaproveitada": True}
    origem_dada = (origem or "").strip()
    legenda, handle = _metadados(url)  # caption/título — funciona mesmo quando a mídia não baixa
    texto_audio = ""
    with tempfile.TemporaryDirectory(prefix="radar_") as td:
        try:
            audio = _baixar_audio(url, Path(td))
            # a conta/autor REAL vem do metadado do download (yt-dlp), não da URL.
            origem = origem_dada or _conta_do_dir(Path(td)) or handle or _origem_da_url(url)
            texto_audio = trans.transcrever(str(audio))
        except RuntimeError as e:
            # IG/YT bloqueou a mídia → NÃO morre: segue com a legenda (análise sempre).
            origem = origem_dada or handle or _origem_da_url(url)
            if not legenda:
                raise RuntimeError(f"não deu pra baixar o vídeo nem ler a legenda: {e}")
    # legenda (nome do produto/oferta) + transcrição (narração) → análise fiel, sem
    # confundir música de fundo com o produto (a legenda é a âncora do "o quê").
    texto = "\n".join(filter(None, [
        ("LEGENDA/TÍTULO: " + legenda) if legenda else "",
        ("TRANSCRIÇÃO DO ÁUDIO: " + texto_audio) if texto_audio else ""]))
    if not texto.strip():
        raise RuntimeError("sem transcrição e sem legenda — link privado/inacessível")
    return _processar(texto, origem, url, instrucao)


def analisar_arquivo(caminho: str, origem: str = "telegram", url_ref: str = "",
                     instrucao: str = "") -> dict:
    """Pipeline por ARQUIVO local (vídeo enviado no Telegram). VISÃO (frames→Gemini,
    o que está na TELA) + transcrição do áudio → insight → GRAVA. A visão é a fonte
    do nome-do-produto (o áudio pode ser só música); análise roda com qualquer uma."""
    from shared_core.ai import transcricao as trans
    from shared_core.ai import visao
    texto_audio, visao_txt = "", ""
    with tempfile.TemporaryDirectory(prefix="radar_") as td:
        audio = Path(td) / "audio.mp3"
        try:
            subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", caminho,
                            "-vn", "-acodec", "libmp3lame", "-q:a", "4", str(audio)],
                           check=True, capture_output=True, timeout=180)
            texto_audio = trans.transcrever(str(audio)) or ""
        except Exception:  # noqa: BLE001 — vídeo mudo/áudio ruim: a visão carrega
            texto_audio = ""
        visao_txt, _ = visao.analisar_frames(_frames(caminho, Path(td)))
    texto = _combinar(visao_txt, "", texto_audio)
    if not texto.strip():
        raise RuntimeError("nem visão nem áudio legíveis (sem chave Gemini/Groq?)")
    return _processar(texto, origem, url_ref, instrucao)


def analisar_imagem(caminho: str, origem: str = "telegram", instrucao: str = "") -> dict:
    """Pipeline por IMAGEM (foto enviada no Telegram) — visão (OCR/Gemini) da imagem +
    a legenda/pedido do JP → insight → GRAVA. Sem ffmpeg/áudio (é imagem). Se o OCR vier
    vazio, a legenda ainda ancora a análise (a foto raramente vem sem contexto)."""
    from shared_core.ai import visao
    with open(caminho, "rb") as f:
        visao_txt, _ = visao.analisar_frames([f.read()])
    texto = _combinar(visao_txt, (instrucao or "").strip(), "")  # legenda = o que o JP escreveu
    if not texto.strip():
        raise RuntimeError("imagem sem texto legível e sem legenda — manda com uma legenda de contexto")
    return _processar(texto, origem, "(imagem enviada)", instrucao)


def analisar_site(url: str, origem: str = "") -> dict:
    """Adapter SITE (Item 8, fonte_tipo=site): busca a página, extrai o texto e joga no
    NÚCLEO genérico → insight/vertical/motores/ferramentas → Caixa de Ideias, como qualquer
    fonte. Dogfood: o próprio site vira fonte analisada pela IA. (Interação de visitante vem
    com o beacon do Item 5; aqui é o CONTEÚDO.)"""
    import urllib.request
    html = urllib.request.urlopen(url, timeout=15).read().decode("utf-8", "replace")
    semtags = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", html, flags=re.S)
    texto = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", semtags)).strip()
    if not texto:
        raise RuntimeError("página sem texto legível")
    obs = observacao(texto[:9000], origem=origem or _origem_da_url(url), ref=url, fonte_tipo="site")
    return processar_observacao(obs)


# ═══════════════════════════════════════════════════════════════════════════
# FRONTEIRA fonte↔núcleo (Radar Omnisciente). Um ADAPTER (reel hoje; SDR/site/
# auto-observação depois) produz uma OBSERVAÇÃO no formato padrão abaixo. O NÚCLEO
# (processar_observacao → _insight, as 5 camadas) processa QUALQUER fonte sem saber
# de onde veio. A fonte não conhece o núcleo; o núcleo não conhece a fonte —
# trocar/somar adapter não reescreve o núcleo. `fonte_tipo` fica gravado pra o
# cruzamento entre-fontes (um padrão em reel E em conversa do SDR = sinal mais forte).
# ═══════════════════════════════════════════════════════════════════════════
FONTES = ("reel", "sdr", "sdr_cliente", "site", "relatorio")  # tipos de adapter (reel + sdr_cliente hoje)


def observacao(texto: str, *, origem: str = "", ref: str = "", instrucao: str = "",
               fonte_tipo: str = "reel") -> dict:
    """Monta a OBSERVAÇÃO padrão que todo adapter emite pro núcleo. `texto` é o
    conteúdo já fundido/rotulado (TELA/LEGENDA/ÁUDIO no reel; será conversa no SDR,
    tráfego no site). `ref` = url/id de rastreio. `fonte_tipo` = de qual adapter veio."""
    return {"texto": texto, "origem": origem, "ref": ref,
            "instrucao": instrucao,
            "fonte_tipo": fonte_tipo if fonte_tipo in FONTES else "reel"}


def processar_observacao(obs: dict) -> dict:
    """NÚCLEO genérico: recebe uma observação padrão (de QUALQUER adapter) → roda as
    camadas de análise → grava → devolve. Não sabe da fonte; só do formato padrão.
    Dispatch por fonte_tipo: cada adapter pode ter seu cérebro (reel = _insight/Groq;
    sdr_cliente = Insight Engine/Groq-only). O downstream (gate, storage) é do adapter."""
    if obs.get("fonte_tipo") == "sdr_cliente":  # tier 1 cliente-facing (Groq-only)
        import insight_engine
        return insight_engine.processar_cliente(obs)
    from shared_core.storage import db
    texto = obs.get("texto", "")
    origem = obs.get("origem", "")
    ref = obs.get("ref", "")
    instrucao = obs.get("instrucao", "")
    fonte_tipo = obs.get("fonte_tipo", "reel")
    contexto = _contexto_anterior(origem)
    ins = _insight(texto, contexto, instrucao)
    ins["pedido"] = (instrucao or "").strip()[:400]  # upgrade d: grava a legenda/pedido
    ins["fonte_tipo"] = fonte_tipo                     # de qual adapter veio (cruzamento futuro)
    data = datetime.now(timezone.utc).isoformat()
    detalhe = json.dumps({k: ins.get(k) for k in
                          ("onde_usar", "verticais", "axioma", "assimilacao", "comparacao",
                           "modelos", "motores", "pedido", "fonte", "fonte_tipo",
                           "vertical", "vertical_nova", "marketing", "ferramentas")},
                         ensure_ascii=False)
    with db.conn() as c:
        cur = c.execute(
            "INSERT INTO video_analises (origem, url, data, transcricao, insight, categoria, score, tags, detalhe) "
            "VALUES (?,?,?,?,?,?,?,?,?)",
            (origem, ref, data, texto, ins["insight"], ins["categoria"], ins["score"],
             ",".join(ins["tags"]), detalhe))
        c.commit()
        aid = cur.lastrowid
    return {"id": aid, "origem": origem, "url": ref, "data": data,
            "transcricao": texto, "usou_contexto": len(contexto), **ins}


def _processar(texto: str, origem: str, url: str, instrucao: str = "") -> dict:
    """Shim de retrocompat: o adapter de REEL (analisar/analisar_arquivo) chama aqui.
    Vira uma observação padrão fonte_tipo=reel e delega pro núcleo genérico —
    comportamento idêntico ao de antes do refactor."""
    return processar_observacao(observacao(texto, origem=origem, ref=url,
                                           instrucao=instrucao, fonte_tipo="reel"))


def listar(q: str | None = None, limite: int = 40) -> list[dict]:
    """Histórico (mais recente primeiro), com busca simples por palavra-chave."""
    from shared_core.storage import db
    with db.conn() as c:
        if q and q.strip():
            like = f"%{q.strip()}%"
            rows = c.execute(
                "SELECT id, origem, url, data, categoria, score, tags, detalhe, feedback, "
                "substr(insight,1,300) insight FROM video_analises "
                "WHERE insight LIKE ? OR transcricao LIKE ? OR origem LIKE ? OR tags LIKE ? "
                "ORDER BY COALESCE(feedback,0) DESC, score DESC, id DESC LIMIT ?",(like, like, like, like, limite)).fetchall()
        else:
            rows = c.execute(
                "SELECT id, origem, url, data, categoria, score, tags, detalhe, feedback, "
                "substr(insight,1,300) insight FROM video_analises "
                "ORDER BY COALESCE(feedback,0) DESC, score DESC, id DESC LIMIT ?",(limite,)).fetchall()
    return [_expandir(dict(r)) for r in rows]


def _expandir(d: dict) -> dict:
    """Injeta os campos ricos do JSON `detalhe` no dict (pro front renderizar)."""
    try:
        det = json.loads(d.get("detalhe") or "{}")
        if isinstance(det, dict):
            d.update({k: det.get(k) for k in
                      ("onde_usar", "verticais", "axioma", "assimilacao", "comparacao",
                       "modelos", "motores", "pedido", "fonte_tipo",
                       "vertical", "vertical_nova", "marketing", "ferramentas")})
    except (ValueError, TypeError):
        pass
    return d


_DOMINIOS = ("video", "site", "negocio", "produto", "operacao", "projeto")
# Qual template de domínio melhor serve cada motor (pra Caixa por-motor, upgrade e).
_MOTOR_DOMINIO = {"arbitragem": ("negocio", "produto"), "motor-site": ("site",),
                  "motor-b": ("video",), "noemi": ("operacao", "negocio")}


def harvest_ideias(limite: int = 300) -> dict:
    """CAIXA DE IDEIAS: colhe os `modelos` (templates replicáveis) de TODAS as análises,
    agrupados por domínio. Cada ideia carrega a fonte (origem/url/data/score) pra
    rastrear de onde veio. É uma VIEW sobre video_analises — não duplica storage."""
    from shared_core.storage import db
    grupos: dict[str, list] = {k: [] for k in _DOMINIOS}
    por_motor: dict[str, list] = {m: [] for m in sorted(MOTORES)}
    ferramentas: dict[str, dict] = {}  # cam.4: produto candidato -> {nome, mencoes, origem, url, aid}
    try:
        with db.conn() as c:
            rows = c.execute(
                "SELECT id, origem, url, data, score, detalhe FROM video_analises "
                "ORDER BY COALESCE(feedback,0) DESC, score DESC, id DESC LIMIT ?", (limite,)).fetchall()
    except Exception:  # noqa: BLE001 — sem dados ainda é OK
        return {"grupos": grupos, "por_motor": por_motor, "ferramentas": [], "total": 0}
    total = 0
    for r in rows:
        try:
            det = json.loads(r["detalhe"] or "{}") or {}
        except (ValueError, TypeError):
            continue
        mods = det.get("modelos") or {}
        fonte = {"origem": r["origem"], "url": r["url"], "data": r["data"],
                 "score": r["score"], "aid": r["id"]}
        for dom in _DOMINIOS:
            ideia = (mods.get(dom) or "").strip()
            if ideia:
                grupos[dom].append({"ideia": ideia, **fonte})
                total += 1
        # upgrade e: a Caixa CONSOME o roteamento — cada motor ganha a ideia mais
        # relevante daquele vídeo (o template do domínio que casa com o motor).
        for motor in (det.get("motores") or []):
            if motor not in por_motor:
                continue
            ideia = next((mods.get(d, "").strip() for d in _MOTOR_DOMINIO.get(motor, ())
                          if (mods.get(d) or "").strip()),
                         next((v.strip() for v in mods.values() if (v or "").strip()), ""))
            if ideia:
                por_motor[motor].append({"ideia": ideia, **fonte})
        # cam.4: ferramentas citadas viram produtos candidatos. Dedup por nome; conta
        # menções (recorrência = sinal de força — 3 fontes citando > 1 fonte).
        for f in (det.get("ferramentas") or []):
            chave = str(f).strip().lower()
            if not chave:
                continue
            if chave in ferramentas:
                ferramentas[chave]["mencoes"] += 1
            else:
                ferramentas[chave] = {"nome": str(f).strip()[:60], "mencoes": 1, **fonte}
    cand = sorted(ferramentas.values(), key=lambda x: x["mencoes"], reverse=True)
    return {"grupos": grupos, "por_motor": por_motor, "ferramentas": cand, "total": total}


def obter(aid: int) -> dict | None:
    from shared_core.storage import db
    with db.conn() as c:
        r = c.execute("SELECT * FROM video_analises WHERE id = ?", (aid,)).fetchone()
    return _expandir(dict(r)) if r else None


def set_feedback(aid: int, valor: int) -> bool:
    """👍=1 / 👎=-1 / 0=limpa. Sinal rotulado do 2.1 (o autotune pondera por isto)."""
    v = 1 if valor > 0 else (-1 if valor < 0 else None)
    from shared_core.storage import db
    with db.conn() as c:
        c.execute("UPDATE video_analises SET feedback=? WHERE id=?", (v, aid))
        c.commit()
    return True


def stats() -> dict:
    """(5) Panorama do radar: total, por categoria, top origens, quantas com visão."""
    from shared_core.storage import db
    try:
        with db.conn() as c:
            total = c.execute("SELECT COUNT(*) n FROM video_analises").fetchone()["n"]
            cats = {r["categoria"] or "outro": r["n"] for r in c.execute(
                "SELECT categoria, COUNT(*) n FROM video_analises GROUP BY categoria ORDER BY n DESC")}
            origens = [{"origem": r["origem"], "n": r["n"]} for r in c.execute(
                "SELECT origem, COUNT(*) n FROM video_analises GROUP BY origem ORDER BY n DESC LIMIT 8")]
            com_visao = c.execute(
                "SELECT COUNT(*) n FROM video_analises WHERE transcricao LIKE '%NA TELA%'").fetchone()["n"]
    except Exception:  # noqa: BLE001
        return {"total": 0, "categorias": {}, "origens": [], "com_visao": 0}
    return {"total": total, "categorias": cats, "origens": origens, "com_visao": com_visao}


def deletar(aid: int) -> bool:
    """(6) Remove uma análise (limpar teste/lixo do radar)."""
    from shared_core.storage import db
    with db.conn() as c:
        cur = c.execute("DELETE FROM video_analises WHERE id=?", (aid,))
        c.commit()
    return cur.rowcount > 0


def registrar_job(ok: bool, *, origem: str = "", url: str = "", motivo: str = "") -> None:
    """Log de job do radar (sucesso E falha) → visibilidade no /obs. Fire-and-forget:
    falha em logar nunca derruba a análise. Guarda os últimos jobs pra status."""
    from datetime import datetime, timezone

    from shared_core.storage import db
    try:
        with db.conn() as c:
            c.execute("CREATE TABLE IF NOT EXISTS radar_jobs (id INTEGER PRIMARY KEY AUTOINCREMENT, "
                      "ts TEXT, ok INTEGER, origem TEXT, url TEXT, motivo TEXT)")
            c.execute("INSERT INTO radar_jobs (ts,ok,origem,url,motivo) VALUES (?,?,?,?,?)",
                      (datetime.now(timezone.utc).isoformat(), 1 if ok else 0,
                       origem[:80], url[:300], motivo[:200]))
            c.execute("DELETE FROM radar_jobs WHERE id < (SELECT MAX(id)-200 FROM radar_jobs)")  # só últimos 200
            c.commit()
    except Exception:  # noqa: BLE001 — log é secundário
        pass


def status_jobs(limite: int = 12) -> dict:
    """(5) Status do radar pro /obs: últimos jobs (ok/falha/motivo) + taxa de sucesso."""
    from shared_core.storage import db
    try:
        with db.conn() as c:
            c.execute("CREATE TABLE IF NOT EXISTS radar_jobs (id INTEGER PRIMARY KEY AUTOINCREMENT, "
                      "ts TEXT, ok INTEGER, origem TEXT, url TEXT, motivo TEXT)")
            rows = [dict(r) for r in c.execute(
                "SELECT ts, ok, origem, url, motivo FROM radar_jobs ORDER BY id DESC LIMIT ?", (limite,))]
            tot = c.execute("SELECT COUNT(*) n, COALESCE(SUM(ok),0) s FROM radar_jobs").fetchone()
    except Exception:  # noqa: BLE001
        return {"jobs": [], "total": 0, "sucesso_pct": None}
    n = tot["n"] or 0
    return {"jobs": rows, "total": n,
            "sucesso_pct": round(100 * tot["s"] / n) if n else None}


if __name__ == "__main__":  # self-check: origem + json + degradação (sem rede)
    assert _origem_da_url("https://www.instagram.com/reel/ABC/") == "instagram.com" or \
           _origem_da_url("https://www.instagram.com/lojax/reel/ABC/") == "@lojax"
    assert _extrair_json('lixo {"a":1} fim') == {"a": 1}
    d = _insight("Primeira frase. Segunda frase. Terceira.", [])  # proxy provavelmente fora
    assert d["categoria"] in CATEGORIAS and 1 <= d["score"] <= 5, d
    assert d["motores"] == [], d  # degradado não roteia pra motor nenhum
    assert d["vertical"] == "" and d["vertical_nova"] is False and d["ferramentas"] == [], d

    # upgrade c + Omnisciente cam.1/3/4: valida motores + vertical + marketing + ferramentas
    def _fake_completar(*a, **k):
        return ('{"insight":"x","categoria":"vendas","score":4,"motores":'
                '["arbitragem","MOTOR_SITE","inexistente","arbitragem"],'
                '"modelos":{"site":"landing de leilão","negocio":"revende com 30%"},'
                '"vertical":"Odontologia","marketing":{"angulo":"medo de perder cliente",'
                '"hook":"3s","oferta":"","cta":"chama no zap"},"ferramentas":["Shopify","Ruflo"]}')
    import shared_core.ai.llm_proxy as _lp
    _orig = _lp.completar
    _lp.completar = _fake_completar
    try:
        r = _insight("qualquer", [])
        assert r["motores"] == ["arbitragem", "motor-site"], r["motores"]  # dedup+whitelist+normaliza
        assert r["vertical"] == "odontologia" and r["vertical_nova"] is False, r  # cam.1 catalogada
        assert r["marketing"] == {"angulo": "medo de perder cliente", "hook": "3s",
                                  "cta": "chama no zap"}, r["marketing"]       # cam.3 (oferta vazia caiu)
        assert r["ferramentas"] == ["Shopify", "Ruflo"], r["ferramentas"]     # cam.4
        # vertical fora do catálogo => vertical_nova=True
        _lp.completar = lambda *a, **k: '{"insight":"y","categoria":"produto","score":3,"vertical":"petshop"}'
        r2 = _insight("q", [])
        assert r2["vertical"] == "petshop" and r2["vertical_nova"] is True, r2
    finally:
        _lp.completar = _orig

    # upgrade e: harvest agrupa por motor usando o template de domínio que casa
    linha = {"motores": ["arbitragem", "motor-site"],
             "modelos": {"site": "landing de leilão", "negocio": "revende com 30%"}}
    dom_arb = next((linha["modelos"].get(dd, "") for dd in _MOTOR_DOMINIO["arbitragem"]
                    if linha["modelos"].get(dd)), "")
    assert dom_arb == "revende com 30%", dom_arb  # arbitragem prefere negocio/produto

    # REFACTOR adapter: observacao() monta o formato padrão; fonte_tipo inválido cai p/ reel
    o = observacao("t", origem="oo", ref="uu", instrucao="pede", fonte_tipo="sdr")
    assert o == {"texto": "t", "origem": "oo", "ref": "uu", "instrucao": "pede",
                 "fonte_tipo": "sdr"}, o
    assert observacao("t", fonte_tipo="inexistente")["fonte_tipo"] == "reel"
    # o shim _processar delega pro núcleo como observação fonte_tipo=reel (sem tocar DB)
    _capt = {}
    _g = globals()
    _orig_proc = _g["processar_observacao"]
    _g["processar_observacao"] = lambda obs: _capt.update(obs) or {"id": 0}
    try:
        _processar("texto reel", "conta", "http://x", "leg")
        assert _capt["fonte_tipo"] == "reel" and _capt["ref"] == "http://x" and \
               _capt["texto"] == "texto reel", _capt  # núcleo recebe o formato padrão
    finally:
        _g["processar_observacao"] = _orig_proc
    print("radar OK — degradado:", d["fonte"],
          "· cam.1/3/4 + fronteira adapter (observacao/processar_observacao) OK")
