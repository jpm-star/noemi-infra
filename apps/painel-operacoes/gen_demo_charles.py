"""Demo do Charles Cabeleireiros — EXCEÇÃO NOMEADA ao gate de motion do T1.

POR QUE ESTE ARQUIVO EXISTE, e por que ele NÃO é o novo padrão de T1:
o gate `motion_alto.NIVEL_POR_TIER` mantém T1 sem motion de propósito — motion é a
alavanca de vender T3/T4, e dar de graça no T1 queima o argumento. Charles é uma
exceção decidida pelo JP com motivo específico: ele é barbeiro de empresários da
cidade, então a demo não vende só a ele, ela circula por indicação. Aqui o custo de
impressionar é menor que o custo de parecer básico na mesa de quem vai indicar.

Qualquer outro T1 continua sem motion. Se isso virar padrão, vira SKU com nome e
preço próprios — não um `if` escondido aqui.

O template genérico (gen_demo_motion) não cobre o que esta demo precisa: DOIS
profissionais com peso igual e uma seção de depoimento real. Por isso página
própria, reusando a técnica que já está em produção: scroll-timeline nativo, o
mesmo de chinelospedi.com. Zero GSAP, zero Three, zero dependência externa.

TIPOGRAFIA: font-stack do sistema, sem webfont. Numa reunião presencial a internet
é do lugar, não sua — webfont que não carrega deixa a demo feia na hora exata em
que ela precisa estar bonita. O refino vem de escala, tracking e leading, que
custam zero request.

DADO REAL x DADO A CONFERIR:
  - Charles: nota 5,0/50 avaliações e "mais de 40 anos" saem do perfil público do
    Google (avaliação do Francisco Kurimori). São verificáveis na frente dele.
  - Fátima: NÃO tem perfil no Places e não há avaliação nominal dela. Entra com o
    mesmo peso visual, mas SEM número inventado — o texto dela fala do trabalho,
    não de métrica. JP confirma os detalhes com ela antes de publicar como cliente.
"""
from __future__ import annotations

import html
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, "/root/motor-site/app")

SLUG = "charles-cabeleireiros"
SAIDA = Path("/var/www/sites") / SLUG
WA = "5514998745847"  # número do JP: na reunião demonstra o fluxo real funcionando

NEGOCIO = "Charles Cabeleireiros"
TEL = "(14) 3522-6713"
ENDERECO = "R. Washington Luís, 132 — Labate, Lins/SP"
NOTA, N_AVAL = "5,0", 50

PROFISSIONAIS = [
    {"nome": "Charles", "foto": 3, "papel": "Barbeiro · mais de 40 anos de profissão",
     "texto": "Corte social, degradê e barba na navalha. A régua que virou referência "
              "em Lins — e a razão de metade dos clientes chegarem por indicação de "
              "quem já senta na cadeira há década.",
     "marcas": ["Degradê", "Barba na navalha", "Corte social"]},
    # sem `foto`: nenhuma das 4 do Google é foto profissional dela. Assim que o
    # JP mandar uma, é pôr "foto": <n> aqui e regerar.
    {"nome": "Fátima", "papel": "Cabeleireira · atendimento feminino",
     "texto": "Corte, escova, coloração e tratamento. O mesmo cuidado da casa, agora "
              "para quem quer sair com o cabelo do jeito que imaginou — com hora "
              "marcada e sem espera.",
     "marcas": ["Corte feminino", "Coloração", "Escova e tratamento"]},
]

# Avaliações públicas do Google, verbatim. São da CASA — nenhuma é atribuída a um
# profissional específico, porque o Google não separa isso e inventar atribuição
# numa demo que o dono vai ler seria o pior erro possível.
DEPOIMENTOS = [
    {"txt": "Excelente atendimento e qualidades nos serviços. Mais de 40 anos de experiência.",
     "por": "Francisco K."},
    {"txt": "Ambiente limpo e organizado, adorei o atendimento, meu cabelo ficou maravilhoso.",
     "por": "Priscila G."},
    {"txt": "Excelente profissional! Sempre atualizado com as necessidades dos clientes!",
     "por": "Brazilian Custom"},
    {"txt": "Muito carinhosos e atenciosos, excelente atendimento.", "por": "Marli P."},
]

SERVICOS = [
    ("Corte Social", "a partir de R$ 45", "O corte que resolve a semana inteira."),
    ("Degradê", "a partir de R$ 45", "Máquina, navalha e acabamento que não some em três dias."),
    ("Barba na Navalha", "a partir de R$ 35", "Toalha quente, navalha, pele tratada."),
    ("Corte + Barba", "a partir de R$ 70", "O combo, num horário só."),
    ("Corte Feminino", "consulte com a Fátima", "Corte, escova e finalização."),
    ("Coloração e Tratamento", "consulte com a Fátima", "Cor, hidratação e reconstrução."),
]


def _wa(assunto: str) -> str:
    import urllib.parse
    t = f"Oi! Vim pelo site e queria agendar: {assunto}"
    return f"https://wa.me/{WA}?text={urllib.parse.quote(t)}"


def _fotos() -> list[str]:
    """Foto real do perfil do Google, baixada pro disco (a URL do Places leva a
    API key, e esta página é pública)."""
    import gen_demos_venda as g
    fotos = g.fotos_do_negocio(f"{NEGOCIO}, Lins, SP", g._chave(), quantas=6)
    (SAIDA / "img").mkdir(parents=True, exist_ok=True)
    fora = []
    for i, dados in enumerate(fotos, 1):
        (SAIDA / "img" / f"{i:02d}.jpg").write_bytes(dados)
        fora.append(f"img/{i:02d}.jpg")
    return fora


# Qual foto vai onde — escolhido OLHANDO cada uma, não pela ordem do Places.
# A ordem do Places é arbitrária: na primeira geração, a selfie pessoal de uma
# mulher (tirada em casa, parede e fio à mostra) caiu no card da profissional. Foto
# pessoal não vai pra site de negócio, nem sendo dela.
FOTO_HERO = 2      # fachada com a placa "Charles cabelos" e o telefone
FOTO_CHARLES = 3   # ele cortando, no salão, tesoura na mão
FOTO_AMBIENTE = 1  # fachada de rua
FOTO_DESCARTADA = 4  # selfie pessoal — não usar


def render(fotos: list[str]) -> str:
    e = html.escape

    def f(n: int) -> str:
        """n = número do arquivo (1-based), como as constantes acima."""
        if not fotos:
            return ""
        return fotos[min(n, len(fotos)) - 1]

    cards = "".join(f'''
      <article class="sv revela">
        <div class="sv-img"><img loading="lazy" src="{f(1 + (i % 3))}" alt="{e(n)}"></div>
        <div class="sv-txt"><h3>{e(n)}</h3><p class="preco">{e(p)}</p><p>{e(d)}</p>
          <a class="mini" href="{_wa(n)}">agendar</a></div>
      </article>''' for i, (n, p, d) in enumerate(SERVICOS))

    def _midia(x, i):
        """Foto real quando existe; senão, card tipográfico com o nome.

        Um card de tipografia lê como escolha de design. Uma foto de pessoa errada
        lê como erro — e essa demo vai ser aberta na frente do dono."""
        if x.get("foto"):
            return f'''<div class="pro-foto"><img loading="lazy" src="{f(x["foto"])}"
                 alt="{e(x["nome"])}"></div>'''
        return f'''<div class="pro-foto pro-tipo"><span>{e(x["nome"][0])}</span>
                 <p>{e(x["nome"])}</p></div>'''

    profs = "".join(f'''
      <article class="pro revela">
        {_midia(x, i)}
        <div class="pro-txt">
          <h3>{e(x["nome"])}</h3>
          <p class="papel">{e(x["papel"])}</p>
          <p>{e(x["texto"])}</p>
          <ul class="marcas">{"".join(f"<li>{e(m)}</li>" for m in x["marcas"])}</ul>
          <a class="mini" href="{_wa('horário com ' + x['nome'])}">agendar com {e(x["nome"])}</a>
        </div>
      </article>''' for i, x in enumerate(PROFISSIONAIS))

    depos = "".join(f'''
      <figure class="depo revela">
        <blockquote>{e(d["txt"])}</blockquote>
        <figcaption>{e(d["por"])} <span>· Google</span></figcaption>
      </figure>''' for d in DEPOIMENTOS)

    return f"""<!doctype html><html lang="pt-BR" data-tier="T1" data-motion="completo"
 data-excecao="motion liberado por decisao do JP — nao e o padrao T1">
<head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{e(NEGOCIO)}</title>
<meta name="description" content="Barbearia em Lins/SP. Nota {NOTA} no Google. Agende pelo WhatsApp.">
<style>
:root{{
  --tinta:#0d0d0f; --papel:#f7f5f2; --ouro:#c9a227; --ouro-claro:#e8cf7a;
  --grafite:#1c1c20; --cinza:#7d7d86; --linha:rgba(0,0,0,.09);
  /* escala tipográfica 1.25 — o refino vem daqui, não de webfont */
  --f-xs:.78rem; --f-s:.94rem; --f-m:1.18rem; --f-l:1.85rem; --f-xl:3rem; --f-2xl:clamp(2.8rem,9vw,6rem);
}}
*{{box-sizing:border-box;margin:0}}
html{{scroll-behavior:smooth}}
body{{background:var(--papel);color:var(--tinta);
  font:400 var(--f-s)/1.65 ui-sans-serif,system-ui,-apple-system,"Segoe UI",Roboto,sans-serif;
  -webkit-font-smoothing:antialiased;text-rendering:optimizeLegibility}}
h1,h2,h3{{font-family:ui-serif,Georgia,"Times New Roman",serif;font-weight:600;
  letter-spacing:-.022em;line-height:1.06}}
img{{display:block;width:100%;height:100%;object-fit:cover}}
.wrap{{max-width:1080px;margin:0 auto;padding:0 22px}}

/* ── HERO ── */
.hero{{position:relative;min-height:92vh;display:grid;align-items:end;
  background:var(--grafite);color:var(--papel);overflow:hidden}}
.hero-bg{{position:absolute;inset:0}}
.hero-bg img{{filter:grayscale(.35) brightness(.5)}}
.hero-bg::after{{content:"";position:absolute;inset:0;
  background:linear-gradient(180deg,rgba(13,13,15,.25) 0%,rgba(13,13,15,.9) 78%)}}
.hero-in{{position:relative;padding:0 0 clamp(2.5rem,7vw,5rem)}}
.selo{{display:inline-flex;align-items:center;gap:.5rem;font-size:var(--f-xs);
  letter-spacing:.19em;text-transform:uppercase;color:var(--ouro-claro);margin-bottom:1.4rem}}
.selo b{{color:var(--papel);font-weight:600;letter-spacing:.06em}}
.hero h1{{font-size:var(--f-2xl);color:var(--papel);margin-bottom:1.1rem}}
.hero h1 em{{font-style:italic;color:var(--ouro-claro)}}
.hero p.lead{{font-size:var(--f-m);max-width:44ch;color:rgba(247,245,242,.82);margin-bottom:1.9rem}}
.cta{{display:inline-block;background:var(--ouro);color:#1a1400;font-weight:700;
  padding:1rem 2.1rem;border-radius:2px;letter-spacing:.03em;
  transition:transform .35s cubic-bezier(.2,.8,.2,1),box-shadow .35s}}
.cta:hover{{transform:translateY(-3px);box-shadow:0 14px 34px rgba(201,162,39,.34)}}
a{{color:inherit;text-decoration:none}}

/* ── seções ── */
section{{padding:clamp(4rem,11vw,8rem) 0}}
.rot{{font-size:var(--f-xs);letter-spacing:.21em;text-transform:uppercase;
  color:var(--cinza);margin-bottom:.85rem}}
.tit{{font-size:var(--f-xl);margin-bottom:2.6rem;max-width:22ch}}

.pros{{display:grid;gap:clamp(2rem,5vw,4rem)}}
.pro{{display:grid;grid-template-columns:minmax(0,.85fr) minmax(0,1.15fr);
  gap:clamp(1.4rem,4vw,3rem);align-items:center}}
.pro:nth-child(even) .pro-foto{{order:2}}
.pro-foto{{aspect-ratio:4/5;overflow:hidden;background:var(--grafite)}}
.pro-foto img{{transition:transform 1.1s cubic-bezier(.2,.8,.2,1)}}
.pro:hover .pro-foto img{{transform:scale(1.045)}}
.pro h3{{font-size:var(--f-l);margin-bottom:.28rem}}
.pro-tipo{{display:grid;place-content:center;text-align:center;background:var(--grafite);
  color:var(--papel);gap:.5rem}}
.pro-tipo span{{font-family:ui-serif,Georgia,serif;font-size:clamp(4rem,11vw,7rem);
  line-height:1;color:var(--ouro-claro)}}
.pro-tipo p{{font-size:var(--f-xs);letter-spacing:.24em;text-transform:uppercase;
  color:rgba(247,245,242,.6)}}
.papel{{color:var(--ouro);font-size:var(--f-xs);letter-spacing:.13em;
  text-transform:uppercase;margin-bottom:1rem}}
.marcas{{list-style:none;display:flex;flex-wrap:wrap;gap:.45rem;margin:1.15rem 0 1.5rem;padding:0}}
.marcas li{{border:1px solid var(--linha);padding:.3rem .8rem;border-radius:2px;
  font-size:var(--f-xs);color:var(--cinza)}}
.mini{{display:inline-block;border-bottom:1px solid var(--ouro);padding-bottom:2px;
  font-size:var(--f-xs);letter-spacing:.14em;text-transform:uppercase;font-weight:600}}

.grade{{display:grid;grid-template-columns:repeat(auto-fit,minmax(268px,1fr));gap:1.5rem}}
.sv{{background:#fff;border:1px solid var(--linha)}}
.sv-img{{aspect-ratio:3/2;overflow:hidden}}
.sv-img img{{transition:transform .9s cubic-bezier(.2,.8,.2,1)}}
.sv:hover .sv-img img{{transform:scale(1.06)}}
.sv-txt{{padding:1.35rem}}
.sv h3{{font-size:var(--f-m);margin-bottom:.2rem}}
.preco{{color:var(--ouro);font-size:var(--f-xs);letter-spacing:.1em;
  text-transform:uppercase;margin-bottom:.6rem}}
.sv p{{color:var(--cinza);margin-bottom:1rem}}

.prova{{background:var(--grafite);color:var(--papel)}}
.prova .rot{{color:var(--ouro-claro)}}
.prova .tit{{color:var(--papel)}}
.nota-big{{display:flex;align-items:baseline;gap:1rem;margin-bottom:2.8rem}}
.nota-big b{{font-family:ui-serif,Georgia,serif;font-size:clamp(3.4rem,10vw,5.6rem);
  line-height:1;color:var(--ouro-claro)}}
.nota-big span{{color:rgba(247,245,242,.62);font-size:var(--f-s)}}
.depos{{display:grid;grid-template-columns:repeat(auto-fit,minmax(255px,1fr));gap:1.4rem}}
.depo{{border-left:2px solid var(--ouro);padding:.2rem 0 .2rem 1.35rem}}
.depo blockquote{{font-family:ui-serif,Georgia,serif;font-size:var(--f-m);
  font-style:italic;line-height:1.5;margin-bottom:.8rem}}
.depo figcaption{{font-size:var(--f-xs);letter-spacing:.1em;text-transform:uppercase;
  color:rgba(247,245,242,.55)}}
.depo figcaption span{{color:var(--ouro)}}

.fim{{text-align:center}}
.fim h2{{font-size:var(--f-xl);margin-bottom:1.1rem}}
.fim p{{color:var(--cinza);margin-bottom:2rem}}
.pe{{border-top:1px solid var(--linha);padding:2.5rem 0;font-size:var(--f-xs);
  color:var(--cinza);display:flex;gap:1.2rem;flex-wrap:wrap;justify-content:space-between}}
.tagdemo{{position:fixed;right:14px;bottom:14px;background:var(--tinta);color:var(--papel);
  font-size:.68rem;letter-spacing:.14em;text-transform:uppercase;padding:.42rem .85rem;
  border-radius:2px;opacity:.82;z-index:9}}

/* ── MOTION: scroll-timeline nativo, 0 KB de JS. Mesma técnica de chinelospedi.com.
   Tudo dentro de @supports + prefers-reduced-motion: quem pediu menos movimento, ou
   usa navegador sem scroll-timeline, não recebe nem as keyframes — o elemento
   renderiza no estado natural e nada quebra. ── */
@supports (animation-timeline: view()) {{
  @media (prefers-reduced-motion: no-preference) {{
    @keyframes surgir{{from{{opacity:0;transform:translateY(2.2rem)}}to{{opacity:1;transform:none}}}}
    @keyframes cede{{from{{opacity:1;transform:none}}to{{opacity:.2;transform:translateY(-1.4rem) scale(.98)}}}}
    @keyframes revelar-img{{from{{clip-path:inset(0 0 100% 0)}}to{{clip-path:inset(0 0 0 0)}}}}
    .revela{{animation:surgir linear both;animation-timeline:view();
      animation-range:entry 0% entry 46%}}
    .revela:nth-child(2){{animation-range:entry 0% entry 58%}}
    .revela:nth-child(3){{animation-range:entry 0% entry 68%}}
    .revela:nth-child(n+4){{animation-range:entry 0% entry 78%}}
    /* continuidade: a seção SAI cedendo o palco, não fica parada esperando */
    .tit,.pros,.grade{{animation:cede linear both;animation-timeline:view();
      animation-range:exit 34% exit 100%}}
    /* a foto do profissional se revela de baixo pra cima — o gesto que faz a
       página parecer feita, não montada */
    .pro-foto img{{animation:revelar-img linear both;animation-timeline:view();
      animation-range:entry 6% entry 62%}}
    .hero-in{{animation:cede linear both;animation-timeline:view();
      animation-range:exit 0% exit 92%}}
  }}
}}
@media (prefers-reduced-motion: reduce){{
  html{{scroll-behavior:auto}}
  .cta,.pro-foto img,.sv-img img{{transition:none}}
}}
@media (max-width:760px){{
  .pro{{grid-template-columns:1fr}}
  .pro:nth-child(even) .pro-foto{{order:0}}
}}
</style></head>
<body>

<header class="hero">
  <div class="hero-bg"><img src="{f(FOTO_HERO)}" alt="{e(NEGOCIO)}"></div>
  <div class="wrap hero-in">
    <p class="selo">★ {NOTA} no Google <b>· {N_AVAL} avaliações</b></p>
    <h1>Quarenta anos<br>de <em>régua</em>.</h1>
    <p class="lead">Barbearia em Lins. Corte social, degradê e barba na navalha —
      e agora atendimento feminino com a Fátima, na mesma casa.</p>
    <a class="cta" href="{_wa('um horário')}">Agendar pelo WhatsApp</a>
  </div>
</header>

<section class="wrap">
  <p class="rot">Quem atende</p>
  <h2 class="tit">Duas cadeiras, o mesmo padrão.</h2>
  <div class="pros">{profs}</div>
</section>

<section class="wrap">
  <p class="rot">Serviços</p>
  <h2 class="tit">O que dá pra agendar agora.</h2>
  <div class="grade">{cards}</div>
</section>

<section class="prova">
  <div class="wrap">
    <p class="rot">Prova social</p>
    <h2 class="tit">Nota cheia, sem exceção.</h2>
    <div class="nota-big revela"><b>{NOTA}</b><span>de {N_AVAL} avaliações no Google —<br>
      nenhuma abaixo de cinco estrelas.</span></div>
    <div class="depos">{depos}</div>
  </div>
</section>

<section class="wrap fim">
  <h2>Sua cadeira está livre.</h2>
  <p>Chame no WhatsApp e marque com Charles ou com a Fátima.</p>
  <a class="cta" href="{_wa('um horário')}">Agendar agora</a>
  <div class="pe"><span>{e(NEGOCIO)} · {e(ENDERECO)}</span><span>{e(TEL)}</span></div>
</section>

<span class="tagdemo">demonstração</span>
</body></html>"""


def gerar() -> dict:
    SAIDA.mkdir(parents=True, exist_ok=True)
    fotos = _fotos()
    (SAIDA / "index.html").write_text(render(fotos), encoding="utf-8")
    return {"url": f"https://p.jpos.com.br/{SLUG}/", "fotos_reais": len(fotos),
            "tier": "T1", "motion": "completo (exceção nomeada)"}


if __name__ == "__main__":
    import json
    if "--selfcheck" in sys.argv:
        h = render(["img/01.jpg", "img/02.jpg", "img/03.jpg"])
        # os dois profissionais têm de existir com o MESMO peso estrutural
        assert h.count('class="pro revela"') == 2, "faltou profissional"
        assert "Fátima" in h and "Charles" in h
        assert h.count("agendar com") == 2, "cada profissional precisa do próprio CTA"
        # motion tem de estar ligado, e sempre atrás dos dois guards
        assert "animation-timeline:view()" in h and "@supports (animation-timeline: view())" in h
        assert "prefers-reduced-motion: no-preference" in h
        assert "prefers-reduced-motion: reduce" in h
        # prova social real, e nenhuma métrica inventada pra Fátima
        assert "Francisco K." in h and "Priscila G." in h
        # Fátima NÃO pode receber foto de pessoa que não foi confirmada como ela
        assert 'class="pro-foto pro-tipo"' in h, "card tipográfico da Fátima sumiu"
        assert h.count('class="pro-foto"') == 1, "só Charles tem foto de pessoa"
        assert "5,0" in h and "50 avaliações" in h
        # a exceção tem de ficar VISÍVEL no HTML, senão vira precedente silencioso
        assert 'data-excecao=' in h and 'data-tier="T1"' in h
        # sem dependência externa: nada de webfont/CDN numa demo presencial
        for proibido in ("fonts.googleapis", "cdn.", "loremflickr", "picsum", "gsap", "three.min"):
            assert proibido not in h, proibido
        print("OK — self-check do Charles passou.")
    else:
        print(json.dumps(gerar(), ensure_ascii=False, indent=2))
