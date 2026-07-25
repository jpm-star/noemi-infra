"""Histórico JPOS de prospecção — o JP anota cada approach: o que deu, objeções,
o que falou, próximo passo. Memória do funil na mão dele (não é o SDR automático).

Grava no leads.db (mesma base dos leads). Ao registrar, atualiza o status do lead
em leads_clinicas (ligado/agendado/fechado/hostil) pra o funil refletir na hora.
"""
from __future__ import annotations

import os
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

RESULTADOS = ("ligado", "respondeu", "agendou", "fechou", "recusou", "sem_resposta", "hostil")
# resultado do log → status no lead (só os que fazem sentido no funil)
_STATUS = {"ligado": "ligado", "respondeu": "ligado", "agendou": "agendado",
           "fechou": "fechado", "recusou": "descartado", "hostil": "hostil"}


def _db() -> sqlite3.Connection:
    p = Path(os.environ.get("LEADS_DB", str(Path(__file__).resolve().parents[2] / "data" / "leads.db")))
    p.parent.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(p, timeout=10)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA journal_mode=WAL")
    c.execute("""CREATE TABLE IF NOT EXISTS prospeccao_log (
        id INTEGER PRIMARY KEY AUTOINCREMENT, empresa TEXT, telefone TEXT, canal TEXT,
        resultado TEXT, objecao TEXT, o_que_falei TEXT, proximo_passo TEXT, criado_em TEXT)""")
    c.commit()
    return c


def registrar(d: dict) -> dict:
    """Grava 1 entrada do histórico + atualiza o status do lead. Saneia a entrada."""
    res = d.get("resultado") if d.get("resultado") in RESULTADOS else "ligado"
    tel = re.sub(r"\D", "", str(d.get("telefone") or ""))
    entrada = {
        "empresa": str(d.get("empresa") or "")[:120], "telefone": tel, "canal": str(d.get("canal") or "whatsapp")[:20],
        "resultado": res, "objecao": str(d.get("objecao") or "")[:500],
        "o_que_falei": str(d.get("o_que_falei") or "")[:1000], "proximo_passo": str(d.get("proximo_passo") or "")[:300],
        "criado_em": datetime.now(timezone.utc).isoformat()}
    with _db() as c:
        cur = c.execute("INSERT INTO prospeccao_log (empresa,telefone,canal,resultado,objecao,o_que_falei,proximo_passo,criado_em) "
                        "VALUES (?,?,?,?,?,?,?,?)", tuple(entrada.values()))
        # reflete no funil: atualiza o status do lead pelo telefone
        novo = _STATUS.get(res)
        if novo and tel:
            try:
                c.execute("UPDATE leads_clinicas SET status=? WHERE REPLACE(REPLACE(REPLACE(REPLACE(telefone,'(',''),')',''),'-',''),' ','') LIKE ?",
                          (novo, f"%{tel[-8:]}%"))
            except sqlite3.Error:
                pass
        c.commit()
        entrada["id"] = cur.lastrowid
    return entrada


def listar(q: str | None = None, limite: int = 60) -> list[dict]:
    """Histórico (mais recente primeiro), busca por empresa/objeção/nota."""
    with _db() as c:
        if q and q.strip():
            like = f"%{q.strip()}%"
            rows = c.execute("SELECT * FROM prospeccao_log WHERE empresa LIKE ? OR objecao LIKE ? "
                             "OR o_que_falei LIKE ? OR resultado LIKE ? ORDER BY id DESC LIMIT ?",
                             (like, like, like, like, limite)).fetchall()
        else:
            rows = c.execute("SELECT * FROM prospeccao_log ORDER BY id DESC LIMIT ?", (limite,)).fetchall()
    return [dict(r) for r in rows]


def resumo() -> dict:
    """Contagem por resultado (pro funil do histórico) — as objeções mais comuns."""
    with _db() as c:
        por_res = {r["resultado"]: r["n"] for r in c.execute(
            "SELECT resultado, COUNT(*) n FROM prospeccao_log GROUP BY resultado")}
        total = c.execute("SELECT COUNT(*) FROM prospeccao_log").fetchone()[0]
    return {"total": total, "por_resultado": por_res}


if __name__ == "__main__":  # self-check: registra, lista, resumo (sem tocar leads)
    import tempfile
    os.environ["LEADS_DB"] = str(Path(tempfile.mktemp()))
    r = registrar({"empresa": "Clínica X", "telefone": "(18) 99999-8888", "resultado": "recusou",
                   "objecao": "já tem secretária", "o_que_falei": "mostrei o custo/mês"})
    assert r["id"] and r["resultado"] == "recusou"
    assert listar("secretária")[0]["empresa"] == "Clínica X"
    assert resumo()["total"] == 1 and resumo()["por_resultado"]["recusou"] == 1
    print("proslog OK — registra approach, objeção, busca e resumo do funil")
