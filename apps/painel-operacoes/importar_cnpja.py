"""Traz leads da captura da CNPJá para a fila de prospecção (`tracker_prospects`).

O BURACO: `leads_cnpja` tem 37.070 empresas com CNPJ, razão social e telefone, e nunca
existiu caminho dela pra fila. A fila lia só `tracker_prospects` (1.512), então a
operação inteira foi dimensionada sobre 5% da base — e ninguém via os outros 95%, porque
o painel não mostra o que não está na tabela que ele lê.

DOIS FILTROS, e os dois têm motivo:
  · CELULAR — a CNPJá devolve telefone no formato pré-2016 (DDD + 8). `normalizar_celular`
    recupera o nono dígito; prefixo 2-5 é fixo e fica fora (fixo não tem WhatsApp, e
    envio que falha conta como sinal ruim contra o número).
  · NOME UTILIZÁVEL — por padrão exige nome FANTASIA. Razão social ("MARIA DA SILVA
    CABELEIREIRA ME") serve pra cadastro e não serve pra abrir conversa; abrir com ela
    entrega na hora que é lista comprada. `--aceitar-razao-social` libera os outros
    31.734, com o custo de a abordagem ficar pior.

NÃO DISPARA NADA. Só popula a fila, com status "A contatar". O kill switch, a janela
comercial e o portão "número tem WhatsApp" continuam entre isto e qualquer envio.

Uso:
    python importar_cnpja.py --dry-run                 # conta, não grava
    python importar_cnpja.py --limite 200 --segmento cabeleireiro
    python importar_cnpja.py --aceitar-razao-social --limite 1000
"""
from __future__ import annotations

import argparse
import os
import re
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from prospeccao_dia import normalizar_celular  # noqa: E402

# Tier de entrada. T2 e não T1: T1 é "sem site", e a CNPJá não diz se a empresa tem site
# — afirmar isso sem ter olhado seria inventar o gancho, que é o que queima o lead.
# A triagem que promove pra T1/T3/T4 é outra etapa, com dado de verdade.
TIER_ENTRADA = "T2"


def _db() -> sqlite3.Connection:
    p = os.environ.get("LEADS_DB", str(Path(__file__).resolve().parents[2] / "data" / "leads.db"))
    c = sqlite3.connect(p, timeout=30)
    c.row_factory = sqlite3.Row
    return c


def _tel8(t: str) -> str:
    return re.sub(r"\D", "", str(t or ""))[-8:]


def candidatos(segmento: str = "", aceitar_razao: bool = False, limite: int = 0) -> list[dict]:
    """Leads da CNPJá prontos pra fila, já sem os que existem no tracker ou no log.

    A dedup é pelos últimos 8 dígitos — mesma chave que o resto do sistema usa, pra um
    número não entrar duas vezes só por estar gravado em formato diferente."""
    with _db() as c:
        vistos = {_tel8(r["telefone"]) for r in c.execute("SELECT telefone FROM tracker_prospects")}
        try:
            vistos |= {_tel8(r["telefone"]) for r in c.execute("SELECT telefone FROM prospeccao_log")}
        except sqlite3.Error:
            pass
        sql = ("SELECT cnpj, razao_social, fantasia, telefone, email, cidade, uf, segmento "
               "FROM leads_cnpja")
        args: tuple = ()
        if segmento:
            sql += " WHERE lower(segmento) = lower(?)"
            args = (segmento,)
        linhas = c.execute(sql, args).fetchall()

    fora: list[dict] = []
    for r in linhas:
        cel = normalizar_celular(r["telefone"])
        if not cel or _tel8(cel) in vistos:
            continue
        fantasia = str(r["fantasia"] or "").strip()
        nome = fantasia or (str(r["razao_social"] or "").strip() if aceitar_razao else "")
        if not nome:
            continue
        vistos.add(_tel8(cel))          # dedup DENTRO do próprio lote também
        cidade = " - ".join(x for x in (str(r["cidade"] or "").strip(),
                                        str(r["uf"] or "").strip()) if x)
        fora.append({
            "empresa": nome, "cnpj": str(r["cnpj"] or "").strip(),
            "razao_social": str(r["razao_social"] or "").strip(),
            "segmento": str(r["segmento"] or "").strip(), "cidade_uf": cidade,
            "telefone": cel, "tier": TIER_ENTRADA,
            # o sinal é o que se sabe DE VERDADE: veio da Receita, não foi verificado.
            "sinal": "captado da base CNPJá — site e presença ainda não verificados",
            "notas": (str(r["email"] or "").strip() or None),
            "usou_razao_social": not fantasia,
        })
        if limite and len(fora) >= limite:
            break
    return fora


def importar(itens: list[dict]) -> int:
    if not itens:
        return 0
    agora = datetime.now(timezone.utc).isoformat()
    with _db() as c:
        c.executemany(
            "INSERT INTO tracker_prospects "
            "(empresa,cnpj,segmento,cidade_uf,telefone,tier,sinal,status,razao_social,"
            " notas,criado_em,atualizado_em) "
            "VALUES (:empresa,:cnpj,:segmento,:cidade_uf,:telefone,:tier,:sinal,"
            "'A contatar',:razao_social,:notas,:agora,:agora)",
            [{**i, "agora": agora} for i in
             ({k: v for k, v in it.items() if k != "usou_razao_social"} for it in itens)])
        c.commit()
    return len(itens)


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--limite", type=int, default=0, help="0 = todos")
    ap.add_argument("--segmento", default="")
    ap.add_argument("--aceitar-razao-social", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    itens = candidatos(a.segmento, a.aceitar_razao_social, a.limite)
    com_razao = sum(1 for i in itens if i["usou_razao_social"])
    print(f"candidatos: {len(itens)}" + (f"  (dos quais {com_razao} só têm razão social)"
                                         if com_razao else ""))
    if itens:
        print("amostra:")
        for i in itens[:5]:
            print(f"  {i['empresa'][:44]:46} {i['telefone']}  {i['cidade_uf']}  [{i['segmento']}]")
    if a.dry_run:
        print("\n--dry-run: nada foi gravado.")
    else:
        print(f"\nimportados: {importar(itens)} (status 'A contatar', tier {TIER_ENTRADA})")
        print("NADA foi disparado — kill switch, janela e portão de WhatsApp seguem valendo.")
