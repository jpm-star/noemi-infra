"""Loader ÚNICO do cartucho (shared-core): 1 JSON de cliente → várias saídas.

Chamam: motor-b-video (brand.py / overlay de imóvel) e o gerador de site. Retorna
o cartucho cru + acessores normalizados (cidade, serviço, marca, ficha de imóvel).
Nunca lança — arquivo/campo ausente vira "" / {} / default. A leitura de arquivo,
o saneamento contra path traversal e o best-effort moram AQUI (antes copiados em
cada consumidor) — os cartuchos JSON são a fonte de dados única (NOEMI_CARTUCHOS_DIR).
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path

_NOME_SEGURO = re.compile(r"[^a-z0-9_-]")


def _base_dir(base: str | None) -> str | None:
    return base or os.environ.get("NOEMI_CARTUCHOS_DIR")


def carregar(nome: str, base: str | None = None) -> dict:
    """Cartucho <base>/<nome>.json como dict. Best-effort: dir/arquivo ausente ou
    JSON quebrado → {}. `nome` saneado contra path traversal. Aceita nome com ou
    sem .json."""
    base = _base_dir(base)
    nome = _NOME_SEGURO.sub("", (nome or "").lower().removesuffix(".json"))
    if not base or not nome:
        return {}
    caminho = Path(base) / f"{nome}.json"
    if not caminho.is_file():
        return {}
    try:
        return json.loads(caminho.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def cidade(cart: dict) -> str:
    """Cidade do cliente = 1ª região atendida (ou campo `cidade` explícito)."""
    if c := (cart.get("cidade") or "").strip():
        return c
    regioes = cart.get("regioes_atendidas") or []
    return str(regioes[0]).strip() if regioes else ""


def servico_principal(cart: dict) -> str:
    """Serviço-âncora pro CTA ("Quero orçamento de {isto}"). 1º item do escopo,
    senão o vertical. Escopo pode vir string ("a, b, c") ou lista."""
    esc = cart.get("escopo") or cart.get("servico_principal") or ""
    if isinstance(esc, list):
        esc = esc[0] if esc else ""
    primeiro = str(esc).split(",")[0].strip()
    return primeiro or str(cart.get("vertical") or "").strip()


def marca(cart: dict) -> dict:
    """Bloco de marca cru do cartucho, já com fallbacks de nome/whatsapp de topo.
    O mapeamento pros campos do kit de vídeo fica no consumidor (brand.py)."""
    m = dict(cart.get("marca") or {})
    m.setdefault("nome", cart.get("nome_empresa"))
    m.setdefault("whatsapp", cart.get("whatsapp_dono"))
    return m


def ficha_imovel(entrada: dict) -> dict:
    """Dados do imóvel (por-listing, vêm no job — não no cartucho do cliente)
    normalizados pro overlay de vídeo: só as chaves preenchidas.
    Aceita sinônimos comuns (valor→preco, endereco/bairro, area/metragem, quartos)."""
    fonte = entrada.get("imovel") if isinstance(entrada.get("imovel"), dict) else entrada
    mapa = {
        "preco": fonte.get("preco") or fonte.get("valor") or fonte.get("preço"),
        "bairro": fonte.get("bairro") or fonte.get("cidade"),
        "endereco": fonte.get("endereco") or fonte.get("endereço") or fonte.get("bairro"),
        "metragem": fonte.get("metragem") or fonte.get("area") or fonte.get("área"),
        "dormitorios": fonte.get("dormitorios") or fonte.get("quartos") or fonte.get("dormitórios"),
        "codigo": fonte.get("codigo") or fonte.get("código") or fonte.get("ref"),
    }
    return {k: str(v).strip() for k, v in mapa.items() if v not in (None, "", " ")}


if __name__ == "__main__":  # self-check
    assert carregar("../etc/passwd") == {}  # path traversal saneado → {}
    assert carregar("") == {}
    c = {"nome_empresa": "Marmoraria X", "vertical": "marmoraria",
         "escopo": "granito, quartzo", "regioes_atendidas": ["Campinas", "Valinhos"],
         "whatsapp_dono": "5519999", "marca": {"cor_acento": "#0E7C86"}}
    assert cidade(c) == "Campinas", cidade(c)
    assert servico_principal(c) == "granito", servico_principal(c)
    assert marca(c)["nome"] == "Marmoraria X" and marca(c)["whatsapp"] == "5519999"
    f = ficha_imovel({"valor": "R$ 850 mil", "quartos": 3, "area": "72m²", "ref": "AP-12"})
    assert f == {"preco": "R$ 850 mil", "dormitorios": "3", "metragem": "72m²", "codigo": "AP-12"}, f
    print("cartucho OK — cidade/serviço/marca/ficha")
