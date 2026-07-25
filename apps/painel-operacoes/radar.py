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
    """Só o áudio em mp3 via yt-dlp (reusa ffmpeg do host). Levanta em erro."""
    saida = destino / "audio.%(ext)s"
    subprocess.run(["yt-dlp", "-x", "--audio-format", "mp3", "--no-playlist",
                    "-o", str(saida), link],
                   check=True, capture_output=True, text=True, timeout=300)
    mp3s = list(destino.glob("*.mp3"))
    if not mp3s:
        raise RuntimeError("yt-dlp não gerou mp3")
    return mp3s[0]


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
    "Você é o Radar de Vídeo do JP (Noemi OS: SDR/IA no WhatsApp, geração de site/vídeo, "
    "growth, arbitragem). Dada a TRANSCRIÇÃO de um vídeo e o histórico de análises "
    "anteriores, gere um insight que CONECTE com o padrão já observado (o que se repete, "
    "o que muda, o que o concorrente/conta está fazendo).\n"
    "Responda SOMENTE JSON com as chaves: "
    '"insight" (2-4 frases acionáveis, conectando com o histórico quando houver), '
    '"resumo" (1 frase), '
    f'"categoria" (um de {sorted(CATEGORIAS)}), '
    '"score" (inteiro 1-5 de relevância pro JP), '
    '"tags" (lista de 3-6 palavras-chave em minúsculo).'
)


def _prompt(transcricao: str, contexto: list[dict]) -> str:
    hist = ""
    if contexto:
        linhas = [f"- [{a.get('categoria','?')}/{a.get('score','?')}] {a.get('origem','?')}: "
                  f"{(a.get('resumo_curto') or '').strip()[:160]}" for a in contexto]
        hist = "\n\nHISTÓRICO (análises anteriores relevantes):\n" + "\n".join(linhas)
    return f"{_PROMPT_BASE}{hist}\n\nTRANSCRIÇÃO:\n{transcricao[:9000]}"


def _insight(transcricao: str, contexto: list[dict]) -> dict:
    """LLM (via proxy sancionado, com retry) → dict validado. Degrada pra resumo
    extrativo se o proxy estiver fora — nunca crasha a análise."""
    from shared_core.ai import llm_proxy
    txt = llm_proxy.completar(_prompt(transcricao, contexto), model="analise",
                              max_tokens=500, temperature=0.3)
    bruto = _extrair_json(txt) if txt else None
    if not bruto:  # proxy fora / saída ilegível → resumo extrativo honesto
        frase = re.split(r"(?<=[.!?])\s+", transcricao.strip())[:2]
        return {"insight": " ".join(frase)[:400] or "(sem insight — LLM indisponível)",
                "resumo": (frase[0] if frase else "")[:160], "categoria": "outro",
                "score": 1, "tags": [], "fonte": "extrativo"}
    cat = str(bruto.get("categoria", "outro")).strip().lower()
    try:
        score = max(1, min(5, int(bruto.get("score", 1))))
    except (TypeError, ValueError):
        score = 1
    tags = bruto.get("tags") or []
    tags = [str(t).strip().lower()[:30] for t in tags if str(t).strip()][:6] if isinstance(tags, list) else []
    return {"insight": str(bruto.get("insight", "")).strip()[:1200] or "(sem insight)",
            "resumo": str(bruto.get("resumo", "")).strip()[:200],
            "categoria": cat if cat in CATEGORIAS else "outro",
            "score": score, "tags": tags, "fonte": "llm"}


def _extrair_json(texto: str) -> dict | None:
    m = re.search(r"\{.*\}", texto or "", re.S)
    if not m:
        return None
    try:
        d = json.loads(m.group(0))
        return d if isinstance(d, dict) else None
    except (ValueError, TypeError):
        return None


def analisar(url: str, origem: str | None = None) -> dict:
    """Pipeline completo: baixa → transcreve → contexto → insight → GRAVA. Levanta
    só se download/transcrição falharem totalmente (o caller vira erro HTTP)."""
    from shared_core.ai import transcricao as trans
    from shared_core.storage import db
    url = (url or "").strip()
    if not url.startswith("http"):
        raise ValueError("url inválida")
    origem = (origem or "").strip() or _origem_da_url(url)
    with tempfile.TemporaryDirectory(prefix="radar_") as td:
        audio = _baixar_audio(url, Path(td))
        texto = trans.transcrever(str(audio))
    if not texto:
        raise RuntimeError("transcrição falhou (sem chave Groq ou áudio ilegível)")
    contexto = _contexto_anterior(origem)
    ins = _insight(texto, contexto)
    data = datetime.now(timezone.utc).isoformat()
    with db.conn() as c:
        cur = c.execute(
            "INSERT INTO video_analises (origem, url, data, transcricao, insight, categoria, score, tags) "
            "VALUES (?,?,?,?,?,?,?,?)",
            (origem, url, data, texto, ins["insight"], ins["categoria"], ins["score"],
             ",".join(ins["tags"])))
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
                "SELECT id, origem, url, data, categoria, score, tags, "
                "substr(insight,1,300) insight FROM video_analises "
                "WHERE insight LIKE ? OR transcricao LIKE ? OR origem LIKE ? OR tags LIKE ? "
                "ORDER BY id DESC LIMIT ?", (like, like, like, like, limite)).fetchall()
        else:
            rows = c.execute(
                "SELECT id, origem, url, data, categoria, score, tags, "
                "substr(insight,1,300) insight FROM video_analises "
                "ORDER BY id DESC LIMIT ?", (limite,)).fetchall()
    return [dict(r) for r in rows]


def obter(aid: int) -> dict | None:
    from shared_core.storage import db
    with db.conn() as c:
        r = c.execute("SELECT * FROM video_analises WHERE id = ?", (aid,)).fetchone()
    return dict(r) if r else None


if __name__ == "__main__":  # self-check: origem + json + degradação (sem rede)
    assert _origem_da_url("https://www.instagram.com/reel/ABC/") == "instagram.com" or \
           _origem_da_url("https://www.instagram.com/lojax/reel/ABC/") == "@lojax"
    assert _extrair_json('lixo {"a":1} fim') == {"a": 1}
    d = _insight("Primeira frase. Segunda frase. Terceira.", [])  # proxy provavelmente fora
    assert d["categoria"] in CATEGORIAS and 1 <= d["score"] <= 5, d
    print("radar OK — origem/json/insight degradado:", d["fonte"])
