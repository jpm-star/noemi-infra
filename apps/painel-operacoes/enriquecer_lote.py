"""Enriquece tracker_prospects com CNPJ+razão+sócios via CNPJá (nome+cidade→CNPJ).

Idempotente (pula quem já tem cnpj), incremental (commita a cada match), seguro
(só grava match confiável do matcher estrito do cnpj.py; ambíguo/fraco fica vazio).
Uso: LEADS_DB=/caminho/leads.db CNPJA_API_KEY=... python enriquecer_lote.py [limite]
"""
from __future__ import annotations

import os
import sqlite3
import sys
import time

import cnpj

DB = os.environ.get("LEADS_DB", "data/leads.db")
PAUSA = float(os.environ.get("CNPJA_PAUSA", "0.4"))  # gentileza entre chamadas


def main(limite: int | None = None):
    c = sqlite3.connect(DB)
    c.row_factory = sqlite3.Row
    q = "SELECT id, empresa, cidade_uf FROM tracker_prospects WHERE cnpj IS NULL OR TRIM(cnpj)=''"
    if limite:
        q += f" LIMIT {int(limite)}"
    leads = c.execute(q).fetchall()
    total = len(leads)
    print(f"[enriquecer] {total} leads sem CNPJ em {DB}", flush=True)
    ok = 0
    for i, lead in enumerate(leads, 1):
        cid = (lead["cidade_uf"] or "").split("/")[0].strip()
        uf = lead["cidade_uf"].split("/")[1].strip() if "/" in (lead["cidade_uf"] or "") else ""
        try:
            r = cnpj.procurar_por_nome(lead["empresa"], cid, uf, limite=30)
        except cnpj._SemCredito:
            print(f"[enriquecer] PAROU em {i}/{total}: CNPJá sem créditos. "
                  f"{ok} preenchidos até aqui. Recarregue e rode de novo (idempotente).", flush=True)
            break
        if r.get("ok"):
            ok += 1
            c.execute("UPDATE tracker_prospects SET cnpj=?, razao_social=?, atualizado_em=datetime('now') WHERE id=?",
                      (r["cnpj"], r["razao_social"], lead["id"]))
            # sócios → tracker_socios (limpa os antigos desse prospect antes, idempotente)
            c.execute("DELETE FROM tracker_socios WHERE prospect_id=?", (lead["id"],))
            for s in r.get("qsa", []):
                c.execute("""INSERT INTO tracker_socios (prospect_id, empresa, nome, cargo, poder_decisao, obs)
                             VALUES (?,?,?,?,?,?)""",
                          (lead["id"], r["razao_social"], s["nome"], s["qualificacao"],
                           "sim" if s["decide"] else "", "CNPJá"))
            c.commit()
        if i % 50 == 0 or i == total:
            print(f"[enriquecer] {i}/{total} | matches={ok} ({100*ok//max(i,1)}%)", flush=True)
        time.sleep(PAUSA)
    print(f"[enriquecer] FIM: {ok}/{total} preenchidos ({100*ok//max(total,1)}%)", flush=True)
    return ok, total


if __name__ == "__main__":
    main(int(sys.argv[1]) if len(sys.argv) > 1 else None)
