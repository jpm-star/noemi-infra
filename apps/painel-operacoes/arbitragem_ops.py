"""Oportunidade de arbitragem: achou aqui, passou ali — com a conta feita.

O QUE ISTO É E O QUE NÃO É. `motores.arbitragem()` mostra o ESTADO das três camadas
(v1 no ar, central de compras sem serviço, exodia vazio) — infraestrutura. Isto aqui é
a operação do dia: uma linha por negócio que você viu, com a conta que diz se vale.

POR QUE OS DOIS MODOS NA MESMA TABELA. "Achou aqui, passou ali" pode ser duas coisas
diferentes, e não dava pra saber qual sem decidir por você:
  · REVENDA  — você compra do fornecedor e vende pro comprador. Assume o capital e o
               frete, e fica com a diferença inteira.
  · COMISSAO — você não compra nada: apresenta um ao outro e cobra um percentual.
               Zero capital, zero frete, zero risco de estoque — e um teto de ganho.
Os dois têm os MESMOS campos de identificação (o quê, de quem, pra quem, por quanto) e
diferem só na fórmula do lucro. Então a decisão vira um CAMPO, não uma bifurcação de
arquitetura: registre a mesma oportunidade nos dois modos e compare o lucro lado a lado.

A LOGÍSTICA ENTRA AQUI, e é o ponto que costuma matar o negócio. Frete não é despesa
menor: num item de R$ 40 com R$ 15 de frete, o frete come 37% do preço antes de qualquer
margem. Por isso `conta()` devolve `frete_pct_lucro` — quanto do seu lucro é frete — em
vez de só o total. Um negócio com margem boa e frete comendo 60% do lucro é um negócio
que morre no primeiro reajuste da transportadora.

ponytail: uma tabela no SQLite que já existe, função pura pra conta, sem serviço novo.
"""
from __future__ import annotations

import os
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "packages"))

MODOS = ("revenda", "comissao")
STATUS = ("achada", "cotando", "fechada", "perdida")

_DDL = """
CREATE TABLE IF NOT EXISTS oportunidades (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  criado_em TEXT NOT NULL,
  modo TEXT NOT NULL,
  item TEXT NOT NULL,
  origem TEXT,            -- onde ACHOU (fornecedor, marketplace, feira)
  destino TEXT,           -- pra quem PASSA (comprador)
  qtd REAL NOT NULL DEFAULT 1,
  custo_unit REAL NOT NULL DEFAULT 0,
  frete_total REAL NOT NULL DEFAULT 0,
  preco_unit REAL NOT NULL DEFAULT 0,
  comissao_pct REAL NOT NULL DEFAULT 0,
  status TEXT NOT NULL DEFAULT 'achada',
  nota TEXT
)
"""


def _conn():
    from shared_core.storage import db
    return db.conn()


def garantir_tabela(c) -> None:
    c.execute(_DDL)
    c.commit()


def conta(op: dict) -> dict:
    """A conta do negócio. Função pura: recebe dict, devolve dict.

    Campos derivados, todos em reais salvo onde o nome diz `_pct`:
      receita        — o que o comprador paga
      custo_total    — o que sai do seu bolso (0 no modo comissão: você não compra)
      lucro          — o que sobra
      margem_pct     — lucro sobre receita (não sobre custo: margem sobre custo é markup,
                       e confundir os dois é como se acha que 50% de markup é 50% de margem)
      markup_pct     — lucro sobre custo, pra quem negocia com fornecedor nessa linguagem
      frete_pct_lucro— quanto do lucro é frete. É o número que mata negócio bom no papel.
    """
    qtd = float(op.get("qtd") or 0)
    preco = float(op.get("preco_unit") or 0)
    custo = float(op.get("custo_unit") or 0)
    frete = float(op.get("frete_total") or 0)
    pct = float(op.get("comissao_pct") or 0)
    receita = preco * qtd
    if (op.get("modo") or "revenda") == "comissao":
        # não compra e não paga frete: o lucro é o percentual sobre o que o comprador paga
        custo_total, lucro = 0.0, receita * pct / 100.0
        frete = 0.0
    else:
        custo_total = custo * qtd + frete
        lucro = receita - custo_total
    return {
        "receita": round(receita, 2),
        "custo_total": round(custo_total, 2),
        "lucro": round(lucro, 2),
        "margem_pct": round(lucro / receita * 100, 1) if receita else None,
        "markup_pct": round(lucro / custo_total * 100, 1) if custo_total else None,
        # None (não 0) quando não há lucro: 0% de frete sobre prejuízo seria mentira
        "frete_pct_lucro": round(frete / lucro * 100, 1) if lucro > 0 and frete else None,
        "frete_unit": round(frete / qtd, 2) if qtd else None,
        "viavel": lucro > 0,
    }


def preco_para_margem(op: dict, margem_alvo_pct: float) -> float | None:
    """Por quanto vender pra bater a margem alvo. None se a conta não fecha.

    É a pergunta que se faz na frente do comprador ("por quanto posso deixar?"), e
    fazer de cabeça com frete no meio é como se erra."""
    qtd = float(op.get("qtd") or 0)
    if not qtd or margem_alvo_pct >= 100:
        return None
    if (op.get("modo") or "revenda") == "comissao":
        return None   # no modo comissão a margem é a própria comissão, não o preço
    custo_total = float(op.get("custo_unit") or 0) * qtd + float(op.get("frete_total") or 0)
    return round(custo_total / (1 - margem_alvo_pct / 100.0) / qtd, 2)


def registrar(op: dict) -> dict:
    """Grava a oportunidade. Devolve a linha com a conta junto."""
    modo = (op.get("modo") or "revenda").strip().lower()
    if modo not in MODOS:
        return {"ok": False, "erro": f"modo tem que ser um de {MODOS}"}
    if not (op.get("item") or "").strip():
        return {"ok": False, "erro": "sem item não há oportunidade"}
    status = (op.get("status") or "achada").strip().lower()
    if status not in STATUS:
        return {"ok": False, "erro": f"status tem que ser um de {STATUS}"}
    with _conn() as c:
        garantir_tabela(c)
        cur = c.execute(
            "INSERT INTO oportunidades (criado_em,modo,item,origem,destino,qtd,custo_unit,"
            "frete_total,preco_unit,comissao_pct,status,nota) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (datetime.now(timezone.utc).isoformat(), modo, op["item"].strip(),
             (op.get("origem") or "").strip(), (op.get("destino") or "").strip(),
             float(op.get("qtd") or 1), float(op.get("custo_unit") or 0),
             float(op.get("frete_total") or 0), float(op.get("preco_unit") or 0),
             float(op.get("comissao_pct") or 0), status, (op.get("nota") or "").strip()))
        c.commit()
        return {"ok": True, "id": cur.lastrowid, **conta(op)}


def mudar_status(oid: int, status: str) -> dict:
    if status not in STATUS:
        return {"ok": False, "erro": f"status tem que ser um de {STATUS}"}
    with _conn() as c:
        garantir_tabela(c)
        n = c.execute("UPDATE oportunidades SET status=? WHERE id=?", (status, oid)).rowcount
        c.commit()
    return {"ok": bool(n), "id": oid, "status": status}


def listar(status: str = "") -> dict:
    """Todas as oportunidades com a conta feita, mais o placar do funil.

    O placar soma o lucro só das FECHADAS. Somar o das 'achadas' viraria um número de
    pipeline que ninguém recebeu — a mesma armadilha do CRM com 1.532 leads 'a contatar'
    que parecia um funil cheio e era uma fila parada."""
    with _conn() as c:
        garantir_tabela(c)
        sql = "SELECT * FROM oportunidades"
        args: tuple = ()
        if status:
            sql += " WHERE status=?"
            args = (status,)
        cur = c.execute(sql + " ORDER BY id DESC", args)
        cols = [d[0] for d in cur.description]
        itens = [dict(zip(cols, r)) for r in cur.fetchall()]
    for it in itens:
        it["conta"] = conta(it)
    fechadas = [i for i in itens if i["status"] == "fechada"]
    por_status = {s: sum(1 for i in itens if i["status"] == s) for s in STATUS}
    return {
        "itens": itens, "total": len(itens), "por_status": por_status,
        "lucro_fechado": round(sum(i["conta"]["lucro"] for i in fechadas), 2),
        # em aberto fica SEPARADO do realizado, e nomeado como potencial
        "lucro_potencial_aberto": round(
            sum(i["conta"]["lucro"] for i in itens if i["status"] in ("achada", "cotando")), 2),
    }


def _autoteste() -> None:
    # revenda: 100 un a 40 de custo, 15 de frete total, vendidas a 60
    r = conta({"modo": "revenda", "qtd": 100, "custo_unit": 40, "frete_total": 15,
               "preco_unit": 60})
    assert r["receita"] == 6000 and r["custo_total"] == 4015, r
    assert r["lucro"] == 1985 and r["margem_pct"] == 33.1, r
    # markup != margem: 1985/4015 = 49.4%, e 1985/6000 = 33.1%. Trocar os dois é o erro
    # clássico de quem negocia com fornecedor e acha que fechou 50%.
    assert r["markup_pct"] == 49.4 and r["margem_pct"] != r["markup_pct"], r

    # o frete que mata: item barato, frete alto
    r = conta({"modo": "revenda", "qtd": 10, "custo_unit": 40, "frete_total": 150,
               "preco_unit": 60})
    assert r["lucro"] == 50 and r["frete_pct_lucro"] == 300.0, r
    assert r["viavel"] is True, "lucro positivo é viável, mesmo com frete pesado"

    # prejuízo não vira porcentagem de frete bonitinha
    r = conta({"modo": "revenda", "qtd": 10, "custo_unit": 40, "frete_total": 300,
               "preco_unit": 50})
    assert r["lucro"] == -200 and r["viavel"] is False and r["frete_pct_lucro"] is None, r

    # comissão: não compra, não paga frete — o frete informado é ignorado de propósito
    r = conta({"modo": "comissao", "qtd": 100, "preco_unit": 60, "comissao_pct": 8,
               "custo_unit": 40, "frete_total": 999})
    assert r["custo_total"] == 0 and r["lucro"] == 480 and r["margem_pct"] == 8.0, r
    assert r["frete_pct_lucro"] is None, "comissão não paga frete"

    # preço-alvo: bate a margem pedida
    op = {"modo": "revenda", "qtd": 100, "custo_unit": 40, "frete_total": 15}
    p = preco_para_margem(op, 30)
    assert abs(conta({**op, "preco_unit": p})["margem_pct"] - 30) < 0.2, (p, op)
    assert preco_para_margem({"modo": "comissao", "qtd": 10}, 30) is None
    assert preco_para_margem({"qtd": 0}, 30) is None

    # divisão por zero não explode em lugar nenhum
    z = conta({"modo": "revenda", "qtd": 0, "custo_unit": 0, "preco_unit": 0})
    assert z["margem_pct"] is None and z["markup_pct"] is None and z["viavel"] is False, z
    print("arbitragem_ops OK — margem != markup, frete entra na conta e é reportado como "
          "% do lucro, comissão não paga frete, preço-alvo bate a margem, zero não explode")


if __name__ == "__main__":
    if "--check" in sys.argv[1:] or os.environ.get("ARB_SELFTEST"):
        _autoteste()
        raise SystemExit(0)
    import json
    print(json.dumps(listar(), ensure_ascii=False, indent=1)[:3000])
