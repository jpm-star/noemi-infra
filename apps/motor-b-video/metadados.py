"""Metadados de publicação do vídeo (Motor B — Bloco C).

Título e hashtags derivados da classificação + dados do imóvel. Composição pura
(o raciocínio de LLM foi a classificação) — vira legenda/caption pronta pro post,
sem o corretor escrever nada.
"""
from __future__ import annotations

import re
import unicodedata
from urllib.parse import quote

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


# -- hashtags ---------------------------------------------------------------
_HT_TIPO = {"apartamento": ["#apartamento", "#apartamentoavenda"],
            "casa": ["#casa", "#casaavenda"],
            "condominio": ["#casaemcondominio", "#condominiofechado"]}
_HT_PADRAO = {
    "luxo": ["#imoveisdeluxo", "#altopadrao", "#luxo"],
    "lancamento": ["#lancamento", "#naplanta", "#imovelnovo"],
    "rural": ["#imovelrural", "#chacara", "#sitio"],
    "comercial": ["#salacomercial", "#pontocomercial", "#imovelcomercial"],
    "economico": ["#primeiroimovel", "#minhacasaminhavida", "#imovelacessivel"],
}
_HT_DESTAQUE = [(("vista mar", "vista pro mar", "frente mar", "beira mar"), "#vistamar"),
                (("piscina",), "#piscina"),
                (("mobiliado", "mobiliada"), "#mobiliado"),
                (("vista", "panorâmica", "panoramica"), "#vistapanoramica")]
_HT_BASE = ["#imoveis", "#imovelavenda", "#realestate", "#corretordeimoveis"]


def _slug_tag(texto: str) -> str:
    s = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode()
    s = re.sub(r"[^a-z0-9]+", "", s.lower())
    return f"#{s}" if s else ""


def hashtags(classificacao: dict, entrada: dict, minimo: int = 8, maximo: int = 10) -> list[str]:
    """8-10 hashtags relevantes por classificação/segmento. Dedup preservando
    ordem (mais específica primeiro), completa com base até o mínimo."""
    desc = (entrada.get("descricao") or "").lower()
    tags: list[str] = []
    tags += _HT_TIPO.get(classificacao.get("tipo"), [])
    tags += _HT_PADRAO.get(classificacao.get("padrao"), [])
    for chaves, tag in _HT_DESTAQUE:
        if any(k in desc for k in chaves):
            tags.append(tag)
    local = (entrada.get("localizacao") or "").strip()
    if local:
        t = _slug_tag(local)
        if t:
            tags.append(t)
    tags += _HT_BASE  # completa
    vistos, saida = set(), []
    for t in tags:
        if t and t not in vistos:
            vistos.add(t)
            saida.append(t)
        if len(saida) >= maximo:
            break
    return saida[:maximo] if len(saida) >= minimo else saida


# -- CTA WhatsApp (item 4) --------------------------------------------------
def _zap(brand: dict | None) -> str:
    return "".join(c for c in str((brand or {}).get("cta_contato") or "") if c.isdigit())


def cta_whatsapp(brand: dict | None, ficha: dict | None) -> str:
    """CTA de encerramento: link WhatsApp pré-preenchido citando o CÓDIGO do imóvel.
    Sem contato no kit → texto simples (sem link). Sem código → interesse genérico."""
    codigo = str((ficha or {}).get("codigo") or "").strip()
    ref = f"o imóvel cód {codigo}" if codigo else "este imóvel"
    zap = _zap(brand)
    if not zap:
        return f"📲 Chame no WhatsApp e pergunte sobre {ref}."
    msg = quote(f"Olá! Tenho interesse em {ref}.")
    return f"📲 Fale no WhatsApp: https://wa.me/{zap}?text={msg}"


def legenda_cta(brand: dict | None, ficha: dict | None) -> str:
    """Legenda CURTA queimada no vídeo (sem link — pixel não clica): CTA de marca
    + código do imóvel quando houver ('Fale no WhatsApp • cód AP-12')."""
    base = str((brand or {}).get("cta_texto") or "Fale no WhatsApp").strip()
    codigo = str((ficha or {}).get("codigo") or "").strip()
    return f"{base} • cód {codigo}" if codigo else base


def copy_publicacao(titulo_: str, hashtags_: list[str], cta: str) -> str:
    """Caption pronta pro post: título + CTA (WhatsApp/código) + hashtags. É o
    texto único que o corretor cola no feed, sem escrever nada."""
    linhas = [titulo_.strip(), "", cta.strip()]
    if hashtags_:
        linhas += ["", " ".join(hashtags_)]
    return "\n".join(linhas).strip()


if __name__ == "__main__":  # self-check
    assert cta_whatsapp({"cta_contato": "55 (19) 99888-7777"}, {"codigo": "AP-12"}) == \
        "📲 Fale no WhatsApp: https://wa.me/5519998887777?text=Ol%C3%A1%21%20Tenho%20interesse%20em%20o%20im%C3%B3vel%20c%C3%B3d%20AP-12."
    assert cta_whatsapp(None, None).startswith("📲 Chame no WhatsApp")  # sem zap → sem link
    assert legenda_cta({"cta_texto": "Agende visita"}, {"codigo": "AP-12"}) == "Agende visita • cód AP-12"
    assert legenda_cta(None, None) == "Fale no WhatsApp"
    t = titulo({"tipo": "apartamento", "padrao": "luxo"},
               {"descricao": "3 quartos com vista pro mar", "localizacao": "Balneário Camboriú"})
    assert t == "Apartamento 3 quartos - Balneário Camboriú - Vista Mar - Alto Padrão", t
    t2 = titulo({"tipo": "casa", "padrao": "economico"}, {"descricao": "casa simples"})
    assert t2 == "Casa", t2  # sem quartos/local/destaque/padrão → só o tipo
    h = hashtags({"tipo": "apartamento", "padrao": "luxo"},
                 {"descricao": "vista pro mar com piscina", "localizacao": "Balneário Camboriú"})
    assert 8 <= len(h) <= 10 and len(set(h)) == len(h), h
    assert "#apartamento" in h and "#imoveisdeluxo" in h and "#vistamar" in h
    print("metadados OK — título:", t, "| hashtags:", " ".join(h))
