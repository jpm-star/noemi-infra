#!/usr/bin/env python3
"""Ingestão AUTOMÁTICA de referências de estrutura — o gargalo do motor.

Por que o motor gerava sempre a mesma coisa: `templates_referencia` tinha ZERO linhas.
A biblioteca existia, o pool de receitas sabia consumi-la, e ninguém nunca a alimentou
porque o único caminho era o JP colar print a print.

A DECISÃO QUE MUDA A QUALIDADE AQUI: pra uma URL, a estrutura está no HTML — não
precisa de visão. Ler o DOM dá a ordem real das seções, determinística, de graça e sem
gastar cota de LLM. Visão sobre screenshot é o caminho CARO e impreciso; fica só pro
print manual, onde não há HTML.

O que sai não é decorativo: é uma `ordem` no vocabulário de `receitas.BLOCOS`, que é
exatamente o que `receitas.pool()` consome pra montar site. Referência que não vira
ordem utilizável é enfeite — por isso `de_url` descarta o que não mapeia em nada.

Uso:
    python referencias_scrap.py --url https://exemplo.com --segmento clinica
    python referencias_scrap.py --galeria onepagelove --segmento clinica --limite 12
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

_AQUI = Path(__file__).resolve().parent
sys.path.insert(0, str(_AQUI))
sys.path.insert(0, str(_AQUI.parents[1] / "packages"))

# Sinais de cada bloco do NOSSO vocabulário dentro de um HTML alheio. Ordem de teste
# importa: o primeiro que casar ganha a seção, então o mais específico vem antes.
# São heurísticas de forma (tag/classe/id/texto), não de marca — a ideia é aprender
# ESTRUTURA, nunca copiar conteúdo.
_SINAIS: tuple[tuple[str, str], ...] = (
    ("antesdepois", r"antes[-_ ]?e?[-_ ]?depois|before[-_ ]?after|transforma|resultado"),
    ("depoimentos", r"depoiment|testimonial|review|avalia[çc][ãa]|o que dizem|clientes? dizem"),
    ("faq", r"\bfaq\b|perguntas frequentes|d[úu]vidas|frequently asked"),
    ("preco", r"pre[çc]o|pricing|planos?\b|investimento|tabela de valores|assinatura"),
    ("calculadora", r"calculadora|simulador|calculate|estimate|or[çc]amento online"),
    ("formulario", r"<form|contato|contact|fale conosco|agendar|solicite|get in touch"),
    ("catalogo_motion", r"galeria|gallery|portfolio|portf[óo]lio|nossos trabalhos|cases?\b"),
    ("catalogo", r"servi[çc]os|services|produtos|products|o que fazemos|especialidades"),
    ("sobre", r"sobre|about|quem somos|nossa hist[óo]ria|our story|who we are"),
)

GALERIAS = {
    "onepagelove": "https://onepagelove.com/inspiration",
    "lapaninja": "https://www.lapa.ninja/",
    "landbook": "https://land-book.com/",
}


def _blocos_do_html(html: str) -> list[str]:
    """Ordem das seções do HTML no vocabulário de `receitas.BLOCOS`.

    Ordena pela POSIÇÃO da 1ª ocorrência de cada sinal no corpo. A 1ª tentativa fatiava
    por `<section>` e casava um bloco por fatia — morreu no mundo real: site moderno não
    usa seção semântica, a página inteira virava uma fatia só e rendia 1 bloco (medido:
    1 de 3 clínicas reais passava). Posição funciona com qualquer marcação, porque a
    ordem visual do documento é a ordem do argumento — que é o que queremos aprender."""
    import receitas
    corpo = html[html.lower().find("<body"):] if "<body" in html.lower() else html
    # fora script/style/svg (JS e ícone têm palavra que casa sinal e mente na posição)
    corpo = re.sub(r"<(script|style|svg|noscript)\b.*?</\1>", " ", corpo, flags=re.S | re.I)
    # o <head> e menus repetem os termos; o menu fica no topo e distorceria tudo.
    # Cortar o 1º <nav>/<header> resolve sem precisar entender o site.
    corpo = re.sub(r"<(nav|header)\b.*?</\1>", " ", corpo, count=2, flags=re.S | re.I)

    posicoes: dict[str, int] = {}
    for bloco, rx in _SINAIS:
        if bloco not in receitas.BLOCOS:
            continue
        m = re.search(rx, corpo, re.I)
        if m:
            posicoes[bloco] = m.start()
    return [b for b, _ in sorted(posicoes.items(), key=lambda kv: kv[1])]


def de_url(url: str, segmento: str, tag: str = "", aprovada: bool = False) -> dict:
    """Uma URL → uma referência de ESTRUTURA gravada. {ok, ordem, motivo}.

    Descarta o que rende menos de 3 blocos: referência de 1-2 seções não ensina ordem
    de argumento nenhuma e só sujaria o pool com ruído."""
    import ingestao
    import receitas
    url = (url or "").strip()
    if not url.startswith("http"):
        url = "https://" + url.lstrip("/")
    try:
        html = ingestao._buscar(url)      # MESMO fetch da ingestão (UA, gzip, timeout)
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "url": url, "motivo": f"não baixou: {type(e).__name__}"}
    ordem = _blocos_do_html(html or "")
    if len(ordem) < 3:
        return {"ok": False, "url": url, "ordem": ordem,
                "motivo": f"só {len(ordem)} bloco(s) — pouco pra ensinar ordem"}
    hero = "video" if "<video" in (html or "").lower() else ""
    receita = {"ordem": ordem, "hero": hero,
               "porque": f"estrutura observada em {re.sub(r'^https?://', '', url)[:60]}"}
    receitas.referencia_salvar(
        tag=tag or re.sub(r"^https?://(www\.)?", "", url)[:60],
        segmento=segmento, imagem=url, receita=receita,
        tipo="estrutura", aprovada=aprovada)
    return {"ok": True, "url": url, "ordem": ordem, "hero": hero}


def _links_da_galeria(html: str, base: str) -> list[str]:
    """URLs de sites REAIS linkados na galeria. Ignora link interno da própria galeria
    (é a diferença entre aprender com 12 sites e aprender com 12 páginas do mesmo site)."""
    host = re.sub(r"^https?://(www\.)?", "", base).split("/")[0]
    achados: list[str] = []
    for m in re.finditer(r'href=["\'](https?://[^"\'?#]+)', html, re.I):
        u = m.group(1)
        h = re.sub(r"^https?://(www\.)?", "", u).split("/")[0]
        if host in h or any(x in h for x in ("twitter", "facebook", "instagram", "github",
                                             "linkedin", "youtube", "pinterest", "t.co")):
            continue
        raiz = f"https://{h}"
        if raiz not in achados:
            achados.append(raiz)
    return achados


def de_galeria(galeria: str, segmento: str, limite: int = 12,
               aprovada: bool = False) -> dict:
    """Galeria aberta → N referências, sem o JP colar print nenhum.

    Só galerias públicas e sem paywall (as que o JP indicou). Pega ESTRUTURA: nada de
    texto, marca ou imagem do site alheio entra no nosso banco."""
    import ingestao
    base = GALERIAS.get(galeria, galeria)
    try:
        html = ingestao._buscar(base)
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "galeria": base, "erro": f"{type(e).__name__}"}
    urls = _links_da_galeria(html or "", base)[:max(1, limite)]
    fora = [de_url(u, segmento, aprovada=aprovada) for u in urls]
    bons = [r for r in fora if r.get("ok")]
    return {"ok": True, "galeria": base, "tentadas": len(fora), "salvas": len(bons),
            "referencias": bons,
            "descartadas": [{"url": r["url"], "motivo": r["motivo"]}
                            for r in fora if not r.get("ok")][:8]}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url")
    ap.add_argument("--galeria", choices=[*GALERIAS, "todas"])
    ap.add_argument("--segmento", required=True)
    ap.add_argument("--limite", type=int, default=12)
    ap.add_argument("--aprovar", action="store_true", help="entra no pool já aprovada")
    a = ap.parse_args()
    if a.url:
        print(de_url(a.url, a.segmento, aprovada=a.aprovar))
        return
    alvos = list(GALERIAS) if a.galeria == "todas" else [a.galeria or "onepagelove"]
    for g in alvos:
        r = de_galeria(g, a.segmento, a.limite, aprovada=a.aprovar)
        print(f"{g}: {r.get('salvas', 0)}/{r.get('tentadas', 0)} salvas")
        for d in r.get("descartadas", [])[:3]:
            print("   descartada:", d["url"][:50], "—", d["motivo"])


if __name__ == "__main__":
    main()
