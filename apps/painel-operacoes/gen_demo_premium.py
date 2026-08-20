"""Template premium — o padrão do Charles, agora para qualquer negócio.

O que fez a demo do Charles funcionar não foi o motion: foi a PROVA SOCIAL REAL na
página. Nota, número de avaliações e depoimentos verbatim, todos conferíveis pelo
dono na hora. Isso o Places entrega para qualquer negócio, então vira automático
aqui — não é texto escrito à mão por demo.

Diferença pro gen_demos_venda (template de grade): aquele mostra serviços; este
mostra CREDIBILIDADE. Serve quando o negócio já tem reputação no Google e o
argumento é "você é bom e o site não mostra isso".

MOTION: scroll-timeline nativo, mesma técnica do chinelospedi.com. 0 KB de JS,
sem GSAP, sem Three, sem webfont. Tudo atrás de @supports + prefers-reduced-motion.

REGRA QUE NÃO PODE CAIR: nada aqui é inventado. Sem avaliação no Places, a seção
de prova social simplesmente não é renderizada — página com menos seção é melhor
que página com número falso, porque o dono confere na frente de você.
"""
from __future__ import annotations

import html
import json
import re
import sys
import unicodedata
import urllib.parse
from pathlib import Path

_AQUI = Path(__file__).resolve().parent
sys.path.insert(0, str(_AQUI))
sys.path.insert(0, "/root/motor-site/app")

SITES = Path("/var/www/sites")
WA = "5514998745847"  # número do JP: demonstra o fluxo real na conversa

# Fotos que NÃO servem: selfie pessoal, print de tela. Heurística barata por
# proporção — foto de retrato muito estreita vinda do Google costuma ser selfie de
# celular, e foi assim que uma selfie caiu num card de profissional.
_MIN_BYTES = 12_000


def _slug(t: str) -> str:
    t = unicodedata.normalize("NFKD", t or "").encode("ascii", "ignore").decode()
    return re.sub(r"-+", "-", re.sub(r"[^a-z0-9]+", "-", t.lower())).strip("-")[:60]


def _wa(assunto: str) -> str:
    return f"https://wa.me/{WA}?text={urllib.parse.quote('Oi! Vim pelo site: ' + assunto)}"


def dados_do_google(busca: str) -> dict:
    """Tudo que a página precisa, do perfil público: nota, avaliações, fotos, contato."""
    import gen_demos_venda as g
    k = g._chave()
    b = g._get(g._TEXTSEARCH, {"query": busca, "language": "pt-BR", "key": k})
    res = b.get("results") or []
    if not res:
        return {"achou": False, "reviews": [], "fotos": []}
    pid = res[0]["place_id"]
    d = g._get(g._DETAILS, {"place_id": pid, "language": "pt-BR", "key": k,
                            "fields": "name,formatted_address,formatted_phone_number,rating,"
                                      "user_ratings_total,reviews,photos,website"}).get("result") or {}
    # só depoimento 4★+ e com texto que diga alguma coisa
    revs = [r for r in (d.get("reviews") or [])
            if (r.get("rating") or 0) >= 4 and len((r.get("text") or "").strip()) > 24][:4]
    return {"achou": True, "nome": d.get("name"), "endereco": d.get("formatted_address"),
            "telefone": d.get("formatted_phone_number"), "site": d.get("website") or "",
            "nota": d.get("rating"), "avaliacoes": d.get("user_ratings_total") or 0,
            "reviews": revs, "fotos": d.get("photos") or [], "place_id": pid}


def baixar_fotos(slug: str, busca: str, quantas: int = 6) -> list[str]:
    import gen_demos_venda as g
    fotos = [f for f in g.fotos_do_negocio(busca, g._chave(), quantas=quantas)
             if len(f) > _MIN_BYTES]
    pasta = SITES / slug / "img"
    pasta.mkdir(parents=True, exist_ok=True)
    fora = []
    for i, dados in enumerate(fotos, 1):
        (pasta / f"{i:02d}.jpg").write_bytes(dados)
        fora.append(f"img/{i:02d}.jpg")
    return fora


def _milhar(n) -> str:
    """7096 -> 7.096. Número sem separador lê como dado cru de sistema, não como
    página escrita por gente — e é o dono do negócio que vai ler."""
    return f"{int(n):,}".replace(",", ".")


def _corta(txt: str, limite: int = 200) -> str:
    """Corta na última palavra INTEIRA. Cortar no meio ('...buscam d') faz o
    depoimento parecer quebrado justamente na seção que serve pra dar credibilidade."""
    t = " ".join((txt or "").split())
    if len(t) <= limite:
        return t
    return t[:limite].rsplit(" ", 1)[0].rstrip(".,;:") + "…"


def _primeiro_nome(autor: str) -> str:
    """'Francisco Kurimori' -> 'Francisco K.' — crédito sem expor nome completo."""
    partes = (autor or "").strip().split()
    if not partes:
        return "Cliente do Google"
    return partes[0] + (f" {partes[1][0]}." if len(partes) > 1 else "")


# ponytail: substituição literal, não %-format nem f-string. O CSS é cheio de "%"
# (animation-range: entry 0% entry 46%) e de "{}" — qualquer um dos dois quebraria.
CSS = """
:root{--tinta:#0d0d0f;--papel:#f7f5f2;--dest:@COR@;--dest2:@COR2@;--grafite:#1c1c20;
  --cinza:#7d7d86;--linha:rgba(0,0,0,.09);
  --f-xs:.78rem;--f-s:.94rem;--f-m:1.18rem;--f-l:1.85rem;--f-xl:3rem;--f-2xl:clamp(2.6rem,8.5vw,5.6rem)}
*{box-sizing:border-box;margin:0}
html{scroll-behavior:smooth}
body{background:var(--papel);color:var(--tinta);
  font:400 var(--f-s)/1.65 ui-sans-serif,system-ui,-apple-system,"Segoe UI",Roboto,sans-serif;
  -webkit-font-smoothing:antialiased;text-rendering:optimizeLegibility}
h1,h2,h3{font-family:ui-serif,Georgia,"Times New Roman",serif;font-weight:600;
  letter-spacing:-.022em;line-height:1.07}
img{display:block;width:100%;height:100%;object-fit:cover}
a{color:inherit;text-decoration:none}
.wrap{max-width:1080px;margin:0 auto;padding:0 22px}
.hero{position:relative;min-height:92vh;display:grid;align-items:end;
  background:var(--grafite);color:var(--papel);overflow:hidden}
.hero-bg{position:absolute;inset:0}
.hero-bg img{filter:grayscale(.3) brightness(.48)}
.hero-bg::after{content:"";position:absolute;inset:0;
  background:linear-gradient(180deg,rgba(13,13,15,.22),rgba(13,13,15,.9) 78%)}
.hero-in{position:relative;padding:0 0 clamp(2.5rem,7vw,5rem)}
.selo{display:inline-flex;gap:.5rem;font-size:var(--f-xs);letter-spacing:.19em;
  text-transform:uppercase;color:var(--dest2);margin-bottom:1.4rem}
.selo b{color:var(--papel);font-weight:600;letter-spacing:.06em}
.hero h1{font-size:var(--f-2xl);color:var(--papel);margin-bottom:1.1rem}
.hero h1 em{font-style:italic;color:var(--dest2)}
.lead{font-size:var(--f-m);max-width:46ch;color:rgba(247,245,242,.82);margin-bottom:1.9rem}
.cta{display:inline-block;background:var(--dest);color:#12100a;font-weight:700;
  padding:1rem 2.1rem;border-radius:2px;letter-spacing:.03em;
  transition:transform .35s cubic-bezier(.2,.8,.2,1),box-shadow .35s}
.cta:hover{transform:translateY(-3px);box-shadow:0 14px 34px rgba(0,0,0,.28)}
section{padding:clamp(3.6rem,10vw,7.5rem) 0}
.rot{font-size:var(--f-xs);letter-spacing:.21em;text-transform:uppercase;
  color:var(--cinza);margin-bottom:.85rem}
.tit{font-size:var(--f-xl);margin-bottom:2.6rem;max-width:22ch}
.grade{display:grid;grid-template-columns:repeat(auto-fit,minmax(268px,1fr));gap:1.5rem}
.sv{background:#fff;border:1px solid var(--linha)}
.sv-img{aspect-ratio:3/2;overflow:hidden}
.sv-img img{transition:transform .9s cubic-bezier(.2,.8,.2,1)}
.sv:hover .sv-img img{transform:scale(1.06)}
.sv-txt{padding:1.35rem}
.sv h3{font-size:var(--f-m);margin-bottom:.2rem}
.preco{color:var(--dest);font-size:var(--f-xs);letter-spacing:.1em;
  text-transform:uppercase;margin-bottom:.6rem}
.sv p{color:var(--cinza);margin-bottom:1rem}
.mini{display:inline-block;border-bottom:1px solid var(--dest);padding-bottom:2px;
  font-size:var(--f-xs);letter-spacing:.14em;text-transform:uppercase;font-weight:600}
.prova{background:var(--grafite);color:var(--papel)}
.prova .rot{color:var(--dest2)}.prova .tit{color:var(--papel)}
.nota-big{display:flex;align-items:baseline;gap:1rem;margin-bottom:2.6rem}
.nota-big b{font-family:ui-serif,Georgia,serif;font-size:clamp(3.2rem,9vw,5.4rem);
  line-height:1;color:var(--dest2)}
.nota-big span{color:rgba(247,245,242,.62)}
.depos{display:grid;grid-template-columns:repeat(auto-fit,minmax(255px,1fr));gap:1.4rem}
.depo{border-left:2px solid var(--dest);padding:.2rem 0 .2rem 1.35rem}
.depo blockquote{font-family:ui-serif,Georgia,serif;font-size:var(--f-m);
  font-style:italic;line-height:1.5;margin-bottom:.8rem}
.depo figcaption{font-size:var(--f-xs);letter-spacing:.1em;text-transform:uppercase;
  color:rgba(247,245,242,.55)}
.depo figcaption span{color:var(--dest2)}
.fim{text-align:center}
.fim h2{font-size:var(--f-xl);margin-bottom:1.1rem}
.fim p{color:var(--cinza);margin-bottom:2rem}
.pe{border-top:1px solid var(--linha);padding:2.4rem 0;font-size:var(--f-xs);
  color:var(--cinza);display:flex;gap:1.2rem;flex-wrap:wrap;justify-content:space-between}
.tagdemo{position:fixed;right:14px;bottom:14px;background:var(--tinta);color:var(--papel);
  font-size:.68rem;letter-spacing:.14em;text-transform:uppercase;padding:.42rem .85rem;
  border-radius:2px;opacity:.82;z-index:9}
@supports (animation-timeline: view()){
  @media (prefers-reduced-motion: no-preference){
    @keyframes surgir{from{opacity:0;transform:translateY(2.2rem)}to{opacity:1;transform:none}}
    @keyframes cede{from{opacity:1;transform:none}to{opacity:.2;transform:translateY(-1.4rem) scale(.98)}}
    @keyframes revelar{from{clip-path:inset(0 0 100% 0)}to{clip-path:inset(0 0 0 0)}}
    .revela{animation:surgir linear both;animation-timeline:view();animation-range:entry 0% entry 46%}
    .revela:nth-child(2){animation-range:entry 0% entry 58%}
    .revela:nth-child(3){animation-range:entry 0% entry 68%}
    .revela:nth-child(n+4){animation-range:entry 0% entry 78%}
    .tit,.grade{animation:cede linear both;animation-timeline:view();animation-range:exit 34% exit 100%}
    .sv-img img{animation:revelar linear both;animation-timeline:view();animation-range:entry 6% entry 60%}
    .hero-in{animation:cede linear both;animation-timeline:view();animation-range:exit 0% exit 92%}
  }
}
@media (prefers-reduced-motion: reduce){html{scroll-behavior:auto}
  .cta,.sv-img img{transition:none}}
"""


def render(neg: dict, dados: dict, fotos: list[str]) -> str:
    e = html.escape
    f = lambda i: fotos[i % len(fotos)] if fotos else ""
    nome = neg["negocio"]

    cards = "".join(f'''
      <article class="sv revela">
        <div class="sv-img"><img loading="lazy" src="{f(i)}" alt="{e(s["nome"])}"></div>
        <div class="sv-txt"><h3>{e(s["nome"])}</h3><p class="preco">{e(s["preco"])}</p>
          <p>{e(s["desc"])}</p><a class="mini" href="{_wa(s["nome"])}">agendar</a></div>
      </article>''' for i, s in enumerate(neg["servicos"]))

    # PROVA SOCIAL: só existe se o Google tiver. Sem isso, a seção some inteira.
    prova = ""
    if dados.get("nota") and dados.get("avaliacoes"):
        depos = "".join(f'''
          <figure class="depo revela"><blockquote>{e(_corta(r.get("text", "")))}</blockquote>
            <figcaption>{e(_primeiro_nome(r.get("author_name", "")))} <span>· Google</span></figcaption>
          </figure>''' for r in dados["reviews"])
        nota = f"{dados['nota']:.1f}".replace(".", ",")
        prova = f'''
<section class="prova"><div class="wrap">
  <p class="rot">O que dizem</p>
  <h2 class="tit">{e(neg.get("tit_prova", "A reputação já existe."))}</h2>
  <div class="nota-big revela"><b>{nota}</b>
    <span>de {_milhar(dados["avaliacoes"])} avaliações no Google.</span></div>
  <div class="depos">{depos}</div>
</div></section>'''

    tel = dados.get("telefone") or ""
    end = dados.get("endereco") or ""
    selo = (f'<p class="selo">★ {dados["nota"]:.1f} no Google <b>· {_milhar(dados["avaliacoes"])} avaliações</b></p>'
            if dados.get("nota") else "")

    return f"""<!doctype html><html lang="pt-BR" data-tier="{neg['tier']}" data-motion="completo"
 data-template="premium">
<head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{e(nome)}</title>
<meta name="description" content="{e(neg['tagline'])}">
<style>{CSS.replace('@COR@', neg['cor']).replace('@COR2@', neg['cor2'])}</style></head>
<body>
<header class="hero">
  <div class="hero-bg"><img src="{f(0)}" alt="{e(nome)}"></div>
  <div class="wrap hero-in">
    {selo}
    <h1>{neg['h1']}</h1>
    <p class="lead">{e(neg['tagline'])}</p>
    <a class="cta" href="{_wa('quero falar com vocês')}">Falar no WhatsApp</a>
  </div>
</header>
<section class="wrap">
  <p class="rot">O que oferecemos</p>
  <h2 class="tit">{e(neg.get('tit_servicos', 'Tudo num lugar só.'))}</h2>
  <div class="grade">{cards}</div>
</section>
{prova}
<section class="wrap fim">
  <h2>Vamos conversar?</h2>
  <p>Chame no WhatsApp e a gente responde na hora.</p>
  <a class="cta" href="{_wa('quero falar com vocês')}">Falar agora</a>
  <div class="pe"><span>{e(nome)}{(' · ' + e(end)) if end else ''}</span><span>{e(tel)}</span></div>
</section>
<span class="tagdemo">demonstração</span>
</body></html>"""


def gerar(slug: str, neg: dict) -> dict:
    """neg precisa de: negocio, busca, tier, cor, cor2, h1, tagline, servicos."""
    alvo = SITES / slug
    alvo.mkdir(parents=True, exist_ok=True)
    dados = dados_do_google(neg["busca"])
    fotos = baixar_fotos(slug, neg["busca"])
    if not fotos:
        import gen_demos_venda as g
        fotos = [g._bloco_cor(slug, neg["cor"], neg["cor2"], neg["negocio"], 1)]
    (alvo / "index.html").write_text(render(neg, dados, fotos), encoding="utf-8")
    # meta ao lado do demo: o telefone vem do Places na geração, e sem guardar aqui
    # a prospecção teria que consultar de novo (custo) ou o JP digitar (erro).
    (alvo / "meta.json").write_text(json.dumps({
        "negocio": neg["negocio"], "tier": neg["tier"], "busca": neg["busca"],
        "telefone": dados.get("telefone") or "", "nota": dados.get("nota"),
        "avaliacoes": dados.get("avaliacoes", 0), "site_atual": dados.get("site") or "",
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"slug": slug, "url": f"https://p.jpos.com.br/{slug}/", "tier": neg["tier"],
            "fotos": len(fotos), "nota": dados.get("nota"),
            "avaliacoes": dados.get("avaliacoes", 0), "depoimentos": len(dados.get("reviews", [])),
            "tem_prova_social": bool(dados.get("nota"))}


if __name__ == "__main__":
    if "--selfcheck" in sys.argv:
        neg = {"negocio": "Teste", "tier": "T3", "cor": "#c9a227", "cor2": "#e8cf7a",
               "h1": "Um <em>teste</em>.", "tagline": "tagline",
               "servicos": [{"nome": f"S{i}", "preco": "R$ 1", "desc": "d"} for i in range(6)]}
        # com prova social
        d = {"nota": 4.8, "avaliacoes": 120, "telefone": "(14) 1", "endereco": "rua x",
             "reviews": [{"rating": 5, "text": "muito bom mesmo, recomendo demais",
                          "author_name": "Ana Paula Silva"}]}
        h = render(neg, d, ["img/01.jpg"])
        assert "4,8" in h and "120 avaliações" in h and "Ana P." in h
        assert "Ana Paula Silva" not in h, "não expor nome completo"
        # SEM prova social a seção some — nada de número inventado
        h2 = render(neg, {"reviews": []}, ["img/01.jpg"])
        assert "avaliações" not in h2 and 'class="prova"' not in h2
        # motion e guards
        for x in ("animation-timeline:view()", "prefers-reduced-motion: no-preference",
                  "prefers-reduced-motion: reduce"):
            assert x in h, x
        for proibido in ("fonts.googleapis", "cdn.", "gsap", "three.min", "loremflickr", "picsum"):
            assert proibido not in h, proibido
        assert _milhar(7096) == "7.096" and _milhar(61) == "61"
        cortado = _corta("uma frase bem comprida que precisa ser cortada", 20)
        assert cortado.endswith("…") and not cortado.endswith(" …")
        assert " d…" not in cortado, "cortou no meio da palavra"
        assert _corta("curta") == "curta"
        assert _primeiro_nome("Francisco Kurimori") == "Francisco K."
        assert _primeiro_nome("") == "Cliente do Google"
        print("OK — self-check do template premium passou.")
    else:
        print(json.dumps({"uso": "importar e chamar gerar(slug, neg)"}, ensure_ascii=False))
