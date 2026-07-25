"""Handoff de contato — quem a IA atende e por quanto tempo.

CONHECIDO (cliente/parceiro/família, lista editável no painel): a IA responde
1 mensagem e PARA, aguardando o JP decidir. DESCONHECIDO (prospecção fria): a
IA executa o pipeline completo. A lista NÃO é hardcoded — mora em
data/contatos_conhecidos.json, editável pelo /obs.

`politica(numero, ja_respondeu)` é PURA (sem I/O) — o motor de conversa (SDR)
chama antes de responder. Este módulo só decide; o enforcement é do SDR.
"""
from __future__ import annotations

import json
import re

MODOS = {"uma_msg", "ia_livre", "so_eu"}  # 1 resposta+pausa | IA livre | IA muda
MODO_PADRAO = "uma_msg"

# ações que a política devolve (o SDR mapeia pra comportamento):
RESPONDER = "responder"              # pipeline normal (frio ou IA livre)
RESPONDER_E_PAUSAR = "responder_e_pausar"  # manda 1 e pausa o bot p/ o JP assumir
SILENCIAR = "silenciar"             # IA não responde (já fez a 1ª, ou modo só-eu)


def _norm(n: str) -> str:
    return re.sub(r"\D", "", n or "")


def _caminho():
    from shared_core.storage import db
    return db.data_dir() / "contatos_conhecidos.json"


def carregar() -> dict[str, dict]:
    """{numero_normalizado: {'nome':..., 'modo':...}}. {} se não existe/ilegível."""
    try:
        d = json.loads(_caminho().read_text("utf-8"))
    except (OSError, ValueError):
        return {}
    itens = d.get("contatos", d) if isinstance(d, dict) else d
    out: dict[str, dict] = {}
    for c in (itens if isinstance(itens, list) else []):
        num = _norm(str(c.get("numero", "")))
        if num:
            modo = c.get("modo") if c.get("modo") in MODOS else MODO_PADRAO
            out[num] = {"nome": str(c.get("nome", ""))[:80], "modo": modo}
    return out


def salvar(contatos: list[dict]) -> list[dict]:
    """Grava a lista saneada (só numero/nome/modo válidos). Devolve o que gravou."""
    limpos, vistos = [], set()
    for c in contatos if isinstance(contatos, list) else []:
        num = _norm(str(c.get("numero", "")))
        if not num or num in vistos:
            continue
        vistos.add(num)
        modo = c.get("modo") if c.get("modo") in MODOS else MODO_PADRAO
        limpos.append({"numero": num, "nome": str(c.get("nome", ""))[:80], "modo": modo})
    p = _caminho()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"contatos": limpos}, ensure_ascii=False, indent=2), "utf-8")
    return limpos


def politica(numero: str, ja_respondeu: bool, conhecidos: dict | None = None) -> str:
    """Decide a ação da IA pra este contato. PURA: `conhecidos` injetável (senão
    carrega). `ja_respondeu` = a IA já mandou alguma msg pra este contato."""
    conhecidos = carregar() if conhecidos is None else conhecidos
    c = conhecidos.get(_norm(numero))
    if not c:                       # desconhecido → prospecção fria completa
        return RESPONDER
    if c["modo"] == "ia_livre":     # conhecido que liberou a IA
        return RESPONDER
    if c["modo"] == "so_eu":        # conhecido que só o JP atende
        return SILENCIAR
    return SILENCIAR if ja_respondeu else RESPONDER_E_PAUSAR  # uma_msg


if __name__ == "__main__":  # self-check: 4 caminhos da política (puro, sem I/O)
    conh = {"5511000000001": {"nome": "Tio", "modo": "uma_msg"},
            "5511000000002": {"nome": "Parceiro", "modo": "ia_livre"},
            "5511000000003": {"nome": "Chefe", "modo": "so_eu"}}
    assert politica("5511999999999", False, conh) == RESPONDER          # desconhecido
    assert politica("+55 11 00000-0001", False, conh) == RESPONDER_E_PAUSAR  # 1ª msg
    assert politica("5511000000001", True, conh) == SILENCIAR           # já respondeu
    assert politica("5511000000002", True, conh) == RESPONDER           # IA livre
    assert politica("5511000000003", False, conh) == SILENCIAR          # só o JP
    print("contatos OK — desconhecido responde; conhecido 1x-e-pausa; livre/só-eu")
