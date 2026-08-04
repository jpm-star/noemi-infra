#!/usr/bin/env python3
"""Segmenta os leads da CNPJá por ALCANCE e prepara o e-mail de cada faixa.

Por que "alcance" e não "tier": a CNPJá não diz se a empresa tem site — então
afirmar T1..T4 a partir dela seria inventar. O que o dado permite afirmar é por
onde dá pra CHEGAR no lead, que é o que decide o canal:

  A) celular            -> fila de WhatsApp (fluxo T1/T2 que já roda)
  B) fixo + e-mail, SEM decisor -> e-mail em massa, oferta de site
  C) fixo + e-mail, COM decisor -> e-mail NOMEADO, preparando a ligação (T4)

A faixa C é a que muda o jogo: o e-mail chega ANTES da ligação, então quando o JP
liga não é mais cold — é "sou eu que te mandei aquele e-mail". É como se passa da
recepcionista.

Enfileira em `emails` (services/email/outbound.py) — NÃO envia. O envio é do
processar_fila, com teto diário próprio.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sqlite3
import sys
from pathlib import Path

_AQUI = Path(__file__).resolve().parent
sys.path.insert(0, str(_AQUI))
sys.path.insert(0, str(_AQUI.parents[1] / "services" / "email"))
LEADS_DB = os.environ.get("LEADS_DB", str(_AQUI.parents[1] / "data" / "leads.db"))

FAIXA_WHATS = "whatsapp"      # celular: já tem fluxo próprio
FAIXA_MASSA = "email_massa"   # fixo + e-mail, sem decisor
FAIXA_NOMEADO = "email_nomeado"  # fixo + e-mail, com decisor -> pré-ligação


def _celular(tel: str) -> bool:
    d = re.sub(r"\D", "", str(tel or ""))
    d = d[2:] if d.startswith("55") and len(d) > 11 else d
    return len(d) == 11 and d[2] == "9"


def _primeiro_nome(nome: str) -> str:
    """'Paulo Domingos Ribeiro Junior' -> 'Paulo'. Tratamento por primeiro nome soa
    humano; nome completo em e-mail soa mala direta."""
    p = (nome or "").strip().split()
    return p[0].capitalize() if p else ""


_SUFIXO = re.compile(r"\b(LTDA|ME|EPP|EIRELI|S/?A|SA|MEI|SOCIEDADE\s+SIMPLES|"
                     r"UNIPESSOAL|SS|CIA)\b\.?", re.I)


def nome_negocio(lead: dict) -> str:
    """Nome apresentável do negócio. A razão social vem em CAIXA ALTA e com sufixo
    societário ('IOCPD LTDA'), o que grita mala direta num e-mail. Prefere o nome
    fantasia; senão limpa a razão. E, quando a razão é NOME DE PESSOA (MEI), devolve
    '' — porque "a PAULO ALCEU KIEMLE TRINDADE não aparece no Google" é constrangedor."""
    fantasia = (lead.get("fantasia") or "").strip()
    bruto = fantasia or (lead.get("razao_social") or "").strip()
    if not bruto:
        return ""
    limpo = _SUFIXO.sub("", bruto).replace("  ", " ").strip(" -·,")
    if not limpo:
        return ""
    # heurística de pessoa física: sem fantasia, sem termo de negócio e com cara de
    # nome próprio (2+ palavras, nenhuma genérica de empresa).
    if not fantasia:
        termos = ("clinica", "clínica", "odonto", "centro", "instituto", "academia",
                  "estetica", "estética", "salao", "salão", "imobiliaria", "imobiliária",
                  "advocacia", "consultorio", "consultório", "studio", "espaco", "espaço",
                  "lab", "hospital", "escritorio", "escritório")
        if not any(t in limpo.lower() for t in termos):
            return ""  # provável pessoa física: cai no tratamento genérico
    return limpo.title() if limpo.isupper() else limpo


def _decisor(socios_json: str) -> dict:
    """Sócio que DECIDE (administrador/titular vence), senão o primeiro."""
    try:
        socios = json.loads(socios_json or "[]")
    except ValueError:
        return {}
    if not socios:
        return {}
    chave = ("administrador", "titular", "presidente", "diretor")
    for s in socios:
        if any(k in (s.get("cargo") or "").lower() for k in chave):
            return s
    return socios[0]


def segmentar() -> dict:
    """Classifica a base capturada por alcance. Só leitura — não altera nada."""
    faixas: dict[str, list[dict]] = {FAIXA_WHATS: [], FAIXA_MASSA: [], FAIXA_NOMEADO: []}
    with sqlite3.connect(LEADS_DB) as c:
        c.row_factory = sqlite3.Row
        try:
            rows = c.execute("SELECT cnpj,razao_social,fantasia,telefone,email,cidade,"
                             "uf,segmento,socios FROM leads_cnpja").fetchall()
        except sqlite3.Error:
            return {k: [] for k in faixas}
    for r in rows:
        d = dict(r)
        if _celular(d["telefone"]):
            faixas[FAIXA_WHATS].append(d)
            continue
        if not (d["email"] or "").strip():
            continue  # sem e-mail e sem celular: só serve pra ligação fria
        dec = _decisor(d["socios"])
        d["decisor"] = dec.get("nome", "")
        d["cargo"] = dec.get("cargo", "")
        faixas[FAIXA_NOMEADO if d["decisor"] else FAIXA_MASSA].append(d)
    return faixas


# ── copy ─────────────────────────────────────────────────────────────────────
# Mesmo gancho honesto já validado no WhatsApp: dor verificável, sem contato forjado.
def _assunto(lead: dict, nomeado: bool) -> str:
    cidade = lead.get("cidade") or "sua região"
    emp = nome_negocio(lead)
    if nomeado:
        pn = _primeiro_nome(lead["decisor"])
        return f"{pn}, uma observação sobre {emp}" if emp else f"{pn}, sobre a presença de vocês no Google"
    return f"Site pra {emp} em {cidade}" if emp else f"Site pra {lead.get('segmento','seu negócio')} em {cidade}"


def corpo(lead: dict, nomeado: bool) -> str:
    nome_emp = nome_negocio(lead)
    cidade = lead.get("cidade") or "sua região"
    seg = lead.get("segmento") or "seu segmento"
    if nomeado:
        # T4: e-mail que PRECEDE a ligação. Avisa que vai ligar — é isso que faz o
        # "sou eu que te mandei o e-mail" funcionar quando a recepcionista atende.
        return (
            f"Oi, {_primeiro_nome(lead['decisor'])}, tudo bem?\n\n"
            f"Aqui é o João, da JPOS. Trabalhamos com site e integração de IA pra "
            f"negócios locais.\n\n"
            f"Dei uma olhada {('na ' + nome_emp) if nome_emp else 'no negócio de vocês'} e reparei alguns pontos que dá pra melhorar "
            f"na presença de vocês na internet — quem procura \"{seg} em {cidade}\" "
            f"hoje tem dificuldade de achar vocês.\n\n"
            f"Preparei um exemplo de como ficaria. Vou te ligar nos próximos dias pra "
            f"te mostrar em 2 minutos; se preferir, é só responder este e-mail que eu "
            f"mando o link antes.\n\n"
            f"Abraço,\nJoão · JPOS"
        )
    return (
        f"Oi! Aqui é o João, da JPOS.\n\n"
        f"Reparei que {('a ' + nome_emp) if nome_emp else 'vocês'} não aparece{'' if nome_emp else 'm'} quando alguém procura "
        f"\"{seg} em {cidade}\" no Google — e quem aparece acaba levando esse cliente.\n\n"
        f"A gente faz site pra negócio local, com atendimento no WhatsApp integrado. "
        f"Posso te mandar um exemplo pronto, do jeito que ficaria pra vocês, "
        f"sem compromisso?\n\n"
        f"Abraço,\nJoão · JPOS"
    )


def preparar(faixa: str, limite: int = 50, aplicar: bool = False) -> dict:
    """Enfileira o e-mail da faixa (LOTE CONTROLADO — nunca a base toda de uma vez:
    domínio novo que dispara 35 mil e-mails de uma vez vira spam na hora)."""
    import outbound
    faixas = segmentar()
    alvo = faixas.get(faixa) or []
    nomeado = faixa == FAIXA_NOMEADO
    # não repete quem já está na fila/enviado
    ja: set[str] = set()
    with sqlite3.connect(LEADS_DB) as c:
        try:
            ja = {r[0] for r in c.execute("SELECT to_addr FROM emails")}
        except sqlite3.Error:
            ja = set()
    postos, amostra = 0, []
    for lead in alvo:
        if postos >= limite:
            break
        em = (lead.get("email") or "").strip().lower()
        if not em or em in ja:
            continue
        ja.add(em)
        assunto, txt = _assunto(lead, nomeado), corpo(lead, nomeado)
        if aplicar:
            outbound.enfileirar(em, assunto, txt, lead_id=lead.get("cnpj"))
        postos += 1
        if len(amostra) < 2:
            amostra.append({"para": em, "assunto": assunto, "corpo": txt})
    return {"faixa": faixa, "disponiveis": len(alvo), "enfileirados": postos,
            "amostra": amostra}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ver", action="store_true", help="só mostra a segmentação")
    ap.add_argument("--faixa", default=FAIXA_NOMEADO,
                    choices=[FAIXA_MASSA, FAIXA_NOMEADO, FAIXA_WHATS])
    ap.add_argument("-n", type=int, default=50, help="tamanho do lote")
    ap.add_argument("--enfileirar", action="store_true", help="grava na fila de envio")
    a = ap.parse_args()
    if a.ver or not a.enfileirar:
        f = segmentar()
        print("SEGMENTAÇÃO POR ALCANCE (o que decide o canal):")
        print(f"  A) celular            -> fila WhatsApp    : {len(f[FAIXA_WHATS])}")
        print(f"  B) fixo+email s/ decisor -> e-mail massa  : {len(f[FAIXA_MASSA])}")
        print(f"  C) fixo+email c/ decisor -> e-mail NOMEADO: {len(f[FAIXA_NOMEADO])}")
        if f[FAIXA_NOMEADO]:
            x = f[FAIXA_NOMEADO][0]
            print(f"\n  exemplo da faixa C: {x['razao_social'][:40]}")
            print(f"    decisor: {x['decisor']} ({x['cargo']}) · {x['email']}")
        return
    r = preparar(a.faixa, a.n, aplicar=True)
    print(f"\n  faixa {r['faixa']}: {r['enfileirados']} enfileirados de {r['disponiveis']} disponíveis")
    for x in r["amostra"]:
        print(f"\n  --- para: {x['para']}")
        print(f"  assunto: {x['assunto']}")
        print("  " + x["corpo"].replace("\n", "\n  ")[:420])


if __name__ == "__main__":
    main()
