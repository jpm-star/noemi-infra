"""QG Pessoal — controle de vida/financeiro do JP no painel (extensão do p.jpos).

Additive puro: mesma noemi.db (SQLite), mesmo padrão CREATE TABLE IF NOT EXISTS dos
outros módulos do painel (radar_jobs/insights_cliente/auto_insights) — sem migração
central, sem tocar storage/db.py, reversível (DROP TABLE). Sem dep nova.

Ingestão por DOIS caminhos, mesmo add():
  - painel (input rápido na aba Pessoal, origem="painel")
  - Noemi (sdr-motor-papai :8007 grava o que o JP manda no WhatsApp, origem="noemi") — Fase C.
"""
from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parents[1] / "packages"))

TIPOS = ("nota", "financeiro", "tarefa", "lembrete")
STATUS = ("aberto", "feito")


def _tabela(c) -> None:
    c.execute("CREATE TABLE IF NOT EXISTS pessoal_itens ("
              "id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT, tipo TEXT, texto TEXT, "
              "valor REAL, categoria TEXT, status TEXT, origem TEXT)")


def add(texto: str, tipo: str = "nota", valor=None, categoria: str = "",
        origem: str = "painel") -> dict:
    """Grava um item. valor só faz sentido em tipo='financeiro' (+entrada / -saída);
    em qualquer outro tipo o valor é ignorado (fica None)."""
    from shared_core.storage import db
    texto = (texto or "").strip()
    if not texto:
        raise ValueError("texto vazio")
    tipo = tipo if tipo in TIPOS else "nota"
    try:
        v = float(valor) if valor not in (None, "") else None
    except (TypeError, ValueError):
        v = None
    if tipo != "financeiro":
        v = None  # valor só em financeiro — não deixa lançamento sujar nota/tarefa
    ts = datetime.now(timezone.utc).isoformat()
    cat = (categoria or "").strip()[:60]
    with db.conn() as c:
        _tabela(c)
        cur = c.execute("INSERT INTO pessoal_itens (ts,tipo,texto,valor,categoria,status,origem) "
                        "VALUES (?,?,?,?,?,?,?)",
                        (ts, tipo, texto[:2000], v, cat, "aberto", (origem or "painel")[:20]))
        c.commit()
        return {"id": cur.lastrowid, "ts": ts, "tipo": tipo, "texto": texto[:2000],
                "valor": v, "categoria": cat, "status": "aberto", "origem": (origem or "painel")[:20]}


def listar(tipo: str | None = None, limite: int = 100) -> list[dict]:
    """Itens mais recentes (abertos primeiro). Filtra por tipo se dado."""
    from shared_core.storage import db
    with db.conn() as c:
        _tabela(c)
        if tipo and tipo in TIPOS:
            rows = c.execute("SELECT * FROM pessoal_itens WHERE tipo=? "
                             "ORDER BY (status='aberto') DESC, id DESC LIMIT ?", (tipo, limite)).fetchall()
        else:
            rows = c.execute("SELECT * FROM pessoal_itens "
                             "ORDER BY (status='aberto') DESC, id DESC LIMIT ?", (limite,)).fetchall()
    return [dict(r) for r in rows]


def set_status(item_id: int, status: str) -> bool:
    """👍 marca aberto/feito (o toggle da lista)."""
    from shared_core.storage import db
    st = status if status in STATUS else "aberto"
    with db.conn() as c:
        _tabela(c)
        cur = c.execute("UPDATE pessoal_itens SET status=? WHERE id=?", (st, item_id))
        c.commit()
    return cur.rowcount > 0


def saldo_mes(ano_mes: str | None = None) -> dict:
    """Saldo financeiro do mês (SUM valor) + quebra por categoria. ano_mes 'YYYY-MM'
    (default = mês atual UTC). Controle financeiro simples, sem lib."""
    from shared_core.storage import db
    ym = ano_mes or datetime.now(timezone.utc).strftime("%Y-%m")
    with db.conn() as c:
        _tabela(c)
        rows = c.execute("SELECT COALESCE(NULLIF(categoria,''),'(sem)') cat, "
                         "COALESCE(SUM(valor),0) s, COUNT(*) n FROM pessoal_itens "
                         "WHERE tipo='financeiro' AND substr(ts,1,7)=? GROUP BY cat "
                         "ORDER BY s", (ym,)).fetchall()
        total = c.execute("SELECT COALESCE(SUM(valor),0) s FROM pessoal_itens "
                          "WHERE tipo='financeiro' AND substr(ts,1,7)=?", (ym,)).fetchone()
    return {"mes": ym, "saldo": round(total["s"], 2),
            "por_categoria": [{"categoria": r["cat"], "soma": round(r["s"], 2), "n": r["n"]} for r in rows]}


def deletar(item_id: int) -> bool:
    from shared_core.storage import db
    with db.conn() as c:
        _tabela(c)
        cur = c.execute("DELETE FROM pessoal_itens WHERE id=?", (item_id,))
        c.commit()
    return cur.rowcount > 0


if __name__ == "__main__":  # self-check offline: DB isolado (tempfile), sem rede/produção
    import os
    import tempfile
    os.environ["NOEMI_DATA_DIR"] = tempfile.mkdtemp(suffix="_pessoal")

    a = add("comprar cimento", tipo="tarefa")
    assert a["id"] and a["status"] == "aberto" and a["valor"] is None, a
    f1 = add("recebi de cliente", tipo="financeiro", valor=1200, categoria="receita")
    f2 = add("gasolina", tipo="financeiro", valor=-200, categoria="transporte")
    assert f1["valor"] == 1200.0 and f2["valor"] == -200.0, (f1, f2)
    assert add("nota solta", tipo="nota", valor=999)["valor"] is None  # valor só em financeiro
    assert add("tipo inválido vira nota", tipo="xpto")["tipo"] == "nota"

    itens = listar()
    assert len(itens) == 5 and itens[0]["status"] == "aberto", len(itens)
    assert len(listar(tipo="financeiro")) == 2

    s = saldo_mes()
    assert s["saldo"] == 1000.0, s              # 1200 - 200
    assert {c["categoria"] for c in s["por_categoria"]} == {"receita", "transporte"}, s

    assert set_status(a["id"], "feito") and listar(tipo="tarefa")[0]["status"] == "feito"
    assert deletar(f2["id"]) and saldo_mes()["saldo"] == 1200.0  # tirou a saída
    try:
        add("")  # texto vazio deve recusar
        raise AssertionError("deveria ter recusado texto vazio")
    except ValueError:
        pass
    print("pessoal OK — add/listar/status/saldo(financeiro), valor só em financeiro, "
          "tipo inválido→nota, texto vazio recusa, DB isolado")
