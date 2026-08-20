"""Pé Di · calculadora de custo/preço/comissão — porta a PEDI_OPERACIONAL_v2.xlsx.

Substitui a planilha solta que o JP abria pra cotar ao vivo em ligação. Três peças:

  1. CURVA ABC editável (tabela `curva_abc`) — os componentes de custo por par.
     Somar tudo dá o CUSTO REAL POR PAR, exatamente como a aba PRODUTO faz:
     custo direto + provisões + diluições, sem peso, sem rateio novo.
  2. SIMULADOR — tipo + quantidade + preço cotado → custo, margem, imposto no
     preço final, upsells e veredito.
  3. LOG append-only (`log_mudanca`) — toda edição da curva grava campo, valor
     antigo e valor novo. Nunca sobrescreve, nunca apaga.

As diluições (MO, aluguel/energia, marketing, tecnologia, conhecimento, CAPEX,
FINAME) já vêm rateadas na premissa de 1000 pares/mês. Isso é INTENCIONAL: aqui
elas são somadas como estão, nunca recalculadas em cima da quantidade do pedido.

ponytail: SQLite em arquivo PRÓPRIO (data/pedi_custo.db), não a noemi.db. A
restrição é não cruzar com dado de cliente do JPOS — arquivo separado resolve
isso por construção, sem RLS e sem schema qualificado.
"""
from __future__ import annotations

import math
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

_RAIZ = Path(__file__).resolve().parents[2]
_DB = Path(os.environ.get("PEDI_CUSTO_DB", str(_RAIZ / "data" / "pedi_custo.db")))

TIPOS = ("BASE", "PREMIUM")
GRUPOS = ("direto", "provisao", "diluicao")

# CONFIG linha 12 da planilha: Simples Nacional 5%. Sempre embutido no preço
# final cotado — nunca cobrado à parte no fechamento.
# ponytail: constante, não linha de tabela. Vira config quando a faixa do Simples
# mudar de verdade (aí é 1 linha aqui, não uma tela nova).
ALIQUOTA_SIMPLES = 0.05

# Tier 1000+: piso de margem. Abaixo disso o preço sobe sozinho.
PISO_MARGEM = 0.15
PRECO_PARTIDA_1000 = 24.97
PASSOS_AJUSTE = (1.00, 0.50)

# Upsell "bandeira do Brasil": 100% vai pro vendedor como comissão. Não sai da
# margem base do produto — entra e sai, o resultado da empresa não muda.
# ponytail: o brief define até 100 / até 200 / até 500 / de 1000 pra cima. A faixa
# 501–999 não foi definida, então a última faixa conhecida (0,50) se estende até
# 999. Trocar aqui se o JP fechar outra regra.
FAIXAS_BANDEIRA = ((100, 1.00), (200, 0.75), (999, 0.50))
BANDEIRA_ACIMA = 0.30

# Upsell "saquinho personalizado": margem da EMPRESA, não entra na comissão.
SAQUINHO_PRECO = 3.00
SAQUINHO_CUSTO = 2.53

# Semente da curva: portada VERBATIM da aba 08_PRODUTO da PEDI_OPERACIONAL_v2.xlsx.
# Soma BASE = 19,31 e PREMIUM = 26,79, batendo com "CUSTO REAL POR PAR" da planilha.
# Nenhum valor foi recalculado ou "corrigido" — inclusive os que divergem da aba
# CONFIG (embalagem BASE 2,35 aqui vs 2,53 na CONFIG; provisão de MO 0,10 aqui vs
# 6,00 na CONFIG). A aba PRODUTO é o que a planilha de fato usava pra cotar.
_SEMENTE = [
    ("direto", "Placa", 5.00, 10.00, "base: 70/30 R$180 ÷ 36 pares · premium: 90/10 R$80 ÷ 8 pares"),
    ("direto", "Tira", 3.20, 3.20, "base: tradicional · premium: slim glitter premier"),
    ("direto", "Sublimação", 0.94, 0.94, "papel + tinta + tecido + tempo de prensa"),
    ("direto", "Lacre + etiqueta", 0.07, 0.07, "lacre R$0,02 + etiqueta R$0,05"),
    ("direto", "Embalagem", 2.35, 2.53, "base: saco + tag de evento · premium: caixa+seda+cartão+sacola"),
    ("provisao", "Provisão de mão de obra", 0.10, 0.10, "diluída em 1000 pares/mês"),
    ("provisao", "Provisão de aluguel e energia", 0.10, 0.10, "diluída em 1000 pares/mês"),
    ("provisao", "Provisão de marketing", 1.00, 2.00, "diluída em 1000 pares/mês"),
    ("provisao", "Provisão de tecnologia", 0.10, 0.50, "diluída em 1000 pares/mês"),
    ("provisao", "Provisão de conhecimento", 0.00, 1.00, "diluída em 1000 pares/mês"),
    ("diluicao", "Diluição CAPEX", 4.35, 4.35, "diluída em 1000 pares/mês"),
    ("diluicao", "Diluição FINAME", 2.10, 2.00, "diluída em 1000 pares/mês"),
]


def _conn() -> sqlite3.Connection:
    _DB.parent.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(_DB, timeout=10)
    c.row_factory = sqlite3.Row
    c.executescript(
        """
        CREATE TABLE IF NOT EXISTS curva_abc (
          id      INTEGER PRIMARY KEY AUTOINCREMENT,
          ordem   INTEGER NOT NULL DEFAULT 0,
          grupo   TEXT    NOT NULL,
          nome    TEXT    NOT NULL,
          base    REAL    NOT NULL DEFAULT 0,
          premium REAL    NOT NULL DEFAULT 0,
          nota    TEXT    NOT NULL DEFAULT ''
        );
        CREATE TABLE IF NOT EXISTS log_mudanca (
          id    INTEGER PRIMARY KEY AUTOINCREMENT,
          ts    TEXT NOT NULL,
          item  TEXT NOT NULL,
          campo TEXT NOT NULL,
          de    TEXT NOT NULL,
          para  TEXT NOT NULL
        );
        """
    )
    if not c.execute("SELECT 1 FROM curva_abc LIMIT 1").fetchone():
        c.executemany(
            "INSERT INTO curva_abc (ordem,grupo,nome,base,premium,nota) VALUES (?,?,?,?,?,?)",
            [(i, *linha) for i, linha in enumerate(_SEMENTE)],
        )
        c.commit()
    return c


def _log(c: sqlite3.Connection, item: str, campo: str, de, para) -> None:
    """Append-only: só INSERT. Nenhum caminho do módulo faz UPDATE/DELETE aqui."""
    c.execute(
        "INSERT INTO log_mudanca (ts,item,campo,de,para) VALUES (?,?,?,?,?)",
        (datetime.now(timezone.utc).isoformat(timespec="seconds"), item, campo,
         "" if de is None else str(de), "" if para is None else str(para)),
    )


# ─────────────────────────── curva ABC ───────────────────────────

def curva() -> list[dict]:
    with _conn() as c:
        return [dict(r) for r in c.execute("SELECT * FROM curva_abc ORDER BY ordem, id")]


def custo_par(tipo: str = "BASE") -> float:
    """CUSTO REAL POR PAR = soma de TODOS os componentes da curva.

    Mesma lógica da aba PRODUTO: direto + provisões + diluições, sem peso e sem
    recálculo da diluição em cima da quantidade do pedido.
    """
    col = "premium" if str(tipo).upper() == "PREMIUM" else "base"
    with _conn() as c:
        return round(c.execute(f"SELECT COALESCE(SUM({col}),0) FROM curva_abc").fetchone()[0], 2)


def salvar_item(id_: int | None, nome: str, base: float, premium: float,
                grupo: str = "direto", nota: str = "") -> dict:
    """Cria (id_=None) ou edita um componente. Toda diferença vira linha de log."""
    nome = (nome or "").strip()
    if not nome:
        raise ValueError("nome do componente é obrigatório")
    grupo = grupo if grupo in GRUPOS else "direto"
    base, premium = round(float(base or 0), 2), round(float(premium or 0), 2)
    nota = (nota or "").strip()[:300]
    with _conn() as c:
        if id_:
            antes = c.execute("SELECT * FROM curva_abc WHERE id=?", (id_,)).fetchone()
            if not antes:
                raise ValueError(f"componente {id_} não existe")
            for campo, novo in (("nome", nome), ("base", base), ("premium", premium),
                                ("grupo", grupo), ("nota", nota)):
                if str(antes[campo]) != str(novo):
                    _log(c, antes["nome"], campo, antes[campo], novo)
            c.execute("UPDATE curva_abc SET nome=?,base=?,premium=?,grupo=?,nota=? WHERE id=?",
                      (nome, base, premium, grupo, nota, id_))
        else:
            ordem = (c.execute("SELECT COALESCE(MAX(ordem),0)+1 FROM curva_abc").fetchone()[0])
            cur = c.execute("INSERT INTO curva_abc (ordem,grupo,nome,base,premium,nota) "
                            "VALUES (?,?,?,?,?,?)", (ordem, grupo, nome, base, premium, nota))
            id_ = cur.lastrowid
            _log(c, nome, "criado", "", f"base {base:.2f} / premium {premium:.2f}")
        c.commit()
    return {"id": id_, "nome": nome, "base": base, "premium": premium,
            "grupo": grupo, "nota": nota}


def remover_item(id_: int) -> bool:
    with _conn() as c:
        r = c.execute("SELECT * FROM curva_abc WHERE id=?", (id_,)).fetchone()
        if not r:
            return False
        _log(c, r["nome"], "removido", f"base {r['base']:.2f} / premium {r['premium']:.2f}", "")
        c.execute("DELETE FROM curva_abc WHERE id=?", (id_,))
        c.commit()
    return True


def historico(limite: int = 200) -> list[dict]:
    with _conn() as c:
        return [dict(r) for r in c.execute(
            "SELECT * FROM log_mudanca ORDER BY id DESC LIMIT ?", (int(limite),))]


# ─────────────────────────── upsells ───────────────────────────

def comissao_bandeira(qtd: int) -> float:
    """R$/par do upsell bandeira. 100% disso é comissão do vendedor."""
    for ate, valor in FAIXAS_BANDEIRA:
        if qtd <= ate:
            return valor
    return BANDEIRA_ACIMA


# ─────────────────────────── simulador ───────────────────────────

def _preco_com_piso(preco: float, custo: float, qtd: int) -> tuple[float, dict | None]:
    """Rede de segurança do tier 1000+: se a margem cair abaixo do piso, sobe o
    preço sozinho em passos de R$1,00 ou R$0,50 — o que fechar mais perto do piso.

    Só dispara de 1000 pares pra cima e só quando o custo real do pedido empurrou
    a margem pra baixo. Com o custo diluído normal, R$24,97 já passa do piso e
    nada acontece.
    """
    if qtd < 1000 or custo <= 0:
        return preco, None
    alvo = custo / (1 - PISO_MARGEM)  # preço que entrega exatamente o piso
    if preco >= alvo - 0.005:
        return preco, None
    candidatos = [preco + math.ceil((alvo - preco) / p) * p for p in PASSOS_AJUSTE]
    novo = round(min(candidatos), 2)  # o que fecha mais próximo do piso, por cima
    passo = PASSOS_AJUSTE[candidatos.index(min(candidatos))]
    return novo, {"de": round(preco, 2), "para": novo, "passo": passo,
                  "alvo_piso": round(alvo, 2),
                  "porque": f"margem em R$ {preco:.2f} ficaria abaixo do piso de "
                            f"{PISO_MARGEM:.0%} sobre o custo real de R$ {custo:.2f}"}


def simular(tipo: str = "BASE", qtd: int = 0, preco: float = 0.0,
            bandeira: bool = False, saquinho: bool = False) -> dict:
    """Cotação ao vivo. `preco` é o preço do par SEM imposto; o Simples é
    embutido no preço final que o cliente ouve.

    Margem = (preço − custo) / preço, sobre o preço líquido de imposto — é a
    mesma conta da aba PRODUTO. O imposto não entra na margem porque ele é
    repassado por dentro do preço final, não descontado do resultado.
    """
    tipo = str(tipo).upper()
    tipo = tipo if tipo in TIPOS else "BASE"
    qtd, preco = int(qtd or 0), round(float(preco or 0), 2)
    custo = custo_par(tipo)

    preco, ajuste = _preco_com_piso(preco, custo, qtd)

    margem_par = round(preco - custo, 2)
    margem_pct = round(margem_par / preco, 4) if preco else 0.0
    # Simples por dentro: o cliente paga o final, a empresa recolhe a alíquota
    # dele e o que sobra é exatamente `preco`. Somar 5% "por fora" deixaria a
    # margem menor do que a cotada.
    preco_final = round(preco / (1 - ALIQUOTA_SIMPLES), 2) if preco else 0.0
    imposto_par = round(preco_final - preco, 2)

    bandeira_par = comissao_bandeira(qtd) if bandeira else 0.0
    saquinho_margem_par = round(SAQUINHO_PRECO - SAQUINHO_CUSTO, 2) if saquinho else 0.0

    custo_total = round(custo * qtd, 2)
    margem_total = round(margem_par * qtd + saquinho_margem_par * qtd, 2)
    receita = round(preco * qtd, 2)
    receita_final = round((preco_final + bandeira_par + (SAQUINHO_PRECO if saquinho else 0)) * qtd, 2)
    adiantamento = round(receita_final / 2, 2)

    # Veredito é sobre MARGEM. O adiantamento é pergunta de caixa, não de preço:
    # em lote grande 50% quase nunca cobre o material, e deixar isso reprovar a
    # cotação faria o simulador dizer "não fecha" num pedido lucrativo. Vira
    # ressalva no mesmo texto, não veredito.
    if custo <= 0:
        veredito, ok = "SEM CUSTO NA CURVA — preencha a curva ABC antes de cotar", False
    elif margem_pct < PISO_MARGEM:
        veredito, ok = f"NÃO FECHA: margem {margem_pct:.1%} abaixo do piso de {PISO_MARGEM:.0%}", False
    else:
        veredito, ok = f"FECHA: margem {margem_pct:.1%}", True
    caixa_curto = ok and adiantamento < custo_total
    if caixa_curto:
        veredito += " · atenção: o adiantamento de 50% não cobre o material"

    return {
        "tipo": tipo, "qtd": qtd,
        "preco_cotado": preco, "ajuste_automatico": ajuste,
        "custo_par": custo, "custo_total": custo_total,
        "margem_par": margem_par, "margem_pct": margem_pct, "margem_total": margem_total,
        "imposto_par": imposto_par, "imposto_total": round(imposto_par * qtd, 2),
        "preco_final_cliente": preco_final,
        "receita_sem_imposto": receita, "receita_com_upsells": receita_final,
        "adiantamento_50": adiantamento,
        "bandeira": {"por_par": bandeira_par, "total": round(bandeira_par * qtd, 2),
                     "comissao_vendedor": round(bandeira_par * qtd, 2)} if bandeira else None,
        "saquinho": {"preco": SAQUINHO_PRECO, "custo": SAQUINHO_CUSTO,
                     "margem_par": saquinho_margem_par,
                     "margem_total": round(saquinho_margem_par * qtd, 2)} if saquinho else None,
        "veredito": veredito, "fecha": ok, "adiantamento_curto": caixa_curto,
    }


def resumo() -> dict:
    return {"curva": curva(), "custo": {t: custo_par(t) for t in TIPOS},
            "historico": historico(50),
            "config": {"aliquota_simples": ALIQUOTA_SIMPLES, "piso_margem": PISO_MARGEM,
                       "preco_partida_1000": PRECO_PARTIDA_1000,
                       "faixas_bandeira": [list(f) for f in FAIXAS_BANDEIRA] + [[None, BANDEIRA_ACIMA]],
                       "saquinho": {"preco": SAQUINHO_PRECO, "custo": SAQUINHO_CUSTO}}}


if __name__ == "__main__":  # self-check: os 3 cenários que o JP vai conferir
    import json
    import tempfile

    _DB = Path(tempfile.mkdtemp()) / "t.db"  # banco descartável, não toca o real

    # comissão da bandeira por faixa
    assert comissao_bandeira(80) == 1.00 and comissao_bandeira(100) == 1.00
    assert comissao_bandeira(150) == 0.75 and comissao_bandeira(400) == 0.50
    assert comissao_bandeira(1200) == 0.30

    assert custo_par("BASE") == 19.31, custo_par("BASE")
    assert custo_par("PREMIUM") == 26.79, custo_par("PREMIUM")

    # Contrato com a planilha: aos preços sugeridos da aba PRODUTO, a margem tem de
    # reproduzir a linha "Margem (%)" da v2 — 31,0% BASE e 45,3% PREMIUM. É o teste
    # que quebra se alguém mexer na fórmula de margem sem querer.
    assert round(simular("BASE", 100, 28.00)["margem_pct"], 3) == 0.310
    assert round(simular("PREMIUM", 100, 49.00)["margem_pct"], 3) == 0.453

    # 1) 300 pares BASE a R$25,97 — não é tier 1000+, nenhum auto-ajuste
    a = simular("BASE", 300, 25.97, bandeira=True)
    assert a["ajuste_automatico"] is None
    assert a["custo_total"] == 5793.00, a["custo_total"]
    assert a["bandeira"]["comissao_vendedor"] == 150.00
    assert a["imposto_par"] == 1.37, a["imposto_par"]

    # 2) 1200 pares BASE a R$24,97 — margem 22,7%, piso NÃO dispara
    b = simular("BASE", 1200, 24.97, bandeira=True)
    assert b["ajuste_automatico"] is None, b["ajuste_automatico"]
    assert round(b["margem_pct"], 3) == 0.227, b["margem_pct"]
    assert b["bandeira"]["por_par"] == 0.30 and b["fecha"]

    # 3) tier 1000+ com custo real inflado: o preço sobe sozinho até o piso
    salvar_item(None, "Frete + arte customizada (pedido específico)", 3.00, 0.0, "direto")
    assert custo_par("BASE") == 22.31
    c3 = simular("BASE", 1200, 24.97)
    assert c3["ajuste_automatico"] is not None, "auto-ajuste devia ter disparado"
    assert c3["preco_cotado"] > 24.97 and c3["margem_pct"] >= PISO_MARGEM
    assert c3["ajuste_automatico"]["passo"] in PASSOS_AJUSTE

    # log append-only registrou a criação e registra a edição
    salvar_item(None, "Temp", 1.0, 1.0, "direto")
    alvo = [x for x in curva() if x["nome"] == "Temp"][0]
    salvar_item(alvo["id"], "Temp", 2.0, 1.0, "direto")
    h = historico()
    assert any(x["campo"] == "base" and x["de"] == "1.0" and x["para"] == "2.0" for x in h), h[:3]
    remover_item(alvo["id"])
    assert any(x["campo"] == "removido" for x in historico())

    print(json.dumps({"300u": a, "1200u": b, "1200u_custo_inflado": c3},
                     ensure_ascii=False, indent=2))
    print("\nOK — self-check passou.")
