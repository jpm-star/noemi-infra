"""Renderiza o jpos.com.br com dado real e publica em /var/www/jpos.

Por que renderizar no servidor em vez de `fetch` no navegador: os números SÃO o
argumento de venda. Se viessem por JS, o Google, o ChatGPT e o visitante de conexão
ruim veriam uma página sem prova nenhuma. Aqui o HTML já sai com tudo dentro, e o
único JS que roda é o compositor — que é interação, não conteúdo.

Rodar:  python publicar.py            # gera e mostra o diagnóstico, NÃO publica
        python publicar.py --publicar # grava em /var/www/jpos (com backup)
"""
from __future__ import annotations

import html
import re
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

AQUI = Path(__file__).resolve().parent
sys.path.insert(0, str(AQUI))

import dados  # noqa: E402

DESTINO = Path("/var/www/jpos")
ZAP = "https://wa.me/5514998745847?text="


def _e(s) -> str:
    return html.escape(str(s), quote=True)


def _numeros_li(n: dict) -> str:
    itens = [
        (n["sites_no_ar"], "sites no ar"),
        (n.get("nichos_entregues"), "nichos entregues"),
        (n.get("cidades"), "cidades"),
        (f"{n['mediana_s']}s".replace(".", ","), "mediana de geração"),
        (n["nichos_catalogados"], "nichos catalogados"),
        (n["blocos"], "blocos de página"),
    ]
    # campo None = fonte vazia; some da faixa em vez de virar "0 cidades"
    return "".join(f"<li><b>{_e(v)}</b>{_e(r)}</li>" for v, r in itens if v)


def _vitrine_cards(itens: list[dict]) -> str:
    out = []
    for it in itens:
        thumb = f"/vitrine/{it['slug']}.jpg"
        existe = (DESTINO / "vitrine" / f"{it['slug']}.jpg").exists()
        img = (f'<img src="{_e(thumb)}" alt="Home do site de {_e(it["nome"])}" '
               f'loading="lazy" decoding="async" width="1200" height="700">') if existe else ""
        # "cliente" seria prova social INVENTADA: não há venda registrada no CRM, e
        # site no ar não prova contrato. "no ar" é o que dá pra verificar clicando.
        selo = ('<span class="selo">demo</span>' if it.get("demo")
                else '<span class="selo selo--ok">no ar</span>')
        out.append(
            f'<a class="cartao" href="{_e(it["url"])}" target="_blank" rel="noopener">{img}'
            f'<div class="cartao-corpo"><h3>{_e(it["nome"])}</h3>'
            f'<div class="meta">{_e(it["nicho"])} · {_e(it["cidade"])} {selo}</div>'
            f'<div class="ir">abrir o site →</div></div></a>')
    return "".join(out)


def _brl(v: int | float) -> str:
    """1000 -> "1.000". Preço sem separador de milhar lê como preço estrangeiro."""
    return f"{int(v):,}".replace(",", ".")


def _precos_cards(p: dict) -> str:
    out = []
    for i, t in enumerate(p["tiers"]):
        msg = f"Olá! Quero saber do plano {t['nome']} ({t['id']}) da JPOS."
        mensal = (f'<p class="mensal">+ {p["moeda"]} {_brl(t["mensal"])}/mês</p>'
                  if t.get("mensal") else '<p class="mensal">sem mensalidade</p>')
        itens = "".join(f"<li>{_e(x)}</li>" for x in t["entrega"])
        # "a partir de" vem ANTES do número: depois dele, o olho já ancorou no valor
        # cheio e a faixa vira ressalva em vez de convite.
        de = '<p class="desde">a partir de</p>' if i == 0 else ""
        out.append(
            f'<article class="plano plano--{1 if i == 0 else 0}">'
            f'<p class="rotulo">{_e(t["id"])}</p><h3>{_e(t["nome"])}</h3>{de}'
            f'<p class="valor">{_e(p["moeda"])} {_brl(t["setup"])}</p>{mensal}'
            f'<ul>{itens}</ul>'
            f'<a class="btn-brasa" href="{ZAP}{_e(_url(msg))}" rel="noopener">'
            f'Falar sobre o {_e(t["nome"])}</a>'
            f'</article>')
    return "".join(out)


def _url(s: str) -> str:
    from urllib.parse import quote
    return quote(s)


def _faq(n: dict, cidades: list[str]) -> str:
    """Perguntas respondidas com fato verificável. As comerciais (garantia, posse do
    domínio, prazo de contrato) NÃO entram aqui: não estão no código, e inventar
    política comercial num site é como o cliente descobre que você inventa."""
    qs = [
        ("Quanto tempo leva pra ficar pronto?",
         f"A geração em si tem mediana de {n['mediana_s']}s — do briefing ao site no ar, medido em "
         f"{n['geracoes_medidas']} gerações reais. O que leva tempo é o briefing e os seus ajustes, "
         f"não a montagem."),
        ("Isso é template?",
         f"O esqueleto se repete; a decisão não. São {n['familias']} famílias de estilo, "
         f"{n['blocos']} blocos de página e {n['nichos_catalogados']} nichos catalogados, e cada "
         f"escolha carrega o motivo escrito. Teste no campo do topo: troque o nicho e a ficha muda."),
        ("Onde vocês atendem?",
         "Há sites no ar em " + ", ".join(cidades[:-1]) + " e " + cidades[-1] + "."
         if len(cidades) > 1 else "Interior de São Paulo."),
        ("E se o meu ramo não estiver no catálogo?",
         "Ele monta assim mesmo: nicho fora do catálogo cai na família de serviços e fica contado — "
         "é assim que o catálogo cresce. Nicho novo nunca trava uma geração."),
        ("Como sei que não vai subir com erro?",
         "Duas travas automáticas antes de virar material de venda: telefone de exemplo no WhatsApp "
         "reprova a geração inteira, e um gate visual olha a página renderizada e barra defeito de "
         "layout. Um site que manda o lead pra número morto é pior que site nenhum."),
    ]
    return "".join(f"<details><summary>{_e(q)}</summary><p>{_e(a)}</p></details>" for q, a in qs)


def render() -> tuple[str, dict]:
    import json

    d = dados.tudo()
    n, p = d["numeros"], d["precos"]
    fichas = dados._fichas()
    cidades = sorted({f["cidade"] for f in fichas})
    imob = d["motor"]["familias"].get("imobiliaria") or {}
    citacao = imob.get("porque") or next(iter(d["motor"]["familias"].values()))["porque"]

    troca = {
        "__SITES_NO_AR__": str(n["sites_no_ar"]),
        "__MEDIANA__": str(n["mediana_s"]).replace(".", ","),
        "__ENTRADA__": str(p["entrada"]),
        "__NICHOS_CAT__": str(n["nichos_catalogados"]),
        "__BLOCOS__": str(n["blocos"]),
        "__FAMILIAS__": str(n["familias"]),
        "__ATUALIZADO__": _e(p["atualizado_em"] or ""),
        "__CITACAO__": _e(citacao),
        "__NUMEROS__": _numeros_li(n),
        "__VITRINE__": _vitrine_cards(d["vitrine"]),
        "__PRECOS__": _precos_cards(p),
        "__FAQ__": _faq(n, cidades),
        "__VOCAB__": json.dumps(d["motor"], ensure_ascii=False, separators=(",", ":")),
    }
    doc = (AQUI / "index.html").read_text(encoding="utf-8")
    for k, v in troca.items():
        doc = doc.replace(k, v)
    return doc, {"numeros": n, "vitrine": len(d["vitrine"]), "cidades": len(cidades),
                 "bytes": len(doc.encode("utf-8"))}


def publicar(doc: str) -> Path:
    alvo = DESTINO / "index.html"
    if alvo.exists():
        bak = DESTINO / f"index.html.bak-{datetime.now(timezone.utc):%Y%m%d-%H%M%S}"
        shutil.copy2(alvo, bak)
    alvo.write_text(doc, encoding="utf-8")
    return alvo


if __name__ == "__main__":
    doc, info = render()
    # um placeholder esquecido vira "__MEDIANA__" na cara do cliente. Falha antes.
    sobrou = sorted(set(re.findall(r"__[A-Z_]{3,}__", doc)))
    if sobrou:
        print("ABORTADO — placeholders não substituídos:", ", ".join(sobrou))
        sys.exit(1)
    print(f"render OK — {info['bytes']//1024} KB · {info['vitrine']} na vitrine · "
          f"{info['cidades']} cidades · {info['numeros']['sites_no_ar']} sites no ar")
    if "--publicar" in sys.argv[1:]:
        print("publicado em", publicar(doc))
    else:
        p = Path("/root/.claude/jobs/670a75e8/tmp/jpos_preview.html")
        p.write_text(doc, encoding="utf-8")
        print("prévia em", p, "— rode com --publicar pra valer")
