"""Camada de Análise — "os olhos da operação" (contrato mínimo).

Recebe o formulário de intake e devolve recomendação estruturada: quais
produtos se aplicam, config inicial, prioridade e confiança.

ponytail: hardcoded retornando Motor B — o Decision Engine real (Groq, prompt
do Analista na SPEC §2) entra quando houver formulário de cliente de verdade.
O CONTRATO (chaves do retorno) já é o final; quem consumir hoje não muda depois.
"""
from __future__ import annotations


def analisar_cliente(form: dict) -> dict:
    faltando = [c for c in ("segmento", "objetivo") if not form.get(c)]
    return {
        "produtos": [
            {"produto": "motor-b-video", "config": {}, "prioridade": 1},
        ],
        "confianca": "baixa",
        "motivo": "contrato mínimo: análise LLM ainda não ligada; todo intake roteia pro Motor B",
        "faltando": faltando,
    }


if __name__ == "__main__":  # self-check
    r = analisar_cliente({"segmento": "imobiliária", "objetivo": "vender mais"})
    assert r["produtos"][0]["produto"] == "motor-b-video" and not r["faltando"]
    assert analisar_cliente({})["faltando"] == ["segmento", "objetivo"]
    print("analista OK:", r)
