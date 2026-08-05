#!/usr/bin/env python3
"""Enriquece leads com CNPJ + QSA (sócios) da CNPJá — o NOME DO DECISOR na ficha.

Por que existe: a ficha de ligação tinha razão social e telefone, mas não o nome de
quem decide. Ligar sem saber com quem falar queima o primeiro contato — "posso falar
com o responsável?" e "o Robson está?" são conversas diferentes.

Fluxo por lead: nome+cidade → busca CNPJá (match ESTRITO do cnpj.py: corte Jaccard +
margem de ambiguidade, DESCARTA em vez de chutar) → grava cnpj/razão em
tracker_prospects e os sócios em tracker_socios, marcando quem DECIDE pelo cargo.

Custo: 1 consulta por lead. Descarta match fraco/ambíguo — CNPJ errado numa lista de
ligação é pior que CNPJ nenhum (o JP liga e fala o nome errado).

Uso:
    python enriquecer_qsa.py --tiers T3,T4 --ver   # quem falta (não gasta crédito)
    python enriquecer_qsa.py --tiers T3,T4 -n 5    # enriquece 5 (teste)
    python enriquecer_qsa.py --tiers T3,T4 -n 70   # o lote todo
"""
from __future__ import annotations

import argparse
import os
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
LEADS_DB = os.environ.get("LEADS_DB", str(Path(__file__).resolve().parents[2] / "data" / "leads.db"))


def _db() -> sqlite3.Connection:
    c = sqlite3.connect(LEADS_DB, timeout=10)
    c.row_factory = sqlite3.Row
    return c


def pendentes(tiers: str = "T3,T4", limite: int = 100) -> list[dict]:
    """Leads do tier SEM sócio cadastrado — os que a ligação hoje pegaria às cegas."""
    ts = [t.strip().upper() for t in tiers.split(",") if t.strip()]
    marcas = ",".join("?" * len(ts))
    with _db() as c:
        return [dict(r) for r in c.execute(
            f"SELECT p.id, p.empresa, p.cidade_uf, p.cnpj, p.tier FROM tracker_prospects p "
            f"WHERE p.tier IN ({marcas}) "
            f"AND NOT EXISTS (SELECT 1 FROM tracker_socios s WHERE s.prospect_id=p.id) "
            f"ORDER BY CASE p.tier WHEN 'T4' THEN 0 WHEN 'T3' THEN 1 ELSE 2 END, p.id",
            (*ts,))][:limite]


def _salvar(lead: dict, r: dict) -> int:
    """Grava CNPJ/razão no prospect e os sócios. Devolve quantos sócios entraram."""
    with _db() as c:
        c.execute("UPDATE tracker_prospects SET cnpj=?, razao_social=? WHERE id=?",
                  (r.get("cnpj", ""), r.get("razao_social", ""), lead["id"]))
        n = 0
        for s in (r.get("qsa") or []):
            c.execute("INSERT INTO tracker_socios (prospect_id,empresa,nome,cargo,telefone,"
                      "poder_decisao,obs) VALUES (?,?,?,?,?,?,?)",
                      (lead["id"], lead["empresa"][:120], s["nome"][:120],
                       s.get("qualificacao", "")[:80], "",
                       "decide" if s.get("decide") else "",
                       f"CNPJá · confiança {r.get('confianca')}"))
            n += 1
        c.commit()
    return n


def rodar(tiers: str = "T3,T4", limite: int = 5, aplicar: bool = False) -> dict:
    import cnpj
    alvos = pendentes(tiers, limite)
    ok = descartados = socios = 0
    linhas = []
    for lead in alvos:
        cid = (lead["cidade_uf"] or "").split("/")[0].strip()
        uf = (lead["cidade_uf"] or "").split("/")[-1].strip() if "/" in (lead["cidade_uf"] or "") else ""
        try:
            r = cnpj.procurar_por_nome(lead["empresa"], cidade=cid, uf=uf)
        except Exception as e:  # noqa: BLE001
            descartados += 1
            linhas.append({**lead, "erro": str(e)[:90]})
            continue
        if not r.get("ok"):
            descartados += 1
            linhas.append({**lead, "motivo": r.get("motivo", "?")})
            continue
        ok += 1
        n = _salvar(lead, r) if aplicar else len(r.get("qsa") or [])
        socios += n
        decisor = next((s["nome"] for s in (r.get("qsa") or []) if s.get("decide")),
                       (r.get("qsa") or [{}])[0].get("nome", ""))
        linhas.append({**lead, "cnpj": r["cnpj"], "razao": r["razao_social"],
                       "decisor": decisor, "socios": n, "conf": r.get("confianca")})
    return {"tentados": len(alvos), "ok": ok, "descartados": descartados,
            "socios": socios, "linhas": linhas}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tiers", default="T3,T4")
    ap.add_argument("-n", type=int, default=5)
    ap.add_argument("--ver", action="store_true", help="só lista quem falta (não gasta crédito)")
    a = ap.parse_args()
    if a.ver:
        p = pendentes(a.tiers, 999)
        print(f"{len(p)} lead(s) {a.tiers} sem decisor:")
        for x in p[:20]:
            print(f"  [{x['tier']}] {x['empresa'][:44]:46s} {x['cidade_uf']}")
        return
    r = rodar(a.tiers, a.n, aplicar=True)
    print(f"\n{r['ok']}/{r['tentados']} enriquecidos · {r['socios']} sócios · "
          f"{r['descartados']} descartados (match fraco/ambíguo)\n")
    for x in r["linhas"]:
        if x.get("decisor"):
            print(f"  ✅ [{x['tier']}] {x['empresa'][:32]:34s} → {x['decisor'][:26]:28s} "
                  f"({x['socios']} sócio(s), conf {x['conf']})")
        else:
            print(f"  ⏭️  [{x['tier']}] {x['empresa'][:32]:34s} — {x.get('motivo') or x.get('erro')}")


if __name__ == "__main__":
    main()
