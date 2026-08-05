#!/usr/bin/env python3
"""TIER COMO CONTRATO — o motor sabe o que cada tier cobre e recusa entregar incompleto.

Hoje o tier é etiqueta: o JP escolhe T2 e sai o mesmo site do T1, porque o motor não
sabe o que "T2" obriga. Aqui o tier vira CONTRATO em dois sentidos:

  ESCOPO   — o que o motor EXECUTA naquele tier (o que entrega a mais que o anterior).
  REQUISITO — o material MÍNIMO que sustenta aquele escopo.

A regra que muda o produto: se o material não sustenta o tier, avisa ANTES de gerar.
Entregar um "T2" que é um T1 com etiqueta é pior que recusar — o JP vende multi-página
+ SEO, o cliente recebe uma landing, e quem descobre é o cliente.

Os tiers são cumulativos: T2 = T1 + o dele, T3 = T2 + o dele, T4 = T3 + o dele.
Fonte do que cada tier VENDE: prospeccao_dia.TIERS (oferta/abordagem já definidas lá).

ponytail: dados + função pura (recebe material, devolve diagnóstico). Sem I/O.
"""
from __future__ import annotations

import re

# O que o motor EXECUTA por tier (incremental sobre o anterior).
ESCOPO = {
    "T1": ["landing única", "IA monitorando por trás", "relatório periódico"],
    "T2": ["multi-página", "SEO técnico", "AEO", "GEO (SEO local)"],
    "T3": ["IA nativa no site", "Google Calendar (agenda)", "e-mail (notifica/relata)"],
    "T4": ["painel de operações do cliente"],
}

# Material MÍNIMO que sustenta cada escopo. `campo` é o que o form manda;
# `porque` é o que quebra sem ele — a mensagem que o JP lê.
REQUISITOS = {
    "T1": [
        ("nome", "sem o nome do negócio não há site"),
        ("nicho", "sem nicho a copy fica genérica e o SEO não ancora em nada"),
        ("contato", "landing sem WhatsApp/telefone não converte — é folheto"),
        ("diferenciais:1", "1 diferencial no mínimo, senão a landing não tem argumento"),
    ],
    "T2": [
        ("diferenciais:3", "multi-página precisa de conteúdo pra 3+ blocos reais; "
                           "com menos, as páginas extras nascem vazias"),
        ("cidade", "GEO/SEO local sem cidade não existe — é o que faz aparecer na busca da região"),
    ],
    "T3": [
        ("servicos", "a IA agenda O QUÊ? sem lista de serviços ela não tem o que oferecer"),
        ("email", "sem e-mail a IA não notifica nem manda o relatório — metade do T3 morre"),
    ],
    "T4": [
        ("midia:1", "o painel do cliente mostra o site dele; sem foto/vídeo real "
                    "o painel exibe material genérico e o cliente percebe"),
    ],
}
ORDEM = ("T1", "T2", "T3", "T4")


def _tem(material: dict, campo: str) -> bool:
    """Checa um requisito. `campo:N` = precisa de N itens na lista."""
    nome, _, minimo = campo.partition(":")
    v = material.get(nome)
    if minimo:
        n = len(v) if isinstance(v, (list, tuple)) else (
            len([x for x in str(v or "").splitlines() if x.strip()]))
        return n >= int(minimo)
    if nome == "contato":  # aceita whatsapp OU telefone
        return bool(str(material.get("whatsapp") or material.get("telefone") or "").strip())
    if nome == "email":
        return bool(re.match(r"[^@\s]+@[^@\s]+\.[^@\s]+", str(v or "").strip()))
    return bool(str(v or "").strip())


def escopo_de(tier: str) -> list[str]:
    """Tudo que o motor executa no tier (cumulativo)."""
    t = (tier or "T1").strip().upper()
    fora = []
    for x in ORDEM:
        fora += ESCOPO.get(x, [])
        if x == t:
            break
    return fora


def validar(tier: str, material: dict) -> dict:
    """Diagnóstico ANTES de gerar.

    {ok, tier, escopo, faltas[], tier_sustentado, mensagem}
    `tier_sustentado` = o maior tier que o material AGUENTA — assim o JP escolhe entre
    completar o material ou vender o tier que o material sustenta, em vez de descobrir
    depois que entregou menos do que vendeu."""
    t = (tier or "T1").strip().upper()
    if t not in ORDEM:
        t = "T1"
    faltas: list[dict] = []
    for x in ORDEM:
        for campo, porque in REQUISITOS.get(x, []):
            if not _tem(material, campo):
                faltas.append({"tier": x, "campo": campo.split(":")[0], "porque": porque})
        if x == t:
            break
    # até onde o material aguenta
    sustentado = ""
    for x in ORDEM:
        if all(_tem(material, c) for c, _ in REQUISITOS.get(x, [])):
            sustentado = x
            if x == t:
                break
        else:
            break
    ok = not faltas
    if ok:
        msg = f"{t} sustentado: {len(escopo_de(t))} entregas cobertas pelo material."
    elif sustentado:
        msg = (f"O material sustenta {sustentado}, não {t}. "
               f"Faltam {len(faltas)} item(ns) pro {t} — completar ou gerar como {sustentado}.")
    else:
        msg = f"Material insuficiente até pro T1: faltam {len(faltas)} item(ns)."
    return {"ok": ok, "tier": t, "escopo": escopo_de(t), "faltas": faltas,
            "tier_sustentado": sustentado, "mensagem": msg}


if __name__ == "__main__":  # self-check
    completo = {"nome": "Clínica X", "nicho": "odontologia", "whatsapp": "5514999999999",
                "diferenciais": ["a", "b", "c"], "cidade": "Bauru",
                "servicos": "limpeza\nimplante", "email": "contato@clinicax.com.br",
                "midia": ["foto1.jpg"]}
    r = validar("T4", completo)
    assert r["ok"] and r["tier_sustentado"] == "T4", r
    assert "painel de operações do cliente" in r["escopo"] and "landing única" in r["escopo"]
    assert len(r["escopo"]) == 11, r["escopo"]  # cumulativo: 3(T1)+4(T2)+3(T3)+1(T4)

    # T2 sem conteúdo pra multi-página: o caso que o JP citou
    magro = {"nome": "Clínica Y", "nicho": "odontologia", "whatsapp": "5514999999999",
             "diferenciais": ["só um"], "cidade": "Bauru"}
    r2 = validar("T2", magro)
    # sustenta T1 (tem nome/nicho/contato/1 diferencial) mas NÃO T2 (falta o 3º bloco)
    assert not r2["ok"] and r2["tier_sustentado"] == "T1", r2
    assert any(f["campo"] == "diferenciais" for f in r2["faltas"]), r2["faltas"]
    assert "sustenta" in r2["mensagem"].lower() or "insuficiente" in r2["mensagem"].lower()

    # material de T1 pedindo T3: diz até onde aguenta
    t1 = {"nome": "Bar Z", "nicho": "bar", "whatsapp": "5514999999999",
          "diferenciais": ["ao vivo"]}
    r3 = validar("T3", t1)
    assert r3["tier_sustentado"] == "T1" and not r3["ok"], r3
    assert any(f["tier"] == "T2" for f in r3["faltas"]), r3["faltas"]

    # T1 com o mínimo: passa
    assert validar("T1", t1)["ok"]
    # e-mail inválido não conta
    assert not _tem({"email": "não é email"}, "email")
    assert _tem({"email": "a@b.co"}, "email")
    print(f"tier_contrato OK — escopo cumulativo (T4={len(escopo_de('T4'))} entregas), "
          "falta detectada antes de gerar, tier_sustentado aponta o realista")
