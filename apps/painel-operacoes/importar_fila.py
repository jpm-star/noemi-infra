#!/usr/bin/env python3
"""Importa a fila T1/T2 do leads.db (JPOS) pra fila de prospecção do sdr-motor.

Dois bancos, dois sistemas: leads.db (SQLite, noemi-infra) tem os 1503 leads curados;
a fila que dispara vive em `prospects` (Postgres, sdr-motor). Esta ponte usa a API que
JÁ existe (`POST /api/painel/prospects`) em vez de escrever no Postgres direto — assim
a normalização de telefone, o dedup e a classificação de segmento continuam num lugar só.

LOTE CONTROLADO (decisão do JP): 20 por vez, nunca a base toda. Com 975 celulares
válidos e teto de ~25/dia, importar tudo criaria fila de 39 dias — e qualquer bug no
meio viraria envio errado em escala. Importar em lote mantém o erro pequeno e reversível.

Só entra quem: tier T1/T2 · sem contato no prospeccao_log · CELULAR (fixo não tem
WhatsApp e queimaria a instância única) · não importado antes.

Uso:
    python importar_fila.py --ver              # mostra o próximo lote (não envia nada)
    python importar_fila.py --enviar           # importa 20
    python importar_fila.py --enviar -n 5      # importa 5
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sqlite3
import sys
import urllib.request
from pathlib import Path

LEADS_DB = os.environ.get("LEADS_DB", str(Path(__file__).resolve().parents[2] / "data" / "leads.db"))
SDR_URL = os.environ.get("SDR_MOTOR_URL", "http://127.0.0.1:8007").rstrip("/")
SDR_USER = os.environ.get("SDR_MOTOR_USER", "")
SDR_SENHA = os.environ.get("SDR_MOTOR_SENHA", "")
CAMPANHA = os.environ.get("CAMPANHA", "JPOS T1/T2 sem site")


def _tel8(t: str) -> str:
    return re.sub(r"\D", "", str(t or ""))[-8:]


def eh_celular(tel: str) -> bool:
    """Celular BR = DDD + 9 + 8 dígitos. Fixo não tem WhatsApp: fica fora da fila.
    (Mesma regra do evolution.eh_fixo do sdr-motor — aqui é o filtro de origem.)"""
    d = re.sub(r"\D", "", str(tel or ""))
    d = d[2:] if d.startswith("55") and len(d) > 11 else d
    if len(d) == 10 and d[2] in "6789":  # celular antigo sem o 9 → ainda é celular
        return True
    return len(d) == 11 and d[2] == "9"


def proximo_lote(n: int = 20) -> list[dict]:
    """Os N próximos leads elegíveis, T1 antes de T2 (meta maior, gancho mais simples)."""
    c = sqlite3.connect(LEADS_DB)
    c.row_factory = sqlite3.Row
    try:
        try:
            ja = {_tel8(r[0]) for r in c.execute("SELECT telefone FROM prospeccao_log")}
        except sqlite3.Error:
            ja = set()
        rows = [dict(r) for r in c.execute(
            "SELECT id,empresa,segmento,cidade_uf,telefone,tier FROM tracker_prospects "
            "WHERE tier IN ('T1','T2') AND telefone!='' ORDER BY CASE tier WHEN 'T1' THEN 0 ELSE 1 END, id")]
    finally:
        c.close()
    fora = []
    for r in rows:
        tel = r["telefone"]
        if _tel8(tel) in ja or not eh_celular(tel):
            continue
        cidade = (r["cidade_uf"] or "").strip()
        uf = cidade.split("/")[-1].strip().upper() if "/" in cidade else ""
        fora.append({"telefone": tel, "nome": (r["empresa"] or "").strip()[:120],
                     "ramo": (r["segmento"] or "").strip() or None,
                     "cidade": cidade.split("/")[0].strip() or None,
                     "estado": uf if len(uf) == 2 else None,
                     "_tier": r["tier"]})
        if len(fora) >= n:
            break
    return fora


def enviar(lote: list[dict]) -> dict:
    """POST no importador do sdr-motor (dedup/normalização/classificação são dele)."""
    if not lote:
        return {"ok": True, "inseridos": 0, "aviso": "lote vazio"}
    if not SDR_USER or not SDR_SENHA:
        return {"ok": False, "erro": "faltam SDR_MOTOR_USER e SDR_MOTOR_SENHA no ambiente"}
    # login → cookie/token de sessão
    try:
        req = urllib.request.Request(
            f"{SDR_URL}/api/painel/login", method="POST",
            data=json.dumps({"usuario": SDR_USER, "senha": SDR_SENHA}).encode(),
            headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=30) as r:
            cookie = r.headers.get("Set-Cookie", "")
            tok = (json.loads(r.read().decode() or "{}") or {}).get("token", "")
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "erro": f"login falhou: {exc}"}
    corpo = {"prospects": [{k: v for k, v in p.items() if not k.startswith("_")} for p in lote],
             "campanha": CAMPANHA}
    hdr = {"Content-Type": "application/json"}
    if cookie:
        hdr["Cookie"] = cookie.split(";")[0]
    if tok:
        hdr["Authorization"] = f"Bearer {tok}"
    try:
        req = urllib.request.Request(f"{SDR_URL}/api/painel/prospects", method="POST",
                                     data=json.dumps(corpo).encode(), headers=hdr)
        with urllib.request.urlopen(req, timeout=60) as r:
            return {"ok": True, **(json.loads(r.read().decode() or "{}"))}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "erro": f"import falhou: {exc}"}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--enviar", action="store_true", help="importa de verdade (sem isto, só mostra)")
    ap.add_argument("-n", type=int, default=20, help="tamanho do lote (default 20)")
    a = ap.parse_args()
    lote = proximo_lote(a.n)
    print(f"próximo lote: {len(lote)} lead(s)")
    for p in lote:
        print(f"  [{p['_tier']}] {p['nome'][:38]:38s} {p['telefone']:18s} {p.get('cidade') or ''}")
    if not a.enviar:
        print("\n(simulação — use --enviar pra importar de verdade)")
        return
    r = enviar(lote)
    print("\n", r)
    sys.exit(0 if r.get("ok") else 1)


if __name__ == "__main__":
    main()
