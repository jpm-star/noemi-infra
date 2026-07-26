"""Extrator de ideia USÁVEL de qualquer conteúdo → alimenta os 3 motores.

Recebe texto (transcrição do radar, artigo, legenda) e devolve, POR MOTOR
(arbitragem / vídeo / site), UMA ação concreta que o motor pode executar — não
um resumo bonito. O prompt força: sem ação real → usavel=false com o porquê.

Reusa o Whisper/transcrição do radar (o texto já vem pronto); o novo aqui é a
extração acionável. Groq via llm_proxy (ECONOMIA: 1 chamada, JSON estrito).
Degrada honesto: LLM fora → status=erro, nunca inventa ideia.
"""
from __future__ import annotations

import json
import re

_MOTORES = ("arbitragem", "video", "site")

# o que cada motor CONSOME — descrito pro LLM saber o que é "acionável" pra cada um
_ALVO = {
    "arbitragem": "um PRODUTO específico pra arbitrar China→BR: nome do produto, "
                  "por que teria margem, e onde achar (marketplace/fornecedor). "
                  "Genérico ('vender eletrônicos') = NÃO usável.",
    "video": "um ÂNGULO concreto de roteiro de vídeo curto: o gancho (primeiros 3s) "
             "e o formato. 'Fazer vídeo sobre o tema' = NÃO usável.",
    "site": "uma SEÇÃO/feature de site-isca ou um SEGMENTO de nicho pra prospectar, "
            "com o motivo. 'Fazer um site bonito' = NÃO usável.",
}


def _prompt(texto: str, contexto: str) -> str:
    alvos = "\n".join(f"- {m}: {_ALVO[m]}" for m in _MOTORES)
    return (
        "Você extrai AÇÕES concretas de um conteúdo pra 3 motores de produto. "
        "NÃO resuma o conteúdo. Pra cada motor, extraia UMA ação executável agora, "
        "ou marque usavel=false se o conteúdo não oferece nada real pra aquele motor.\n"
        "Proibido ideia genérica. Seja específico como uma ordem de trabalho.\n\n"
        f"MOTORES:\n{alvos}\n\n"
        f"{'CONTEXTO: ' + contexto + chr(10) if contexto else ''}"
        f"CONTEÚDO:\n{texto[:6000]}\n\n"
        "Responda SOMENTE um JSON: {\"arbitragem\":{\"usavel\":bool,\"ideia\":\"...\","
        "\"porque\":\"...\"},\"video\":{...},\"site\":{...}}. "
        "`ideia` vazia quando usavel=false; `porque` sempre explica a decisão."
    )


def extrair_ideias(texto: str, *, origem: str = "", contexto: str = "", completar=None) -> dict:
    """{status, origem, motores:{arbitragem/video/site:{usavel,ideia,porque}}}.
    completar injetável (teste). Sem texto suficiente ou LLM fora → status!='ok'."""
    if not texto or len(texto.strip()) < 40:
        return {"status": "sem_conteudo", "origem": origem, "motores": {}}
    if completar is None:
        from shared_core.ai import llm_proxy
        completar = lambda p: llm_proxy.completar(p, model="analise", max_tokens=600, temperature=0.2)
    bruto = completar(_prompt(texto, contexto))
    if not bruto:
        return {"status": "llm_fora", "origem": origem, "motores": {}}
    m = re.search(r"\{.*\}", bruto, re.DOTALL)
    if not m:
        return {"status": "sem_json", "origem": origem, "motores": {}, "_bruto": bruto[:300]}
    try:
        dados = json.loads(m.group(0))
    except json.JSONDecodeError:
        return {"status": "json_invalido", "origem": origem, "motores": {}, "_bruto": bruto[:300]}
    # normaliza: garante os 3 motores, tipos previsíveis
    motores = {}
    for mot in _MOTORES:
        d = dados.get(mot) or {}
        motores[mot] = {"usavel": bool(d.get("usavel")),
                        "ideia": (d.get("ideia") or "").strip(),
                        "porque": (d.get("porque") or "").strip()}
    n_uteis = sum(1 for v in motores.values() if v["usavel"])
    return {"status": "ok", "origem": origem, "uteis": n_uteis, "motores": motores}


if __name__ == "__main__":  # self-check: normaliza saída do LLM (mock), honesto sem LLM
    def fake(_p):
        return ('lixo antes {"arbitragem":{"usavel":true,"ideia":"Anel de LED USB",'
                '"porque":"produto viral barato"},"video":{"usavel":false,"ideia":"",'
                '"porque":"sem gancho claro"},"site":{"usavel":true,"ideia":"nicho pet",'
                '"porque":"segmento citado"}} lixo depois')
    r = extrair_ideias("x" * 60, origem="teste", completar=fake)
    assert r["status"] == "ok" and r["uteis"] == 2, r
    assert r["motores"]["arbitragem"]["usavel"] and not r["motores"]["video"]["usavel"]
    assert extrair_ideias("curto", completar=fake)["status"] == "sem_conteudo"
    assert extrair_ideias("x" * 60, completar=lambda _p: None)["status"] == "llm_fora"
    print("extrator OK — 3 motores normalizados, honesto sem LLM/conteúdo")
