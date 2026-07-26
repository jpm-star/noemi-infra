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


def _baixar_audio(link: str, destino: Path) -> Path:
    """Só o áudio em mp3. Drive tem caminho próprio (yt-dlp não baixa Drive /view);
    IG/YT usam yt-dlp com cookies (RADAR_COOKIES) — sem login, IG/YT dão 403. Erro claro."""
    if "drive.google.com" in link:
        return _baixar_drive(link, destino)
    saida = destino / "audio.%(ext)s"
    # --write-info-json: guarda o metadado (autor/conta) do post junto do áudio
    cmd = ["yt-dlp", "-x", "--audio-format", "mp3", "--no-playlist",
           "--write-info-json", "-o", str(saida)]
    cookies = os.environ.get("RADAR_COOKIES", "/root/noemi-infra/infra/cookies.txt")
    if cookies and Path(cookies).exists():
        cmd += ["--cookies", cookies]
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
    "Responda SOMENTE JSON com as chaves:\n"
    '"insight" (2-4 frases acionáveis — a sacada central, conectando com o histórico), '
    '"resumo" (1 frase), '
    '"onde_usar" (lista de 2-4 usos concretos no negócio do JP: ex "abertura de prospecção", '
    '"copy de anúncio", "script da Noemi", "post"), '
    '"verticais" (lista de nichos onde aplica: ex "odontologia", "estética", "imobiliária"), '
    '"axioma" (1 frase — o princípio atemporal por trás da dica), '
    '"assimilacao" (1 frase — o próximo passo concreto pra ABSORVER isso no sistema/operação), '
    '"comparacao" (1 frase — como se relaciona com o histórico: reforça? contradiz? é novo?), '
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
                "onde_usar": [], "verticais": [], "axioma": "", "assimilacao": "", "comparacao": ""}
    cat = str(bruto.get("categoria", "outro")).strip().lower()
    try:
        score = max(1, min(5, int(bruto.get("score", 1))))
    except (TypeError, ValueError):
        score = 1

    def _lista(v):
        return [str(x).strip()[:40] for x in v if str(x).strip()][:5] if isinstance(v, list) else []
    return {"insight": str(bruto.get("insight", "")).strip()[:1200] or "(sem insight)",
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


def analisar(url: str, origem: str | None = None, instrucao: str = "") -> dict:
    """Pipeline por URL: baixa → transcreve → contexto → insight → GRAVA.
    `instrucao` = pedido do JP na legenda (replicar/adaptar/comparar) — o LLM
    responde ISSO especificamente em vez do digest genérico."""
    from shared_core.ai import transcricao as trans
    url = (url or "").strip()
    if not url.startswith("http"):
        raise ValueError("url inválida")
    origem_dada = (origem or "").strip()
    with tempfile.TemporaryDirectory(prefix="radar_") as td:
        audio = _baixar_audio(url, Path(td))
        # a conta/autor REAL vem do metadado do download (yt-dlp), não da URL —
        # é o que auto-agrupa por concorrente. Origem explícita do JP tem prioridade.
        origem = origem_dada or _conta_do_dir(Path(td)) or _origem_da_url(url)
        texto = trans.transcrever(str(audio))
    if not texto:
        raise RuntimeError("transcrição falhou (sem chave Groq ou áudio ilegível)")
    return _processar(texto, origem, url, instrucao)


def analisar_arquivo(caminho: str, origem: str = "telegram", url_ref: str = "",
                     instrucao: str = "") -> dict:
    """Pipeline por ARQUIVO local (vídeo/áudio já baixado — ex: enviado no Telegram,
    sem bot-detection de IG/YT). Extrai áudio → transcreve → insight → GRAVA."""
    from shared_core.ai import transcricao as trans
    with tempfile.TemporaryDirectory(prefix="radar_") as td:
        audio = Path(td) / "audio.mp3"
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", caminho,
                        "-vn", "-acodec", "libmp3lame", "-q:a", "4", str(audio)],
                       check=True, capture_output=True, timeout=180)
        texto = trans.transcrever(str(audio))
    if not texto:
        raise RuntimeError("transcrição falhou (áudio ilegível ou sem chave Groq)")
    return _processar(texto, origem, url_ref, instrucao)


def _processar(texto: str, origem: str, url: str, instrucao: str = "") -> dict:
    """Núcleo compartilhado: contexto → insight → grava → devolve."""
    from shared_core.storage import db
    contexto = _contexto_anterior(origem)
    ins = _insight(texto, contexto, instrucao)
    data = datetime.now(timezone.utc).isoformat()
    detalhe = json.dumps({k: ins.get(k) for k in
                          ("onde_usar", "verticais", "axioma", "assimilacao", "comparacao", "fonte")},
                         ensure_ascii=False)
    with db.conn() as c:
        cur = c.execute(
            "INSERT INTO video_analises (origem, url, data, transcricao, insight, categoria, score, tags, detalhe) "
            "VALUES (?,?,?,?,?,?,?,?,?)",
            (origem, url, data, texto, ins["insight"], ins["categoria"], ins["score"],
             ",".join(ins["tags"]), detalhe))
        c.commit()
        aid = cur.lastrowid
    return {"id": aid, "origem": origem, "url": url, "data": data,
            "transcricao": texto, "usou_contexto": len(contexto), **ins}


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
                      ("onde_usar", "verticais", "axioma", "assimilacao", "comparacao")})
    except (ValueError, TypeError):
        pass
    return d


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


if __name__ == "__main__":  # self-check: origem + json + degradação (sem rede)
    assert _origem_da_url("https://www.instagram.com/reel/ABC/") == "instagram.com" or \
           _origem_da_url("https://www.instagram.com/lojax/reel/ABC/") == "@lojax"
    assert _extrair_json('lixo {"a":1} fim') == {"a": 1}
    d = _insight("Primeira frase. Segunda frase. Terceira.", [])  # proxy provavelmente fora
    assert d["categoria"] in CATEGORIAS and 1 <= d["score"] <= 5, d
    print("radar OK — origem/json/insight degradado:", d["fonte"])
