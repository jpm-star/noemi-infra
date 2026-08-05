#!/usr/bin/env python3
"""STUDIO #2 — galeria com preview: o que foi entregue, visto como o cliente vê.

A lista de hoje é uma TABELA: slug, kb, um pontinho verde. Diz que o site existe,
não diz o que ele É. Pra vender studio (e pra o JP conferir antes de mandar o link),
o que importa é a CARA da entrega.

Duas decisões que definem este módulo:

1. O preview é `<iframe>` na mesma origem, escalado por CSS — não screenshot.
   Sem headless browser, sem storage de thumbnail, sem invalidação: o preview é o
   site, então nunca fica velho. Custo: o navegador carrega as páginas (mitigado com
   `loading="lazy"`, só renderiza o que entra na tela).

2. O que o backend acrescenta é o que o olho NÃO pega num preview de 4cm:
   quais SEÇÕES o site tem. Isso é a prova estrutural — dois sites do mesmo segmento
   com a mesma lista de seções significa que a receita não variou (o bug que a gente
   matou). A galeria expõe isso em vez de esconder.

Não substitui `criacao.listar_sites()` — CHAMA. Criação de site atual fica intacta.
"""
from __future__ import annotations

import re
import sys
from collections import Counter
from pathlib import Path

_AQUI = Path(__file__).resolve().parent
sys.path.insert(0, str(_AQUI))

# Assinatura de cada seção no HTML gerado. Casa com o que template_real.py monta:
# a chave é o nome da seção na receita, o valor é o que prova que ela saiu no HTML.
_SECOES = {
    "sobre": r'class="[^"]*sec-titulo|<main\b',
    "catálogo": r'class="[^"]*catalogo|data-sec="catalogo"',
    "motion": r"@keyframes|animation:",
    "antes/depois": r"antes.{0,20}depois|class=\"[^\"]*antesdepois",
    "preço": r'class="[^"]*(preco|ancora-preco)|R\$\s?\d',
    "calculadora": r'class="[^"]*calculadora|<input[^>]+type="range"',
    "depoimentos": r'class="[^"]*depoimento|<blockquote',
    "faq": r'class="[^"]*faq|<details',
    "formulário": r"<form\b",
    "vídeo": r"<video\b",
    "galeria": r"jpos-grid",
    "mapa": r"<iframe[^>]+maps",
}


def _texto(tag: str, html: str) -> str:
    m = re.search(rf"<{tag}[^>]*>(.*?)</{tag}>", html, re.S | re.I)
    if not m:
        return ""
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", m.group(1))).strip()[:120]


def ler(idx: Path) -> dict:
    """Lê o HTML entregue e responde: como se chama, o que promete, do que é feito.

    Só regex — o HTML é gerado pela nossa própria máquina, então o formato é conhecido.
    Parser completo aqui seria dependência nova pra ler o que a gente mesmo escreveu."""
    try:
        html = idx.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return {"titulo": "", "chamada": "", "secoes": [], "cores": []}
    secoes = [nome for nome, rx in _SECOES.items() if re.search(rx, html, re.I)]
    # cores dominantes: dá pra ver na grade se o motor está variando a paleta ou
    # repetindo o mesmo verde em todo cliente.
    cores = [c for c, _ in Counter(
        m.group(0).lower() for m in re.finditer(r"#[0-9a-fA-F]{6}\b", html)).most_common(4)]
    return {"titulo": _texto("title", html), "chamada": _texto("h1", html),
            "secoes": secoes, "cores": cores}


def listar() -> dict:
    """Galeria: cada site com preview + o que o preview não mostra.

    `assinatura` = as seções concatenadas. Dois sites com a MESMA assinatura saíram
    da mesma receita — é o número que o JP olha pra saber se o motor está variando
    de verdade ou só trocando o texto por cima do mesmo esqueleto."""
    import criacao
    sites = criacao.listar_sites()
    fora = []
    for s in sites:
        idx = criacao.SITES_DIR / s["slug"] / "index.html"
        d = ler(idx) if idx.exists() else {"titulo": "", "chamada": "", "secoes": [], "cores": []}
        fora.append({**s, **d, "assinatura": "|".join(d["secoes"])})
    assinaturas = Counter(x["assinatura"] for x in fora if x["assinatura"])
    for x in fora:
        # quantos OUTROS sites têm exatamente a mesma estrutura
        x["iguais"] = max(0, assinaturas.get(x["assinatura"], 0) - 1)
    distintas = len(assinaturas)
    return {"sites": fora, "total": len(fora), "estruturas_distintas": distintas,
            "repetidos": sum(1 for x in fora if x["iguais"] > 0),
            "diversidade": round(100 * distintas / max(1, sum(assinaturas.values())))}


if __name__ == "__main__":  # self-check offline
    import os
    import tempfile
    d = Path(tempfile.mkdtemp(suffix="_gal"))
    os.environ["SITE_OUT_DIR"] = str(d)
    os.environ["NOEMI_DATA_DIR"] = tempfile.mkdtemp(suffix="_galdata")
    import criacao
    criacao.SITES_DIR = d

    corpo = "conteúdo real " * 400
    (d / "a").mkdir(); (d / "a" / "index.html").write_text(
        f"<html><head><title>Clínica A</title></head><body><h1>Sorria mais</h1>"
        f"<main class='sec-titulo'>{corpo}</main><form></form>"
        f"<style>@keyframes x{{}}--c:#0f2f24;#059669;#059669</style></body></html>",
        encoding="utf-8")
    (d / "b").mkdir(); (d / "b" / "index.html").write_text(  # MESMA estrutura de 'a'
        f"<html><head><title>Clínica B</title></head><body><h1>Outro texto</h1>"
        f"<main class='sec-titulo'>{corpo}</main><form></form>"
        f"<style>@keyframes x{{}}</style></body></html>", encoding="utf-8")
    (d / "c").mkdir(); (d / "c" / "index.html").write_text(  # estrutura DIFERENTE
        f"<html><head><title>Bar C</title></head><body><h1>Chopp gelado</h1>"
        f"<main class='sec-titulo'>{corpo}</main><details>faq</details>"
        f"<blockquote>bom</blockquote><video></video></body></html>", encoding="utf-8")

    a = ler(d / "a" / "index.html")
    assert a["titulo"] == "Clínica A" and a["chamada"] == "Sorria mais", a
    assert "formulário" in a["secoes"] and "motion" in a["secoes"], a["secoes"]
    assert "#059669" in a["cores"], a["cores"]

    r = listar()
    por = {x["slug"]: x for x in r["sites"]}
    # a e b saíram da MESMA receita: cada um aponta 1 igual. c é único.
    assert por["a"]["assinatura"] == por["b"]["assinatura"], (por["a"], por["b"])
    assert por["a"]["iguais"] == 1 and por["b"]["iguais"] == 1, r
    assert por["c"]["iguais"] == 0 and "faq" in por["c"]["secoes"], por["c"]
    assert r["estruturas_distintas"] == 2 and r["repetidos"] == 2, r
    assert r["diversidade"] == 67, r["diversidade"]  # 2 estruturas / 3 sites
    # arquivo ausente não derruba a galeria
    assert ler(d / "nao-existe" / "index.html")["secoes"] == []
    print(f"galeria OK — {r['total']} sites, {r['estruturas_distintas']} estruturas "
          f"distintas, {r['repetidos']} repetindo esqueleto (diversidade {r['diversidade']}%)")
