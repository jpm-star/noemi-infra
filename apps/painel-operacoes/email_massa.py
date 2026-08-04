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
# Estrutura (decisão do JP): (1) GARGALO ESPECÍFICO do segmento, não elogio genérico —
# elogio genérico é o que todo mundo manda e o dono já filtra; (2) vender TEMPO
# RECUPERADO, nunca "IA" — dono de clínica não compra tecnologia, compra a agenda
# cheia e a recepção livre; (3) fechar com PERGUNTA DE BAIXA FRICÇÃO, nunca pedindo
# reunião — reunião é caro pro lead responder no primeiro contato.
#
# gargalo = a dor concreta daquele segmento · ganho = o tempo que volta pro dono
_GARGALO = {
    "odontologia": ("paciente que liga pra remarcar e ninguém atende — some e não volta",
                    "a recepção deixa de repetir horário e convênio o dia inteiro"),
    "medico":      ("paciente que liga fora do horário e desiste na secretária eletrônica",
                    "a secretária para de anotar recado e volta a cuidar de quem está na sala"),
    "fisioterapia": ("aluno que cancela em cima da hora e a vaga fica ociosa",
                     "a agenda se reencaixa sozinha em vez de você remanejar no WhatsApp"),
    "academia":    ("quem pergunta o valor do plano à noite e não recebe resposta",
                    "você para de responder 'quanto é a mensalidade?' 20 vezes por dia"),
    "cabeleireiro": ("cliente que manda mensagem pra marcar e a resposta vem 3 horas depois",
                     "você atende no salão sem parar pra olhar o celular a cada corte"),
    "estetica":    ("orçamento pedido no Instagram que morre sem resposta",
                    "some o retrabalho de explicar o mesmo procedimento toda semana"),
    "imobiliaria": ("interessado que pergunta do imóvel no fim de semana e some na segunda",
                    "o corretor chega na segunda com a visita marcada, não com 40 mensagens"),
    "advocacia":   ("consulta que chega por WhatsApp e leva um dia pra ser respondida",
                    "você deixa de triar caso por caso e só olha o que já veio filtrado"),
}
_GARGALO_PADRAO = ("cliente que procura fora do horário e não encontra resposta",
                   "você para de responder a mesma pergunta várias vezes por dia")
def _assunto(lead: dict, nomeado: bool) -> str:
    cidade = lead.get("cidade") or "sua região"
    emp = nome_negocio(lead)
    seg = lead.get("segmento") or "seu segmento"
    # assunto ancora no GARGALO, não no elogio: "uma observação sobre X" some na caixa
    # de entrada; a dor específica do segmento faz o dono parar pra ler.
    if nomeado:
        pn = _primeiro_nome(lead["decisor"])
        alvo = emp or f"{seg} em {cidade}"
        return f"{pn}, sobre os pacientes que ligam e não conseguem falar" if seg in (
            "odontologia", "medico") else f"{pn}, sobre {alvo}"
    return (f"Quem procura {seg} em {cidade} está achando vocês?" if not emp
            else f"{emp}: quem procura {seg} em {cidade} acha vocês?")


def corpo(lead: dict, nomeado: bool) -> str:
    nome_emp = nome_negocio(lead)
    cidade = lead.get("cidade") or "sua região"
    seg = lead.get("segmento") or "seu segmento"
    gargalo, ganho = _GARGALO.get(seg, _GARGALO_PADRAO)
    quem = f"na {nome_emp}" if nome_emp else "aí"
    if nomeado:
        # Faixa C: o e-mail PRECEDE a ligação e avisa dela — é o que faz o "sou eu que
        # te mandei o e-mail" funcionar quando a recepcionista atende. NÃO mexer nisso.
        return (
            f"Oi, {_primeiro_nome(lead['decisor'])}, tudo bem?\n\n"
            f"Aqui é o João, da JPOS. Trabalho com {seg} aqui na região e vejo sempre o "
            f"mesmo gargalo: {gargalo}.\n\n"
            f"O que a gente monta resolve isso em duas frentes — o cliente encontra "
            f"vocês quando procura \"{seg} em {cidade}\", e o primeiro atendimento "
            f"acontece sozinho, na hora. Na prática, {ganho}.\n\n"
            f"Montei um exemplo de como ficaria {quem}. Vou te ligar nos próximos dias "
            f"pra te mostrar em 2 minutos.\n\n"
            f"Faz sentido pra vocês hoje, ou o gargalo aí é outro?\n\n"
            f"Abraço,\nJoão · JPOS"
        )
    return (
        f"Oi! Aqui é o João, da JPOS.\n\n"
        f"Trabalho com {seg} aqui na região e o gargalo que mais aparece é esse: "
        f"{gargalo}.\n\n"
        f"O que a gente monta faz o cliente encontrar vocês quando procura "
        f"\"{seg} em {cidade}\" — e o primeiro atendimento acontece sozinho, na hora. "
        f"Na prática, {ganho}.\n\n"
        f"Montei um exemplo de como ficaria {quem}.\n\n"
        f"Quer que eu mande o link pra você dar uma olhada?\n\n"
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
