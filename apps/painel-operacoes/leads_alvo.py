"""Leads-alvo (sem site) no p.jpos — leitura + filtros sobre leads.db::leads_alvo.

leads_alvo = universo deduplicado, sem franquia, verificado por HTTP → só quem NÃO
tem site real (sem_website / social_only / site_morto). É a fila de WhatsApp/telefone.
leads_t3t4 = os COM email (majoritariamente já têm site) reservados pra tiers 3/4.

Read-only. Mesmo leads.db do tracker/proslog (env LEADS_DB, senão data/leads.db).
"""
from __future__ import annotations

import os
import sqlite3
from pathlib import Path

MOTIVOS = ("sem_website", "social_only", "site_morto")


def _db() -> sqlite3.Connection:
    p = Path(os.environ.get("LEADS_DB", str(Path(__file__).resolve().parents[2] / "data" / "leads.db")))
    c = sqlite3.connect(p, timeout=10)
    c.row_factory = sqlite3.Row
    return c


def _existe(c, tabela: str) -> bool:
    return c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (tabela,)).fetchone() is not None


def listar(motivo: str = "", categoria: str = "", cidade: str = "", tier: str = "",
           q: str = "", limite: int = 2000) -> list[dict]:
    """leads_alvo filtrado. Ordenado por dor (melhores primeiro)."""
    with _db() as c:
        if not _existe(c, "leads_alvo"):
            return []
        onde, params = ["1=1"], []
        if motivo in MOTIVOS:
            onde.append("_motivo = ?"); params.append(motivo)
        if categoria.strip():
            onde.append("categoria = ?"); params.append(categoria.strip())
        if cidade.strip():
            onde.append("cidade_origem = ?"); params.append(cidade.strip())
        if tier.strip():
            onde.append("tier_sugerido = ?"); params.append(tier.strip())
        if q.strip():
            like = f"%{q.strip()}%"
            onde.append("(nome LIKE ? OR telefone LIKE ? OR categoria LIKE ?)")
            params += [like, like, like]
        params.append(int(limite))
        rows = c.execute(
            "SELECT place_id,nome,categoria,cidade_origem,telefone,email,website,"
            "score_dor,tier_sugerido,motivo_da_dor,_motivo AS motivo FROM leads_alvo "
            f"WHERE {' AND '.join(onde)} "
            "ORDER BY CAST(COALESCE(score_dor,0) AS INT) DESC, CAST(COALESCE(score_final,0) AS INT) DESC "
            "LIMIT ?", params).fetchall()
    return [dict(r) for r in rows]


def _contagem(c, tab: str, col: str) -> dict:
    return {(r[0] or "(sem)"): r[1] for r in c.execute(
        f"SELECT {col}, COUNT(*) FROM {tab} GROUP BY {col} ORDER BY COUNT(*) DESC")}


def resumo() -> dict:
    """Números do topo + valores pros dropdowns de filtro."""
    with _db() as c:
        if not _existe(c, "leads_alvo"):
            return {"total": 0, "por_motivo": {}, "por_tier": {}, "categorias": [], "cidades": [], "t3t4": 0}
        total = c.execute("SELECT COUNT(*) FROM leads_alvo").fetchone()[0]
        por_motivo = _contagem(c, "leads_alvo", "_motivo")
        por_tier = _contagem(c, "leads_alvo", "tier_sugerido")
        cats = [r[0] for r in c.execute(
            "SELECT categoria, COUNT(*) n FROM leads_alvo GROUP BY categoria ORDER BY n DESC")]
        cidades = [r[0] for r in c.execute(
            "SELECT cidade_origem, COUNT(*) n FROM leads_alvo GROUP BY cidade_origem ORDER BY n DESC")]
        com_tel = c.execute("SELECT COUNT(*) FROM leads_alvo WHERE TRIM(COALESCE(telefone,''))<>''").fetchone()[0]
        t3t4 = c.execute("SELECT COUNT(*) FROM leads_t3t4").fetchone()[0] if _existe(c, "leads_t3t4") else 0
    return {"total": total, "com_telefone": com_tel, "por_motivo": por_motivo, "por_tier": por_tier,
            "categorias": [x for x in cats if x], "cidades": [x for x in cidades if x], "t3t4": t3t4}


if __name__ == "__main__":  # self-check offline: DB temp com as duas tabelas
    import tempfile
    os.environ["LEADS_DB"] = tempfile.mktemp(suffix="_leadsalvo.db")
    con = sqlite3.connect(os.environ["LEADS_DB"])
    con.execute("CREATE TABLE leads_alvo (place_id,nome,categoria,cidade_origem,telefone,email,website,"
                "score_dor,score_final,tier_sugerido,passa_corte,motivo_da_dor,_motivo,status)")
    dados = [("p1", "Dentista A", "dentista", "Lins", "(14)9", "", "", 60, 60, "T2", "1", "sem site", "sem_website", ""),
             ("p2", "Clinica B", "clínica de estética", "Bauru", "(14)8", "", "http://insta", 40, 40, "T3", "1", "x", "social_only", ""),
             ("p3", "Pet C", "pet shop", "Lins", "", "", "", 10, 10, "T1", "0", "y", "site_morto", "")]
    con.executemany("INSERT INTO leads_alvo VALUES (%s)" % ",".join("?" * 14), dados)
    con.execute("CREATE TABLE leads_t3t4 (place_id,email)")
    con.executemany("INSERT INTO leads_t3t4 VALUES (?,?)", [("x", "a@b.com"), ("y", "c@d.com")])
    con.commit(); con.close()

    assert len(listar()) == 3
    assert [r["nome"] for r in listar()] == ["Dentista A", "Clinica B", "Pet C"]  # ordena por dor
    assert len(listar(motivo="sem_website")) == 1 and listar(motivo="sem_website")[0]["nome"] == "Dentista A"
    assert len(listar(cidade="Lins")) == 2 and len(listar(categoria="pet shop")) == 1
    assert len(listar(q="clinica")) == 1
    r = resumo()
    assert r["total"] == 3 and r["t3t4"] == 2 and r["com_telefone"] == 2, r
    assert r["por_motivo"] == {"sem_website": 1, "social_only": 1, "site_morto": 1}, r["por_motivo"]
    assert "Lins" in r["cidades"] and "dentista" in r["categorias"]
    print("leads_alvo OK — listar+filtros (motivo/cidade/categoria/q), ordena por dor, resumo+t3t4")
