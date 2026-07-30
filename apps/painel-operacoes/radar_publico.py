"""Radar Grátis — versão pública self-serve do Radar (diferencial JPOS de marketing).

A pessoa baixa o vídeo (ex: SnapTube) e SOBE o arquivo — sem link/cookies. Reusa as
peças puras do motor (`radar._frames/_combinar/_insight` + transcrição/visão) SEM
gravar no histórico curado do JP e SEM injetar contexto de outros usuários (isolado).

Guards de endpoint público: cap de tamanho (no main), 10 análises/dia GLOBAL + trava
por IP. Cada uso vira um lead (email + insight) em `radar_publico_leads`.
"""
from __future__ import annotations

import os
import re
import sqlite3
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path

LIMITE_DIA_GLOBAL = 10   # teu limite: 10 grátis por dia no total (escassez + custo travado)
LIMITE_DIA_IP = 3        # anti-flood: uma pessoa não queima as 10 vagas sozinha
MAX_BYTES = 15 * 1024 * 1024  # 15MB — comunicado na cara na página


def _db() -> sqlite3.Connection:
    p = Path(os.environ.get("LEADS_DB", str(Path(__file__).resolve().parents[2] / "data" / "leads.db")))
    p.parent.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(p, timeout=10)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA journal_mode=WAL")
    c.execute("""CREATE TABLE IF NOT EXISTS radar_publico_leads (
        id INTEGER PRIMARY KEY AUTOINCREMENT, email TEXT, ip TEXT, dia TEXT,
        insight TEXT, categoria TEXT, score REAL, criado_em TEXT)""")
    c.commit()
    return c


def _hoje() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def pode_usar(ip: str) -> dict:
    """Portão: retorna {ok} ou {ok:False, erro, esgotou_dia} antes de gastar LLM."""
    dia = _hoje()
    with _db() as c:
        total = c.execute("SELECT COUNT(*) FROM radar_publico_leads WHERE dia=?", (dia,)).fetchone()[0]
        por_ip = c.execute("SELECT COUNT(*) FROM radar_publico_leads WHERE dia=? AND ip=?",
                           (dia, ip or "?")).fetchone()[0]
    if total >= LIMITE_DIA_GLOBAL:
        return {"ok": False, "esgotou_dia": True,
                "erro": f"As {LIMITE_DIA_GLOBAL} análises grátis de hoje já foram usadas. Volte amanhã 🙌"}
    if por_ip >= LIMITE_DIA_IP:
        return {"ok": False, "erro": f"Você já usou {LIMITE_DIA_IP} análises hoje. Volte amanhã."}
    return {"ok": True, "restantes": LIMITE_DIA_GLOBAL - total}


def registrar_uso(email: str, ip: str, resultado: dict) -> int:
    with _db() as c:
        cur = c.execute("INSERT INTO radar_publico_leads (email,ip,dia,insight,categoria,score,criado_em) "
                        "VALUES (?,?,?,?,?,?,?)",
                        (str(email or "")[:160], str(ip or "")[:60], _hoje(),
                         str(resultado.get("insight") or "")[:2000], str(resultado.get("categoria") or "")[:60],
                         resultado.get("score"), datetime.now(timezone.utc).isoformat()))
        c.commit()
        return cur.lastrowid


def analisar(video_path: str) -> dict:
    """Vídeo local → insight/score/categoria. Reusa o motor SEM gravar/contexto."""
    import radar  # peças puras do motor (mesma pasta)
    from shared_core.ai import transcricao as trans
    from shared_core.ai import visao
    texto_audio, visao_txt = "", ""
    with tempfile.TemporaryDirectory(prefix="radarpub_") as td:
        audio = Path(td) / "audio.mp3"
        try:
            subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", video_path,
                            "-vn", "-acodec", "libmp3lame", "-q:a", "4", str(audio)],
                           check=True, capture_output=True, timeout=120)
            texto_audio = trans.transcrever(str(audio)) or ""
        except Exception:  # vídeo mudo/áudio ruim: a visão carrega
            texto_audio = ""
        try:
            visao_txt, _ = visao.analisar_frames(radar._frames(video_path, Path(td)))
        except Exception:
            visao_txt = ""
    texto = radar._combinar(visao_txt, "", texto_audio)
    if not texto.strip():
        raise RuntimeError("Não consegui ler áudio nem imagem do vídeo — tente outro arquivo.")
    r = radar._insight(texto, contexto=[], instrucao="")  # sem histórico de terceiros
    return {"insight": r.get("insight", ""), "categoria": r.get("categoria", ""),
            "score": r.get("score"), "tags": r.get("tags", []),
            "modelos": r.get("modelos") or r.get("modelo") or {}}


def leads(limite: int = 100) -> list[dict]:
    """Quem usou o Radar Grátis (leads mornos / prova social) — pro painel do JP."""
    with _db() as c:
        rows = c.execute("SELECT * FROM radar_publico_leads ORDER BY id DESC LIMIT ?", (limite,)).fetchall()
    return [dict(r) for r in rows]


if __name__ == "__main__":  # self-check dos GUARDS (sem rede/LLM): DB temporário
    os.environ["LEADS_DB"] = tempfile.mktemp()
    assert pode_usar("1.1.1.1")["ok"] is True
    # per-IP: após LIMITE_DIA_IP usos do mesmo IP, barra
    for i in range(LIMITE_DIA_IP):
        registrar_uso(f"a{i}@x.com", "1.1.1.1", {"insight": "x", "score": 8})
    assert pode_usar("1.1.1.1")["ok"] is False  # IP estourou
    assert pode_usar("2.2.2.2")["ok"] is True   # outro IP ainda pode
    # global: enche até 10 no total (com IPs variados)
    for i in range(LIMITE_DIA_GLOBAL - LIMITE_DIA_IP):
        registrar_uso(f"b{i}@x.com", f"9.9.9.{i}", {"insight": "y", "score": 7})
    r = pode_usar("3.3.3.3")
    assert r["ok"] is False and r.get("esgotou_dia") is True  # dia esgotado global
    assert len(leads()) == LIMITE_DIA_GLOBAL
    print("radar_publico OK — guard per-IP + global/dia, registro de lead, contagem")
