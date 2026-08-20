"""Pé Di · primeiro toque — da lista de 138 pro WhatsApp aberto, em um clique.

O CSV de leads não gera dinheiro; a mensagem enviada gera. Entre um e outro havia
quatro passos manuais (achar a linha, copiar o número, escrever o texto, lembrar o
preço da faixa). Este módulo colapsa os quatro num botão: abre o WhatsApp do lead
com a mensagem do segmento dele já escrita, com o preço vindo da calculadora.

NÃO dispara nada. Monta o link `wa.me` e registra o que JP marcou como enviado —
o envio é clique humano, um a um. Disparo em massa queima o número e não é o que
138 leads frios pedem.

ponytail: o texto é template com 3 buracos, não LLM. Mensagem de primeiro toque é
curta e repetitiva por natureza; gerar por modelo custaria dinheiro, latência e a
chance de inventar preço errado numa conversa comercial.
"""
from __future__ import annotations

import csv
import os
import re
import sqlite3
import urllib.parse
from datetime import datetime, timezone
from pathlib import Path

_RAIZ = Path(__file__).resolve().parents[2]
_DB = Path(os.environ.get("PEDI_LEADS_DB", str(_RAIZ / "data" / "pedi_leads.db")))
_CSV = Path(os.environ.get("PEDI_LEADS_CSV", "/root/jpos-entregaveis/pedi_leads.csv"))

# Quantidade de referência por segmento pra cotar já na primeira frase. Preço vem
# de pedi_custo (mesma fonte da calculadora) — nunca digitado aqui, senão o texto
# e a calculadora divergem no dia em que a curva mudar.
GANCHO = {
    "Assessoria esportiva": {
        "qtd": 300,
        "texto": ("Oi! Aqui é o João Pedro, da Pé Di, de Lins. Vi que vocês organizam "
                  "treino e prova aí em {cidade}.\n\nA gente faz chinelo personalizado "
                  "pra kit de atleta — com a marca de vocês na palmilha e na tira. "
                  "Em lote de {qtd} pares fica em torno de {preco} o par, já com nota.\n\n"
                  "Quer que eu mande uma arte simulando com a logo de vocês? Sem "
                  "compromisso, só pra ver como fica."),
    },
    "Cerimonialista / buffet": {
        "qtd": 200,
        "texto": ("Oi! Aqui é o João Pedro, da Pé Di, de Lins.\n\nA gente faz o chinelo "
                  "de descanso personalizado pros convidados — aquele que fica na "
                  "cestinha do banheiro ou entra na hora da pista. Com a arte do casal "
                  "ou do evento.\n\nEm lote de {qtd} pares sai por volta de {preco} o par. "
                  "Quer que eu mande uma simulação com a arte de um evento de vocês?"),
    },
    "Academia / box de crossfit": {
        "qtd": 150,
        "texto": ("Oi! Aqui é o João Pedro, da Pé Di, de Lins.\n\nVi que vocês fazem "
                  "campeonato interno aí em {cidade}. A gente faz chinelo personalizado "
                  "com a marca do box — funciona bem como brinde de inscrição ou "
                  "premiação.\n\nEm lote de {qtd} pares fica em torno de {preco} o par. "
                  "Quer ver uma arte simulada com a logo de vocês?"),
    },
    "Organizadora de evento corporativo": {
        "qtd": 300,
        "texto": ("Oi! Aqui é o João Pedro, da Pé Di, de Lins.\n\nA gente fabrica chinelo "
                  "personalizado pra brinde corporativo — confraternização, convenção, "
                  "kit de recepção. Produção própria, então prazo e arte a gente "
                  "controla.\n\nEm lote de {qtd} pares fica em torno de {preco} o par, "
                  "com nota. Vale eu mandar o material pra vocês terem na mão quando "
                  "um cliente pedir brinde?"),
    },
    "Clube de triathlon / natação": {
        "qtd": 200,
        "texto": ("Oi! Aqui é o João Pedro, da Pé Di, de Lins.\n\nPra quem sai da piscina "
                  "ou da prova, chinelo é o item que todo mundo usa na hora. A gente faz "
                  "personalizado com a marca do clube, pra kit de prova ou pra vender na "
                  "secretaria.\n\nEm lote de {qtd} pares fica em torno de {preco} o par. "
                  "Quer que eu mande uma simulação?"),
    },
}
PADRAO = "Assessoria esportiva"


def _conn() -> sqlite3.Connection:
    _DB.parent.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(_DB, timeout=10)
    c.row_factory = sqlite3.Row
    c.execute("CREATE TABLE IF NOT EXISTS toque ("
              "lead_id TEXT PRIMARY KEY, ts TEXT NOT NULL, resultado TEXT NOT NULL DEFAULT 'enviado')")
    return c


def _fone_wa(bruto: str) -> str:
    """(14) 99832-0333 -> 5514998320333. Vazio se não der um número discável."""
    d = re.sub(r"\D", "", bruto or "")
    if len(d) < 10:
        return ""
    return d if d.startswith("55") else "55" + d


def preco_sugerido(qtd: int) -> str:
    """Preço da faixa vindo da MESMA curva da calculadora, já com imposto embutido —
    é o número que o cliente vai ouvir, não o preço líquido interno."""
    import pedi_custo
    partida = pedi_custo.PRECO_PARTIDA_1000 if qtd >= 1000 else 25.97
    s = pedi_custo.simular("BASE", qtd, partida)
    return f"R$ {s['preco_final_cliente']:.2f}".replace(".", ",")


def _mensagem(lead: dict) -> tuple[str, int]:
    g = GANCHO.get(lead["Segmento"], GANCHO[PADRAO])
    qtd = g["qtd"]
    txt = g["texto"].format(cidade=lead.get("Cidade") or "sua região", qtd=qtd,
                            preco=preco_sugerido(qtd))
    return txt, qtd


def fila(limite: int = 200, incluir_tocados: bool = False) -> list[dict]:
    """Fila pronta pra disparar: melhor score primeiro, já com link do WhatsApp."""
    if not _CSV.exists():
        return []
    with _CSV.open(encoding="utf-8-sig") as f:
        leads = list(csv.DictReader(f))
    with _conn() as c:
        tocados = {r["lead_id"]: dict(r) for r in c.execute("SELECT * FROM toque")}
    fora = []
    for l in leads:
        wa = _fone_wa(l.get("Telefone/WhatsApp", ""))
        if not wa:
            continue  # sem número discável não é fila de WhatsApp
        marca = tocados.get(l["ID"])
        if marca and not incluir_tocados:
            continue
        txt, qtd = _mensagem(l)
        fora.append({
            "id": l["ID"], "empresa": l["Empresa"], "segmento": l["Segmento"],
            "cidade": l["Cidade"], "telefone": l["Telefone/WhatsApp"],
            "instagram": l.get("Instagram", ""), "site": l.get("Site", ""),
            "score": int(l["Score (1-10)"]), "qtd_cotada": qtd, "mensagem": txt,
            "link": f"https://wa.me/{wa}?text={urllib.parse.quote(txt)}",
            "tocado_em": marca["ts"] if marca else None,
            "resultado": marca["resultado"] if marca else None,
        })
        if len(fora) >= limite:
            break
    return fora


def marcar(lead_id: str, resultado: str = "enviado") -> dict:
    """Append/atualiza o toque. Sem isso a fila repete o mesmo lead amanhã."""
    ts = datetime.now(timezone.utc).isoformat(timespec="seconds")
    with _conn() as c:
        c.execute("INSERT INTO toque (lead_id,ts,resultado) VALUES (?,?,?) "
                  "ON CONFLICT(lead_id) DO UPDATE SET ts=excluded.ts, resultado=excluded.resultado",
                  (lead_id, ts, (resultado or "enviado")[:30]))
        c.commit()
    return {"lead_id": lead_id, "ts": ts, "resultado": resultado}


def placar() -> dict:
    with _conn() as c:
        linhas = list(c.execute("SELECT resultado, COUNT(*) n FROM toque GROUP BY resultado"))
    por = {r["resultado"]: r["n"] for r in linhas}
    total_csv = len(fila(limite=10_000, incluir_tocados=True))
    return {"tocados": sum(por.values()), "restam": total_csv - sum(por.values()),
            "por_resultado": por, "total": total_csv}


if __name__ == "__main__":
    import json
    import sys
    import tempfile
    if "--selfcheck" in sys.argv:
        _DB = Path(tempfile.mkdtemp()) / "t.db"
        assert _fone_wa("(14) 99832-0333") == "5514998320333"
        assert _fone_wa("3322-5776") == ""          # fixo sem DDD não vai pro WhatsApp
        assert _fone_wa("5514998320333") == "5514998320333"  # já normalizado, não duplica o 55
        m, q = _mensagem({"Segmento": "Cerimonialista / buffet", "Cidade": "Bauru"})
        assert "convidados" in m and q == 200 and "R$" in m
        m2, _ = _mensagem({"Segmento": "Assessoria esportiva", "Cidade": "Jaú"})
        assert "Jaú" in m2 and "João Pedro" in m2
        # segmento desconhecido não pode quebrar a fila nem mandar texto vazio
        m3, _ = _mensagem({"Segmento": "Coisa Nova", "Cidade": "Lins"})
        assert len(m3) > 80
        print("OK — self-check do primeiro toque passou.")
    else:
        print(json.dumps({"placar": placar(), "primeiros": fila(3)}, ensure_ascii=False, indent=2))
