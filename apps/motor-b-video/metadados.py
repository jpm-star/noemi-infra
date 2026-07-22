"""Metadados de publicação do vídeo (Motor B — Bloco C).

Título e hashtags derivados da classificação + dados do imóvel. Composição pura
(o raciocínio de LLM foi a classificação) — vira legenda/caption pronta pro post,
sem o corretor escrever nada.
"""
from __future__ import annotations

import re
import unicodedata

_TIPO_LABEL = {"apartamento": "Apartamento", "casa": "Casa", "condominio": "Casa em condomínio"}
_PADRAO_LABEL = {"luxo": "Alto Padrão", "lancamento": "Lançamento",
                 "rural": "Rural", "comercial": "Comercial", "economico": ""}
# destaques comuns detectáveis no texto → rótulo curto pro título
_DESTAQUES = [
    (("vista mar", "vista pro mar", "frente mar", "beira mar"), "Vista Mar"),
    (("vista", "panorâmica", "panoramica"), "Vista Panorâmica"),
    (("piscina",), "Piscina"),
    (("mobiliado", "mobiliada"), "Mobiliado"),
    (("reformado", "reformada", "novo", "nova"), "Novo"),
    (("condomínio fechado", "condominio fechado"), "Condomínio Fechado"),
]


def _quartos(entrada: dict, desc: str) -> str:
    q = entrada.get("quartos")
    if q:
        return f"{q} quartos"
    m = re.search(r"(\d+)\s*(?:quartos?|dorm|suítes?|suites?)", desc)
    return f"{m.group(1)} quartos" if m else ""


def _destaque(desc: str) -> str:
    for chaves, rotulo in _DESTAQUES:
        if any(k in desc for k in chaves):
            return rotulo
    return ""


def titulo(classificacao: dict, entrada: dict) -> str:
    """Título tipo 'Apartamento 3 quartos - Vista Mar - Alto Padrão'. Junta só as
    partes que existem (nunca inventa dado que não veio)."""
    desc = (entrada.get("descricao") or "").lower()
    tipo = _TIPO_LABEL.get(classificacao.get("tipo"), "Imóvel")
    quartos = _quartos(entrada, desc)
    cabeca = f"{tipo} {quartos}".strip()
    partes = [cabeca]
    local = (entrada.get("localizacao") or "").strip()
    if local:
        partes.append(local)
    dest = _destaque(desc)
    if dest and dest.lower() not in cabeca.lower():
        partes.append(dest)
    padrao = _PADRAO_LABEL.get(classificacao.get("padrao"), "")
    if padrao:
        partes.append(padrao)
    return " - ".join(p for p in partes if p)


if __name__ == "__main__":  # self-check
    t = titulo({"tipo": "apartamento", "padrao": "luxo"},
               {"descricao": "3 quartos com vista pro mar", "localizacao": "Balneário Camboriú"})
    assert t == "Apartamento 3 quartos - Balneário Camboriú - Vista Mar - Alto Padrão", t
    t2 = titulo({"tipo": "casa", "padrao": "economico"}, {"descricao": "casa simples"})
    assert t2 == "Casa", t2  # sem quartos/local/destaque/padrão → só o tipo
    print("metadados.titulo OK —", t)
