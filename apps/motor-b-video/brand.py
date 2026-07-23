"""Brand Kit do Motor B — marca do cliente aplicada automaticamente (Onda 1).

Devolve o kit de marca de um job SEM intervenção manual: nome, cor de acento,
logo, tipografia, CTA de encerramento e watermark. O worker chama `brand_kit()`
e o resultado alimenta duas pontas — o prompt (cor/CTA viram texto pro Higgsfield)
e o pós-processamento (watermark/overlay via FFmpeg).

Fonte (config vence cartucho vence default):
  1. config["marca"] — dict do chamador (painel/API), schema do bloco `marca`.
  2. cartucho <nome>.json — bloco `marca` do SDR Motor (nome_exibicao/cor_acento/
     logo_url) + whatsapp_dono; nome vem de config["cartucho"], dir de
     NOEMI_CARTUCHOS_DIR.
  3. default neutro Noemi.

ponytail: NÃO importa nada do repo sdr-motor — só lê o JSON por caminho (env).
Env ausente ou arquivo faltando = cai no default, ninguém quebra. Função pura.
"""
from __future__ import annotations

import re

from shared_core import cartucho

# default honesto: marca Noemi neutra, sem inventar logo/cor de cliente
_DEFAULT = {
    "nome": "Noemi",
    "cor_acento": "#7c5cff",
    "logo_url": None,
    "fonte_titulo": "Manrope",  # tipografia default (cartucho não carrega fonte)
    "cta_texto": "Fale no WhatsApp",
    "cta_contato": None,
    "fonte": "default",
}

_HEX = re.compile(r"^#?[0-9a-fA-F]{6}$")


def _norm_cor(v) -> str | None:
    if isinstance(v, str) and _HEX.match(v.strip()):
        c = v.strip()
        return c if c.startswith("#") else f"#{c}"
    return None


def _mapear(marca: dict) -> dict:
    """Bloco `marca` (schema do cartucho) → campos do kit, só os que vieram."""
    bruto = {
        "nome": marca.get("nome_exibicao") or marca.get("nome"),
        "cor_acento": _norm_cor(marca.get("cor_acento")),
        "logo_url": marca.get("logo_url"),
        "fonte_titulo": marca.get("fonte_titulo"),
        "cta_texto": marca.get("cta") or marca.get("cta_texto"),
        "cta_contato": marca.get("whatsapp") or marca.get("cta_contato"),
    }
    return {k: v for k, v in bruto.items() if v}  # descarta None/"" — não sobrescreve


def _de_cartucho(nome: str) -> dict:
    """Marca do cartucho <nome>.json, via loader único do shared-core (leitura,
    path-safety e best-effort moram lá). Só mapeia o bloco pros campos do kit."""
    cart = cartucho.carregar(nome)
    return _mapear(cartucho.marca(cart)) if cart else {}


def brand_kit(owner: str | None, config: dict | None = None) -> dict:
    """Kit de marca resolvido pro job. Nunca lança — sempre devolve dict completo
    (campos faltando caem no default). `config` pode trazer `marca` (dict) e/ou
    `cartucho` (nome do arquivo). config > cartucho > default."""
    config = config or {}
    kit = dict(_DEFAULT)

    origem = "default"
    # ordem: cartucho por baixo, config por cima (config vence)
    if config.get("cartucho"):
        camada = _de_cartucho(str(config["cartucho"]))
        if camada:
            kit.update(camada)
            origem = "cartucho"
    if isinstance(config.get("marca"), dict):
        camada = _mapear(config["marca"])
        if camada:
            kit.update(camada)
            origem = "config"

    kit["cor_acento"] = _norm_cor(kit.get("cor_acento")) or _DEFAULT["cor_acento"]
    kit["fonte"] = origem
    kit["watermark"] = kit.get("logo_url") or kit["nome"]  # logo se houver, senão nome
    return kit


if __name__ == "__main__":  # self-check
    d = brand_kit("x", None)
    assert d["nome"] == "Noemi" and d["fonte"] == "default" and d["watermark"] == "Noemi"
    m = brand_kit("x", {"marca": {"nome_exibicao": "Ateliê Pedra", "cor_acento": "0E7C86"}})
    assert m["nome"] == "Ateliê Pedra" and m["cor_acento"] == "#0E7C86" and m["fonte"] == "config"
    assert m["watermark"] == "Ateliê Pedra"
    bad = brand_kit("x", {"marca": {"cor_acento": "roxo"}})  # cor inválida → default
    assert bad["cor_acento"] == "#7c5cff" and bad["fonte"] == "default"
    print("brand OK —", d["nome"], "|", m["nome"], m["cor_acento"], "|", bad["cor_acento"])
