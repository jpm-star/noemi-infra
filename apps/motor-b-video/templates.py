"""Biblioteca de templates de vídeo (Motor B v1.1) — 4 presets essenciais.

Cada template é um PRESET de parâmetros pro prompt builder (não um sistema novo).
A classificação escolhe o template automaticamente; troca manual via config.template.

Escopo desta sessão (o resto da proposta é V2): alto_padrao, economico,
lancamento, comercial.
"""
from __future__ import annotations

TEMPLATES: dict[str, dict] = {
    "alto_padrao": {
        "rotulo": "Imóvel de padrão alto",
        "camera": "movimentos lentos e fluidos — dolly e crane suaves, revelações amplas",
        "ritmo": "lento e contemplativo",
        "iluminacao": "golden hour, luz natural quente e sombras longas",
        "estilo": "cinematográfico, cor rica, profundidade de campo",
        "transicoes": "cross-dissolve suave",
        "aspect_ratio": "16:9",
        "duracao": 12,
        "cta": False,
    },
    "economico": {
        "rotulo": "Imóvel econômico/popular",
        "camera": "movimentos dinâmicos e cortes rápidos, POV de quem caminha pela casa",
        "ritmo": "energético",
        "iluminacao": "clara e diurna, ambiente acolhedor",
        "estilo": "vibrante e familiar, sensação de lar",
        "transicoes": "cortes secos no ritmo",
        "aspect_ratio": "9:16",
        "duracao": 8,
        "cta": True,
    },
    "lancamento": {
        "rotulo": "Lançamento",
        "camera": "reveals dramáticos, push-in e aéreos",
        "ritmo": "crescente, montagem estilo trailer",
        "iluminacao": "contrastada e dramática",
        "estilo": "trailer com texto animado e contagem regressiva",
        "transicoes": "flash/glitch marcando as batidas",
        "aspect_ratio": "9:16",
        "duracao": 15,
        "cta": True,
    },
    "comercial": {
        "rotulo": "Comercial/corporativo",
        "camera": "planos estáticos e travellings precisos",
        "ritmo": "moderado e controlado",
        "iluminacao": "neutra e uniforme, corporativa",
        "estilo": "minimalista, foco em branding e espaço",
        "transicoes": "wipe limpo",
        "aspect_ratio": "16:9",
        "duracao": 10,
        "cta": False,
    },
}

# padrão do imóvel (classificação) → template automático
_POR_PADRAO = {
    "luxo": "alto_padrao",
    "rural": "alto_padrao",   # paisagem/golden hour cabe bem no rural
    "economico": "economico",
    "lancamento": "lancamento",
    "comercial": "comercial",
}


def escolher_template(classificacao: dict, manual: str | None = None) -> dict:
    """Template escolhido pela classificação, com troca manual (config.template)."""
    tid = manual if manual in TEMPLATES else _POR_PADRAO.get(classificacao.get("padrao"), "economico")
    return {"id": tid, **TEMPLATES[tid]}
