#!/usr/bin/env python3
"""Candidatos a CNPJ para os leads do tracker que não têm — POR REVISÃO, não automático.

Contexto (medido em 2026-08-06): dos 1512 leads em `tracker_prospects`, só 169 (11%)
têm CNPJ. As duas rotas de enriquecimento automático foram testadas:

  1. cruzar por TELEFONE com `leads_cnpja` (37.070 registros): **interseção ZERO**.
     São capturas independentes — o Places traz o telefone divulgado no Maps, a CNPJá
     traz o do cadastro na Receita. A mesma empresa aparece com números diferentes.
  2. cruzar por NOME + CIDADE: 26 candidatos em 1343 (1,9%), e parte deles é rede de
     franquia ("OrthoDontic"), onde casar a unidade errada é fácil.

Por isso este script NÃO escreve no banco: gera um CSV de candidatos para conferência.
Gravar CNPJ errado num lead é pior que lead sem CNPJ — o CNPJ vira chave de dedup, de
enriquecimento e de nota fiscal.

A rota boa continua sendo a CNPJá por nome/município (`captar_cnpja.py`), que hoje está
sem créditos.

Uso:
    python enriquecer_cnpj_tracker.py                 # gera o CSV de candidatos
"""
from __future__ import annotations

import collections
import csv
import os
import re
import sqlite3
import unicodedata
from pathlib import Path

LEADS_DB = os.environ.get("LEADS_DB", "/root/noemi-infra/data/leads.db")
SAIDA = os.environ.get("SAIDA_CNPJ", "/root/noemi-infra/data/cnpj_candidatos.csv")

# Termos que aparecem em quase toda razão social do ramo e não distinguem ninguém.
_RUIDO = r"\b(ltda|me|epp|eireli|sa|s/a|clinica|odontologia|odontologica|dr|dra|consultorio)\b"


def norm(s: str | None) -> str:
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", " ", re.sub(_RUIDO, " ", s)).strip()


def cidade(s: str | None) -> str:
    return norm((s or "").split("/")[0].split("-")[0])


def candidatos(db: str = LEADS_DB) -> list[dict]:
    c = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    idx: dict[tuple, list] = collections.defaultdict(list)
    for cnpj, rs, fan, cid, seg in c.execute(
            "select cnpj, razao_social, fantasia, cidade, segmento from leads_cnpja"):
        for nome in (rs, fan):
            n = norm(nome)
            if len(n) >= 8:
                idx[(n, cidade(cid))].append({"cnpj": cnpj, "razao_social": rs, "segmento": seg})

    saida = []
    for i, emp, cu, seg in c.execute(
            "select id, empresa, cidade_uf, segmento from tracker_prospects "
            "where cnpj is null or trim(cnpj)=''"):
        k = (norm(emp), cidade(cu))
        achados = idx.get(k) or []
        if len(k[0]) >= 8 and len(achados) == 1:   # ambíguo não entra nem como candidato
            saida.append({"lead_id": i, "empresa": emp, "cidade_uf": cu,
                          "segmento_lead": seg, "cnpj_candidato": achados[0]["cnpj"],
                          "razao_social_cnpja": achados[0]["razao_social"],
                          "segmento_cnpja": achados[0]["segmento"], "conferido": ""})
    c.close()
    return saida


def _check() -> None:
    assert norm("Clínica Odontológica Bem Viver LTDA") == "bem viver"
    assert norm("Dia Do Sorriso") == "dia do sorriso"
    assert cidade("Bauru/SP") == "bauru"
    assert cidade("São José do Rio Preto - SP") == "sao jose do rio preto"
    print("self-check ok — normalização de nome e cidade")


if __name__ == "__main__":
    import sys
    if "--check" in sys.argv:
        _check()
        raise SystemExit(0)
    linhas = candidatos()
    Path(SAIDA).parent.mkdir(parents=True, exist_ok=True)
    with open(SAIDA, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(linhas[0].keys()) if linhas else
                           ["lead_id", "empresa", "cnpj_candidato"])
        w.writeheader()
        w.writerows(linhas)
    print(f"{len(linhas)} candidato(s) para conferência em {SAIDA}")
    print("NADA foi escrito no banco — confira a coluna 'conferido' antes de aplicar.")
