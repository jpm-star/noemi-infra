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
# Taxonomia FIXA de persuasão (schema novo de 10 campos) — o LLM só escolhe destas.
PERSUASAO = ("escassez", "urgencia", "prova_social", "autoridade", "reciprocidade",
             "compromisso_coerencia", "afinidade", "ancoragem", "aversao_a_perda",
             "especificidade", "storytelling", "quebra_de_padrao", "contraste",
             "garantia_reversao_risco")
_PERSUASAO_SET = frozenset(PERSUASAO)
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
        net = u.netloc.lower()
        partes = [p for p in u.path.split("/") if p]
        if "instagram.com" in net:
            partes = [p for p in partes if p not in ("reel", "p", "reels", "tv")]
            if partes and partes[0] not in ("", "explore"):
                return "@" + partes[0]
        # #10 TikTok: /@handle/video/123 — o handle já vem com @ no path
        if "tiktok.com" in net:
            for p in partes:
                if p.startswith("@"):
                    return p
            return "tiktok"
        # #10 YouTube Shorts/watch: /@canal/... ou /shorts/<id> (sem canal na URL)
        if "youtube.com" in net or "youtu.be" in net:
            for p in partes:
                if p.startswith("@"):
                    return p
            return "youtube"
        return net or "desconhecida"
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


def _baixar_video(link: str, destino: Path) -> Path:
    """Baixa o VÍDEO (não só o áudio) pra dar OLHOS ao caminho de URL.

    O `_baixar_audio` usa `-x` (extrai áudio e joga o vídeo fora), por isso todo link
    analisado perdia a visão — só áudio+legenda. Aqui pega o arquivo de vídeo, de onde
    saem TANTO os frames quanto o áudio (1 download, 2 usos). Prefere um formato leve
    (<=480p): frames pra OCR/visão não precisam de 1080p e o download fica rápido."""
    saida = destino / "video.%(ext)s"
    cmd = ["yt-dlp", "-f", "best[height<=480]/best", "--no-playlist",
           "--write-info-json", "-o", str(saida)] + _yt_extra()
    try:
        subprocess.run([*cmd, link], check=True, capture_output=True, text=True, timeout=300)
    except subprocess.CalledProcessError as e:
        raise RuntimeError(f"yt-dlp (vídeo) falhou: {(e.stderr or '')[-200:]}")
    vids = [p for p in destino.iterdir() if p.suffix.lower() in (".mp4", ".mkv", ".webm", ".mov")]
    if not vids:
        raise RuntimeError("yt-dlp não gerou arquivo de vídeo")
    return vids[0]


def _audio_do_video(video: Path, destino: Path) -> Path | None:
    """Extrai o mp3 do vídeo já baixado (mesmo caminho do analisar_arquivo)."""
    audio = destino / "audio.mp3"
    try:
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(video),
                        "-vn", "-acodec", "libmp3lame", "-q:a", "4", str(audio)],
                       check=True, capture_output=True, timeout=180)
        return audio if audio.exists() else None
    except Exception:  # noqa: BLE001 — vídeo mudo: a visão carrega sozinha
        return None


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
            # score > 0 = só o que teve sinal vira memória; corta o resumo extrativo
            # (degradado, score 0) que senão injeta ruído no prompt das próximas análises.
            for onde, params in (("WHERE score > 0 AND origem = ?", (origem, limite)),
                                 ("WHERE score > 0", (limite,))):
                for r in c.execute(q.format(onde=onde), params):
                    vistos.setdefault(r["id"], dict(r))
    except Exception:  # noqa: BLE001 — sem contexto ainda é OK
        return []
    return list(vistos.values())[:limite]


# PASS 1 — raciocínio profundo (prosa, sem formato). Eleva a densidade antes de estruturar.
_PROMPT_ANALISE = (
    "Você é um Principal Analyst / especialista de domínio dissecando um vídeo de marketing/vendas/produto "
    "pro arsenal do JP (Noemi OS: SDR/IA no WhatsApp pra clínicas/PMEs; motor-site; motor-b de vídeo; "
    "arbitragem). Escreva um RASCUNHO analítico CIRÚRGICO e DENSO (sem formato fixo, sem JSON ainda). "
    "Exija de si, em cada ponto:\n"
    "- CAUSA RAIZ: o mecanismo psicológico/comercial REAL de por que funciona — não o que é.\n"
    "- EVIDÊNCIA DIRETA: cite trechos/números/frases exatas DO conteúdo (aspas curtas), nunca paráfrase vaga.\n"
    "- PADRÃO OCULTO e ANTI-PADRÃO: o que a maioria copia errado; a alavanca não-óbvia que poucos veem.\n"
    "- IMPACTO/DOR: número concreto, dor específica do público, custo de NÃO fazer.\n"
    "- APLICAÇÃO ao JP: onde encaixa (noemi/motor-site/motor-b/arbitragem) e o passo concreto pra replicar.\n"
    "PROIBIDO: clichê de IA ('é importante ressaltar', 'no cenário atual', 'em resumo'), frase de efeito "
    "vazia, platitude ('conteúdo de qualidade', 'engajar o público'). Se um ponto NÃO tem evidência no "
    "conteúdo, escreva 'sem evidência' — não invente. FUSÃO DE SINAIS: TELA > LEGENDA > ÁUDIO se divergirem."
)

# PASS 2 — estrutura a análise densa nos 10 campos, preservando evidência/mecânica/número.
_PROMPT_BASE = (
    "Estruture a ANÁLISE (Pass 1) abaixo nos 14 campos JSON, PRESERVANDO a densidade: cada campo com "
    "detalhe concreto, evidência/citação do conteúdo, mecânica real e número/dor quando houver. "
    "PROIBIDO clichê, frase vazia ou resumo raso. NÃO invente além da análise/conteúdo.\n"
    "Responda SOMENTE JSON válido com EXATAMENTE estas 14 chaves:\n"
    '"resumo" (1 frase densa: a sacada central + o mecanismo, não o tema), '
    f'"categoria" (um de {sorted(CATEGORIAS)}), '
    '"estrutura_narrativa" (lista de objetos {"beat":"gancho|desenvolvimento|virada|prova|cta",'
    '"o_que":"o que acontece nesse trecho"} — sem timestamp real, use o beat), '
    f'"tecnicas_persuasao" (subconjunto EXATO de {list(PERSUASAO)} — só as presentes), '
    '"objecoes_tratadas" (lista de objeções que o vídeo antecipa/derruba), '
    '"promessa_vs_entrega" (objeto {"promessa":"o que promete","entrega":"o que mostra",'
    '"gap":"lacuna se houver"}), '
    '"score_replicabilidade" (inteiro 0-10 de quão fácil replicar no negócio do JP), '
    '"hooks" (lista de frases/ângulos de abertura reutilizáveis, verbatim ou adaptados), '
    '"ctas" (lista de chamadas pra ação reutilizáveis), '
    f'"aplicar_em" (subconjunto EXATO de {sorted(MOTORES)} — arbitragem=garimpo/revenda, '
    'motor-site=sites, motor-b=vídeo, noemi=SDR/WhatsApp; [] se nenhum, NÃO chute), '
    '"assinatura_tema" (3-6 palavras-chave normalizadas do tema central, pra deduplicar), '
    # cam.1/3/4 (Radar Omnisciente): vertical do negócio + ângulo de marketing + ferramentas + templates.
    f'"vertical" (a vertical/nicho do negócio no vídeo — encaixe em {sorted(VERTICAIS)} OU devolva um nome novo; "" se não der pra dizer), '
    '"marketing" (objeto {"angulo":"a promessa/ângulo central","hook":"o gancho de abertura","oferta":"a oferta se houver","cta":"a chamada"} — deixe "" o que não houver), '
    '"ferramentas" (lista de ferramentas/produtos/apps citados por NOME próprio, ex: Shopify, Canva; [] se nenhum), '
    '"modelos" (objeto {dominio: "template replicável de 1 linha"} com dominios de '
    '["video","site","negocio","produto","operacao","projeto"] — só os que casam; {} se nenhum). '
    "REGRAS: só o que está no conteúdo (não invente). tecnicas_persuasao e aplicar_em SÓ valores das listas."
)


def _hist_pedido(contexto: list[dict], instrucao: str) -> tuple[str, str]:
    hist = ""
    if contexto:
        linhas = [f"- [{a.get('categoria','?')}/{a.get('score','?')}] {a.get('origem','?')}: "
                  f"{(a.get('resumo_curto') or '').strip()[:160]}" for a in contexto]
        hist = "\n\nHISTÓRICO (análises anteriores relevantes):\n" + "\n".join(linhas)
    pedido = ""
    if instrucao and instrucao.strip():
        pedido = (f"\n\n⚠️ O JP PEDIU ISTO (foque a análise nisso, concreto): "
                  f"\"{instrucao.strip()[:400]}\"")
    return hist, pedido


def _prompt_analise(transcricao: str, contexto: list[dict], instrucao: str = "") -> str:
    """PASS 1 — raciocínio profundo (prosa densa)."""
    hist, pedido = _hist_pedido(contexto, instrucao)
    return f"{_PROMPT_ANALISE}{pedido}{hist}\n\nCONTEÚDO (TELA/LEGENDA/ÁUDIO):\n{transcricao[:9000]}"


def _prompt_estrutura(analise: str, transcricao: str, instrucao: str = "") -> str:
    """PASS 2 — estrutura a análise densa (+ conteúdo p/ evidência) nos 10 campos."""
    _, pedido = _hist_pedido([], instrucao)
    return (f"{_PROMPT_BASE}{pedido}\n\nANÁLISE (Pass 1):\n{analise[:6000]}"
            f"\n\nCONTEÚDO ORIGINAL (pra citação/evidência):\n{transcricao[:4000]}")


# dict base com TODAS as chaves (novas + antigas) vazias — garante retrocompat:
# _expandir/harvest_ideias leem as antigas sem KeyError; análises novas as trazem vazias.
_INSIGHT_VAZIO = {
    "insight": "", "resumo": "", "categoria": "outro", "score": 0, "tags": [], "fonte": "extrativo",
    "estrutura_narrativa": [], "tecnicas_persuasao": [], "objecoes_tratadas": [],
    "promessa_vs_entrega": {}, "hooks": [], "ctas": [], "aplicar_em": [], "assinatura_tema": "",
    "onde_usar": [], "verticais": [], "axioma": "", "assimilacao": "", "comparacao": "",
    "modelos": {}, "motores": [], "vertical": "", "vertical_nova": False,
    "marketing": {}, "ferramentas": [],
}


def _insight(transcricao: str, contexto: list[dict], instrucao: str = "") -> dict:
    """LLM (via proxy sancionado, com retry) → dict validado. Degrada pra resumo
    extrativo se o proxy estiver fora — nunca crasha a análise."""
    from shared_core.ai import llm_proxy

    def _call(prompt: str, mt: int, temp: float):  # Groq → Claude direto (TPD diário do Groq é comum)
        t = llm_proxy.completar(prompt, model="analise", max_tokens=mt, temperature=temp)
        if not t:
            t = llm_proxy.completar(prompt, model="fallback-anthropic", max_tokens=mt, temperature=temp)
        return t

    # TWO-PASS: pass 1 = raciocínio profundo (prosa densa, temp maior p/ ângulos não-óbvios);
    # pass 2 = estrutura nos 10 campos (temp baixa, fiel). Eleva a profundidade vs 1-pass.
    analise = _call(_prompt_analise(transcricao, contexto, instrucao), 1400, 0.45)
    fonte_base = analise or transcricao  # se pass 1 falhar, estrutura direto do conteúdo
    txt = _call(_prompt_estrutura(fonte_base, transcricao, instrucao), 2200, 0.2)
    bruto = _extrair_json(txt) if txt else None
    if not bruto:  # proxy fora / saída ilegível → resumo extrativo honesto
        frase = re.split(r"(?<=[.!?])\s+", transcricao.strip())[:2]
        resumo = (frase[0] if frase else "")[:200]
        return {**_INSIGHT_VAZIO, "insight": " ".join(frase)[:400] or "(sem insight — LLM indisponível)",
                "resumo": resumo, "fonte": "extrativo"}

    def _lista(v, n=8, cap=200):
        return [str(x).strip()[:cap] for x in v if str(x).strip()][:n] if isinstance(v, list) else []

    def _aplicar(v):  # subconjunto válido de MOTORES, sem duplicar
        out: list[str] = []
        for x in (v if isinstance(v, list) else []):
            m = str(x).strip().lower().replace("_", "-")
            if m in MOTORES and m not in out:
                out.append(m)
        return out

    cat = str(bruto.get("categoria", "outro")).strip().lower()
    cat = {"operacao": "operação"}.get(cat, cat)  # o LLM quase sempre tira o acento → não perder a categoria
    try:
        score = max(0, min(10, int(bruto.get("score_replicabilidade", 0))))
    except (TypeError, ValueError):
        score = 0
    # anti sobre-análise: input muito pobre (ex: "Hey, cheese") não merece score alto por mais
    # denso que o LLM escreva. Mede o conteúdo REAL, sem os rótulos de fusão → teto baixo.
    _conteudo = re.sub(r"(LEGENDA/TÍTULO:|TRANSCRIÇÃO DO ÁUDIO:|O QUE APARECE NA TELA \(visão\):)",
                       "", transcricao or "").strip()
    if len(_conteudo) < 90:
        score = min(score, 3)
    persuasao = [t for t in (str(x).strip().lower() for x in (bruto.get("tecnicas_persuasao") or []))
                 if t in _PERSUASAO_SET][:14]
    estrut = [{"beat": str(x.get("beat", ""))[:20], "o_que": str(x.get("o_que", ""))[:200]}
              for x in (bruto.get("estrutura_narrativa") or []) if isinstance(x, dict)][:8]
    pve_in = bruto.get("promessa_vs_entrega") if isinstance(bruto.get("promessa_vs_entrega"), dict) else {}
    pve = {k: str(pve_in.get(k, "")).strip()[:200] for k in ("promessa", "entrega", "gap")}
    resumo = str(bruto.get("resumo", "")).strip()[:200]
    _ass = bruto.get("assinatura_tema", "")  # o LLM às vezes devolve LISTA — junta em vez de str(list)
    if isinstance(_ass, list):
        _ass = ", ".join(str(x).strip() for x in _ass if str(x).strip())
    assinatura = str(_ass).strip()[:120]
    aplicar = _aplicar(bruto.get("aplicar_em"))
    # cam.1/3/4 (restauradas — a regressão do two-pass tinha deixado de extrair estas):
    vert = str(bruto.get("vertical", "")).strip().lower().replace(" ", "_")
    vertical_nova = bool(vert) and vert not in VERTICAIS  # nome fora do catálogo => vertical nova
    _mkt = bruto.get("marketing") if isinstance(bruto.get("marketing"), dict) else {}
    marketing = {k: str(_mkt.get(k, "")).strip()[:200]
                 for k in ("angulo", "hook", "oferta", "cta") if str(_mkt.get(k, "")).strip()}
    ferramentas = _lista(bruto.get("ferramentas"), n=12, cap=60)
    _mods = bruto.get("modelos") if isinstance(bruto.get("modelos"), dict) else {}
    modelos = {d: str(_mods.get(d, "")).strip()[:200] for d in _DOMINIOS if str(_mods.get(d, "")).strip()}
    return {**_INSIGHT_VAZIO,
            # colunas do banco (retrocompat): insight/categoria/score/tags
            "insight": resumo or "(sem insight)",
            "categoria": cat if cat in CATEGORIAS else "outro",
            "score": score,
            "tags": (persuasao[:6] or assinatura.lower().replace(",", " ").split()[:6]),
            "fonte": "llm",
            # schema NOVO de 10 campos
            "resumo": resumo, "estrutura_narrativa": estrut, "tecnicas_persuasao": persuasao,
            "objecoes_tratadas": _lista(bruto.get("objecoes_tratadas")), "promessa_vs_entrega": pve,
            "hooks": _lista(bruto.get("hooks")), "ctas": _lista(bruto.get("ctas")),
            "aplicar_em": aplicar, "assinatura_tema": assinatura,
            "motores": aplicar,  # 'motores' segue preenchido (retrocompat do roteamento)
            # cam.1/3/4 restauradas — a Caixa de Ideias (harvest_ideias) volta a receber estes:
            "vertical": vert, "vertical_nova": vertical_nova, "marketing": marketing,
            "ferramentas": ferramentas, "modelos": modelos}


def _bloco_balanceado(texto: str, i: int) -> str | None:
    """1º objeto {...} balanceado a partir de i, ignorando chaves dentro de strings."""
    prof = 0
    em_str = esc = False
    for j in range(i, len(texto)):
        ch = texto[j]
        if em_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                em_str = False
            continue
        if ch == '"':
            em_str = True
        elif ch == "{":
            prof += 1
        elif ch == "}":
            prof -= 1
            if prof == 0:
                return texto[i:j + 1]
    return None


def _extrair_json(texto: str) -> dict | None:
    texto = texto or ""
    # Modelos de RACIOCÍNIO (qwen3.x, deepseek-r1...) emitem <think>…</think> antes da
    # resposta. Esse bloco tem chaves e aspas, então o extrator guloso engolia o
    # raciocínio no lugar do JSON e devolvia None — a análise virava "extrativo,
    # score 0". Some com o raciocínio ANTES de procurar o objeto.
    if "<think>" in texto:
        texto = re.sub(r"<think>.*?</think>", "", texto, flags=re.S)
        texto = re.sub(r"<think>.*$", "", texto, flags=re.S)  # truncado por max_tokens
    i = texto.find("{")
    if i < 0:
        return None
    # guloso primeiro (cobre o caso normal de 1 objeto); se falhar, pega o 1º objeto
    # BALANCEADO — resolve prosa-depois-do-json e "dois objetos" (guloso engoliria os dois).
    g = re.search(r"\{.*\}", texto, re.S)
    for cand in ((g.group(0) if g else None), _bloco_balanceado(texto, i)):
        if not cand:
            continue
        try:
            d = json.loads(cand)
            if isinstance(d, dict):
                return d
        except (ValueError, TypeError):
            continue
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


def quota_ok() -> tuple[bool, str]:
    """#4 — o LLM responde AGORA? Checagem barata (1 chamada minúscula) ANTES de
    gastar download + transcrição numa análise que já nasceria degradada.

    Mede o que importa: não é "a chave existe", é "o provider aceita trabalho".
    True em qualquer dúvida — pré-checagem NUNCA pode ser o motivo de não analisar."""
    try:
        from shared_core.ai import llm_proxy
        t = llm_proxy.completar("ok", model="analise", max_tokens=5, temperature=0)
        return (True, "ok") if t else (False, "LLM sem resposta (cota/provider fora)")
    except Exception as e:  # noqa: BLE001
        return True, f"pré-checagem falhou ({type(e).__name__}) — segue mesmo assim"


def analisar(url: str, origem: str | None = None, instrucao: str = "",
             forcar: bool = False) -> dict:
    """Pipeline por URL: baixa → transcreve → contexto → insight → GRAVA.
    `instrucao` = pedido do JP na legenda (replicar/adaptar/comparar). `forcar`=True
    reanalisa mesmo se a URL já existe (senão devolve a análise anterior — economia)."""
    from shared_core.ai import transcricao as trans
    from shared_core.ai import visao
    url = _limpar_url((url or "").strip())  # (1) higiene
    if not url.startswith("http"):
        raise ValueError("url inválida")
    if not forcar:  # (2) dedup: não regasta LLM num link já analisado
        ja = _ja_analisada(url)
        if ja:
            return {**ja, "reaproveitada": True}
    origem_dada = (origem or "").strip()
    legenda, handle = _metadados(url)  # caption/título — funciona mesmo quando a mídia não baixa
    texto_audio, visao_txt = "", ""
    with tempfile.TemporaryDirectory(prefix="radar_") as td:
        try:
            # VISÃO NO CAMINHO DE URL: baixa o VÍDEO (1 download) e tira dele os frames
            # E o áudio. Antes vinha só o áudio (-x), então todo link perdia o que está
            # na TELA — e a tela é a fonte do nome do produto/preço (áudio pode ser música).
            video = _baixar_video(url, Path(td))
            origem = origem_dada or _conta_do_dir(Path(td)) or handle or _origem_da_url(url)
            visao_txt, _fv = visao.analisar_frames(_frames(str(video), Path(td)))
            if a := _audio_do_video(video, Path(td)):
                texto_audio = trans.transcrever(str(a)) or ""
        except RuntimeError:
            # vídeo bloqueado → tenta o caminho antigo (só áudio); depois só legenda.
            try:
                audio = _baixar_audio(url, Path(td))
                origem = origem_dada or _conta_do_dir(Path(td)) or handle or _origem_da_url(url)
                texto_audio = trans.transcrever(str(audio))
            except RuntimeError as e:
                # IG/YT bloqueou a mídia → NÃO morre: segue com a legenda (análise sempre).
                origem = origem_dada or handle or _origem_da_url(url)
                if not legenda:
                    registrar_job(False, origem=origem, url=url, motivo=f"sem mídia nem legenda: {e}")
                    raise RuntimeError(f"não deu pra baixar o vídeo nem ler a legenda: {e}")
    # legenda (nome do produto/oferta) + transcrição (narração) → análise fiel, sem
    # confundir música de fundo com o produto (a legenda é a âncora do "o quê").
    # mesma combinação rotulada do caminho de arquivo: visão + legenda + áudio
    texto = _combinar(visao_txt, legenda, texto_audio)
    if not texto.strip():
        registrar_job(False, origem=origem, url=url, motivo="sem transcrição e sem legenda")
        raise RuntimeError("sem transcrição e sem legenda — link privado/inacessível")
    res = _processar(texto, origem, url, instrucao)
    registrar_job(bool(res.get("id")), origem=origem, url=url,
                  motivo="" if res.get("fonte") == "llm" else f"degradado ({res.get('fonte')})")
    return res


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
                          ("resumo", "estrutura_narrativa", "tecnicas_persuasao", "objecoes_tratadas",
                           "promessa_vs_entrega", "hooks", "ctas", "aplicar_em", "assinatura_tema",
                           "pedido", "fonte", "fonte_tipo",
                           "onde_usar", "verticais", "axioma", "assimilacao", "comparacao",
                           "modelos", "motores", "vertical", "vertical_nova", "marketing", "ferramentas")},
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
                       # `fonte`: llm = analisado de verdade | extrativo = o LLM estava
                       # FORA e isto é só um resumo. Sem expor isto, score 0 por falha de
                       # LLM ficava idêntico a "vídeo ruim" — foi o que enganou o JP.
                       "fonte",
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


def harvest_ideias_csv(limite: int = 300) -> str:
    """CSV da Caixa de Ideias com UTF-8 BOM (abre certo no Excel PT-BR, sem quebrar
    acento). Achata `grupos` (ideias por domínio, a fonte canônica) + `ferramentas`
    (produtos candidatos). Reusa harvest_ideias — zero query extra. `por_motor` fica de
    fora de propósito: é o MESMO dado roteado, duplicaria linha."""
    import csv
    import io
    dados = harvest_ideias(limite)
    buf = io.StringIO()
    buf.write("﻿")  # BOM: Excel PT-BR abre com acento certo
    w = csv.writer(buf)
    w.writerow(["tipo", "grupo", "ideia", "mencoes", "origem", "url", "data", "score", "analise_id"])
    for dom, itens in (dados.get("grupos") or {}).items():
        for i in itens:
            w.writerow(["ideia", dom, i.get("ideia", ""), "", i.get("origem", ""),
                        i.get("url", ""), (i.get("data") or "")[:10], i.get("score", ""), i.get("aid", "")])
    for f in (dados.get("ferramentas") or []):
        w.writerow(["ferramenta", "produto_candidato", f.get("nome", ""), f.get("mencoes", ""),
                    f.get("origem", ""), f.get("url", ""), (f.get("data") or "")[:10],
                    f.get("score", ""), f.get("aid", "")])
    return buf.getvalue()


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


if __name__ == "__main__":  # self-check: helpers + sanitização + degradação (100% offline)
    import shared_core.ai.llm_proxy as _lp
    _orig = _lp.completar

    # 1) helpers puros (sem rede)
    assert _origem_da_url("https://www.instagram.com/reel/ABC/") == "instagram.com" or \
           _origem_da_url("https://www.instagram.com/lojax/reel/ABC/") == "@lojax"
    assert _extrair_json('lixo {"a":1} fim') == {"a": 1}
    assert _extrair_json('{"a":1} lixo {"b":2}') == {"a": 1}          # item #12: pega o 1º objeto balanceado
    assert _extrair_json('{"t":"tem } dentro de string"}') == {"t": "tem } dentro de string"}  # ignora } em string

    # 2) DEGRADADO — proxy fora (completar→None): resumo extrativo honesto, score 0, nada roteado.
    _lp.completar = lambda *a, **k: None
    try:
        d = _insight("Primeira frase. Segunda frase. Terceira.", [])
    finally:
        _lp.completar = _orig
    assert d["fonte"] == "extrativo" and d["score"] == 0, d        # degradado NÃO inventa score
    assert d["categoria"] in CATEGORIAS and d["motores"] == [] and d["aplicar_em"] == [], d
    assert d["vertical"] == "" and d["vertical_nova"] is False and d["ferramentas"] == [], d

    # 3) HAPPY PATH — fake JSON no schema de 10 campos do Pass 2: valida a sanitização real.
    _fake10 = ('{"resumo":"a sacada + o mecanismo","categoria":"INVALIDA","score_replicabilidade":99,'
               '"tecnicas_persuasao":["escassez","inexistente","URGENCIA"],'
               '"estrutura_narrativa":[{"beat":"gancho","o_que":"abre"},"lixo"],'
               '"objecoes_tratadas":["obj 1"],'
               '"promessa_vs_entrega":{"promessa":"p","entrega":"e","gap":"g"},'
               '"hooks":["Comment the word edit"],"ctas":["cta reutilizável"],'
               '"aplicar_em":["arbitragem","MOTOR_SITE","inexistente","arbitragem"],'
               '"assinatura_tema":["tema-a","tema-b"],'
               '"vertical":"Odontologia","marketing":{"angulo":"medo de perder cliente",'
               '"hook":"3s","oferta":"","cta":"chama no zap"},"ferramentas":["Shopify","Ruflo"],'
               '"modelos":{"site":"landing de leilão","negocio":"revende com 30%","xpto":"ignora"}}')
    _lp.completar = lambda *a, **k: _fake10
    _longo = ("conteúdo real longo o suficiente pra não disparar a guarda de input pobre do radar "
              "aqui, com bastante texto de sobra pra passar do piso de 90 caracteres com folga")
    try:
        r = _insight(_longo, [])
    finally:
        _lp.completar = _orig
    assert r["fonte"] == "llm", r
    assert r["categoria"] == "outro", r["categoria"]                        # categoria fora do set → outro
    assert r["score"] == 10, r["score"]                                     # clamp 0-10 (99→10)
    assert r["tecnicas_persuasao"] == ["escassez", "urgencia"], r["tecnicas_persuasao"]  # filtra+normaliza
    assert r["aplicar_em"] == ["arbitragem", "motor-site"], r["aplicar_em"]  # dedup+whitelist+normaliza
    assert r["motores"] == r["aplicar_em"], r                               # motores espelha aplicar_em
    assert r["estrutura_narrativa"] == [{"beat": "gancho", "o_que": "abre"}], r["estrutura_narrativa"]  # dropa não-dict
    assert r["hooks"] == ["Comment the word edit"] and r["ctas"] == ["cta reutilizável"], r
    assert r["promessa_vs_entrega"] == {"promessa": "p", "entrega": "e", "gap": "g"}, r["promessa_vs_entrega"]
    assert r["assinatura_tema"] == "tema-a, tema-b", r["assinatura_tema"]  # LISTA vira string juntada, não str(list)
    # cam.1/3/4 RESTAURADAS (item #1): vertical catalogada, marketing sem campo vazio,
    # ferramentas por nome, modelos só nos domínios válidos (dominio inexistente 'xpto' cai fora).
    assert r["vertical"] == "odontologia" and r["vertical_nova"] is False, r["vertical"]
    assert r["marketing"] == {"angulo": "medo de perder cliente", "hook": "3s", "cta": "chama no zap"}, r["marketing"]
    assert r["ferramentas"] == ["Shopify", "Ruflo"], r["ferramentas"]
    assert r["modelos"] == {"site": "landing de leilão", "negocio": "revende com 30%"}, r["modelos"]
    # vertical fora do catálogo => vertical_nova=True
    _lp.completar = lambda *a, **k: '{"resumo":"y","categoria":"produto","score_replicabilidade":3,"vertical":"petshop"}'
    try:
        r2 = _insight("q", [])
    finally:
        _lp.completar = _orig
    assert r2["vertical"] == "petshop" and r2["vertical_nova"] is True, r2
    # categoria sem acento do LLM ("Operacao") é restaurada pra "operação" (item #3)
    _lp.completar = lambda *a, **k: '{"resumo":"z","categoria":"Operacao","score_replicabilidade":5}'
    try:
        r3 = _insight("q", [])
    finally:
        _lp.completar = _orig
    assert r3["categoria"] == "operação", r3["categoria"]
    # item #8: input pobre ("Hey, cheese") não vira score alto por mais denso que o LLM escreva
    _lp.completar = lambda *a, **k: '{"resumo":"denso","categoria":"marketing","score_replicabilidade":9}'
    try:
        r4 = _insight("LEGENDA/TÍTULO: pop\nTRANSCRIÇÃO DO ÁUDIO: Hey, cheese.", [])
    finally:
        _lp.completar = _orig
    assert r4["fonte"] == "llm" and r4["score"] <= 3, r4["score"]

    # 4) harvest agrupa por motor usando o template de domínio que casa
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
          "· sanitização 10-campos + harvest + fronteira adapter OK")
