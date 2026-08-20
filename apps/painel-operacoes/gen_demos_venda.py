"""Demos de venda — foto REAL do Google Places + motion pelo tier.

Corrige o defeito que matou a primeira leva e gera os 8 novos já certos.

O DEFEITO, com precisão: os demos nunca usaram os screenshots do Drive (grep no
HTML publicado dá zero). A imagem vinha do `loremflickr` por palavra-chave, com
`onerror` caindo em `picsum.photos`, que devolve foto ALEATÓRIA. Foi de lá que
saiu um gato no card de massagem. Ou seja, a causa não é a fonte errada de foto —
é um fallback que aceita qualquer imagem. Trocar por Places sem matar o fallback
deixaria o gato voltar no primeiro 404.

Aqui: foto do próprio negócio via Places Photos, BAIXADA pro disco e servida
local. Baixar não é capricho — a URL do Places Photos leva a API key no
querystring, e o HTML é público. Servir local mantém a chave fora do ar e o demo
de pé se a cota acabar.

Sem foto suficiente = o card cai num bloco de cor da marca com o nome do serviço.
Nunca em imagem genérica: um card honestamente vazio custa menos numa call que um
gato.

Motion: `motion_alto.NIVEL_POR_TIER` do motor-site, sem reescrever nada. T1 não
recebe um byte de motion — é a alavanca de vender T3/T4, e um T1 com Lusion
completo de graça queima o próprio argumento.
"""
from __future__ import annotations

import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

sys.path.insert(0, "/root/motor-site")
sys.path.insert(0, "/root/motor-site/app")

import gen_demo_motion as motor  # noqa: E402
import motion_alto  # noqa: E402

_TEXTSEARCH = "https://maps.googleapis.com/maps/api/place/textsearch/json"
_DETAILS = "https://maps.googleapis.com/maps/api/place/details/json"
_PHOTO = "https://maps.googleapis.com/maps/api/place/photo"
SAIDA = Path("/var/www/sites")
MIN_FOTOS = 3  # abaixo disso o demo fica mais honesto com bloco de cor que com foto alheia


def _chave() -> str:
    k = os.environ.get("GOOGLE_PLACES_API_KEY", "").strip()
    if not k:
        for ln in Path("/root/noemi-infra/.env").read_text(encoding="utf-8", errors="ignore").splitlines():
            if ln.startswith("GOOGLE_PLACES_API_KEY"):
                k = ln.partition("=")[2].strip().strip('"').strip("'")
    if not k:
        raise RuntimeError("defina GOOGLE_PLACES_API_KEY")
    return k


def _get(url: str, params: dict) -> dict:
    with urllib.request.urlopen(f"{url}?{urllib.parse.urlencode(params)}", timeout=25) as r:
        return json.loads(r.read().decode("utf-8"))


def fotos_do_negocio(busca: str, api_key: str, quantas: int = 6) -> list[bytes]:
    """Fotos que o próprio negócio (ou clientes) publicaram no perfil do Google.

    Devolve os bytes, não URLs — ver docstring do módulo sobre a API key.
    """
    b = _get(_TEXTSEARCH, {"query": busca, "language": "pt-BR", "key": api_key})
    res = (b.get("results") or [])
    if not res:
        return []
    pid = res[0].get("place_id")
    det = _get(_DETAILS, {"place_id": pid, "fields": "photos,name", "language": "pt-BR",
                          "key": api_key}).get("result") or {}
    fora = []
    for f in (det.get("photos") or [])[:quantas]:
        ref = f.get("photo_reference")
        if not ref:
            continue
        try:
            u = f"{_PHOTO}?{urllib.parse.urlencode({'maxwidth': 900, 'photo_reference': ref, 'key': api_key})}"
            with urllib.request.urlopen(u, timeout=25) as r:
                dados = r.read()
            if len(dados) > 8000:  # imagem degenerada/erro não vira card
                fora.append(dados)
        except Exception:  # noqa: BLE001 — foto que não baixa é foto a menos, não falha
            pass
        time.sleep(0.15)
    return fora


def _bloco_cor(slug: str, cor: str, cor2: str, rotulo: str, n: int) -> str:
    """Placeholder honesto: cor da marca + nome do serviço, em SVG (sem download)."""
    t = re.sub(r"[^\w\s-]", "", rotulo)[:28]
    svg = (f'<svg xmlns="http://www.w3.org/2000/svg" width="900" height="620">'
           f'<defs><linearGradient id="g" x1="0" y1="0" x2="1" y2="1">'
           f'<stop offset="0" stop-color="{cor2}"/><stop offset="1" stop-color="{cor}"/>'
           f'</linearGradient></defs><rect width="900" height="620" fill="url(#g)"/>'
           f'<text x="50%" y="50%" text-anchor="middle" font-family="system-ui,sans-serif" '
           f'font-size="42" font-weight="700" fill="#fff" opacity=".92">{t}</text></svg>')
    alvo = SAIDA / slug / "img" / f"ph{n:02d}.svg"
    alvo.parent.mkdir(parents=True, exist_ok=True)
    alvo.write_text(svg, encoding="utf-8")
    return f"img/ph{n:02d}.svg"


def preparar_imagens(slug: str, demo: dict, api_key: str) -> dict:
    """Baixa as fotos e devolve o mapa lock->caminho local que o template vai usar."""
    pasta = SAIDA / slug / "img"
    pasta.mkdir(parents=True, exist_ok=True)
    fotos = fotos_do_negocio(demo["busca"], api_key, quantas=len(demo["servicos"]))
    caminhos = []
    for i, dados in enumerate(fotos, 1):
        alvo = pasta / f"{i:02d}.jpg"
        alvo.write_bytes(dados)
        caminhos.append(f"img/{i:02d}.jpg")
    base = len(caminhos)   # fixa ANTES do loop: `caminhos` cresce a cada volta
    faltou = len(demo["servicos"]) - base
    for j in range(faltou):
        rot = demo["servicos"][base + j]["nome"]
        caminhos.append(_bloco_cor(slug, demo["cor"], demo["cor2"], rot, j + 1))
    return {"mapa": {i + 1: c for i, c in enumerate(caminhos)},
            "reais": len(fotos), "placeholders": faltou}


def render_com_tier(demo: dict, mapa: dict, tier: str) -> str:
    """Gera o HTML do template padrão, com imagem local e motion do tier.

    Troca `_card_img` em vez de editar gen_demo_motion: o template é compartilhado
    com os outros demos e não deve saber que existe Places. O fallback passa a ser
    a MESMA imagem — é o que impede o picsum aleatório de voltar.
    """
    original = motor._card_img
    motor._card_img = lambda keyword, lock, w=600, h=420: (mapa.get(lock, mapa[1]),
                                                           mapa.get(lock, mapa[1]))
    try:
        html = motor.render(demo)
    finally:
        motor._card_img = original

    nv = motion_alto.nivel(tier)
    css, js = motion_alto.css(nv), motion_alto.js(nv)
    extra = ""
    if css:
        extra += f"<style>{css}</style>"
    if js:
        extra += f"<script>{js}</script>"
    if extra:
        html = html.replace("</head>", extra + "</head>", 1)
    return html.replace("<html", f'<html data-tier="{tier}" data-motion="{nv}"', 1)


# ── os 11. `busca` é o que vai pro Places; erra o alvo se for só o nome.
NEGOCIOS = {}
NEGOCIOS.update({k: v for k, v in __import__("gen_demos_lins").DEMOS_LINS.items()})
NEGOCIOS["charles-cabeleireiros"].update(
    {"tier": "T1", "busca": "Charles Cabeleireiros, Lins, SP"})
NEGOCIOS["oligoflora"].update(
    {"tier": "T3", "busca": "OligoFlora Estética, Lins, SP"})
NEGOCIOS["vitor-canevaroli-advocacia"].update(
    {"tier": "T3", "busca": "Vitor Canevaroli Advocacia, Lins, SP"})

_CLUBE = lambda cidade: [
    {"nome": "Natação", "preco": "consulte o plano", "img": "swimming,pool",
     "desc": "Turmas por nível, da adaptação ao treino de equipe, com professor na borda o tempo todo."},
    {"nome": "Academia e Musculação", "preco": "incluso no plano", "img": "gym,weights",
     "desc": "Sala de musculação com orientação, ficha montada por avaliação e horário estendido."},
    {"nome": "Quadras e Tênis", "preco": "reserva pelo WhatsApp", "img": "tennis,court",
     "desc": "Reserva de quadra sem burocracia. Aula avulsa ou turma fixa, saibro e rápida."},
    {"nome": "Espaço para Eventos", "preco": "orçamento na hora", "img": "event,party,venue",
     "desc": f"Salão e área externa para casamento, formatura e confraternização em {cidade}."},
    {"nome": "Day Use", "preco": "a partir de R$ 40", "img": "pool,leisure,family",
     "desc": "Passe de um dia pra conhecer a estrutura com a família antes de virar sócio."},
    {"nome": "Plano de Sócio", "preco": "fale com a secretaria", "img": "club,members",
     "desc": "Mensalidade com acesso completo. Condição especial pra família e primeira adesão."},
]
_ASSESSORIA = lambda cidade: [
    {"nome": "Assessoria de Corrida", "preco": "a partir de R$ 180/mês", "img": "running,training",
     "desc": "Planilha individual, treino em grupo e acompanhamento de prova. Do primeiro 5k à maratona."},
    {"nome": "Avaliação Física", "preco": "a partir de R$ 120", "img": "fitness,assessment",
     "desc": "Composição corporal, teste de esforço e definição da zona de treino. Base do planejamento."},
    {"nome": "Treino Funcional", "preco": "consulte turmas", "img": "functional,training",
     "desc": "Força e mobilidade pra sustentar o volume de corrida sem lesão."},
    {"nome": "Personal Trainer", "preco": "a partir de R$ 90/sessão", "img": "personal,trainer",
     "desc": "Atendimento individual pra quem tem meta com data marcada ou está voltando de lesão."},
    {"nome": "Preparação para Prova", "preco": "pacote fechado", "img": "marathon,race",
     "desc": f"Ciclo completo até a prova alvo, com estratégia de ritmo e logística no dia."},
    {"nome": "Aula Experimental", "preco": "gratuita", "img": "running,group",
     "desc": f"Treine junto com o grupo em {cidade} antes de decidir. Sem compromisso."},
]

NOVOS = {
    "complexo-jose-maria": {
        "negocio": "Complexo de Esportes José Maria Pascoal", "tier": "T3",
        "busca": "Complexo de Esportes José Maria Pascoal, Ourinhos, SP",
        "cor": "#38bdf8", "cor2": "#0c4a6e",
        "tagline": "Esporte em Ourinhos · turmas e reservas pelo WhatsApp",
        "servicos": _ASSESSORIA("Ourinhos")},
    "aracatuba-clube": {
        "negocio": "Araçatuba Clube", "tier": "T3",
        "busca": "Araçatuba Clube, Araçatuba, SP",
        "cor": "#34d399", "cor2": "#064e3b",
        "tagline": "Clube em Araçatuba · sócio, day use e eventos",
        "servicos": _CLUBE("Araçatuba")},
    "vloz-sports": {
        "negocio": "VLOZ Sports", "tier": "T3",
        "busca": "VLOZ SPORTS uniformes esportivos, São José do Rio Preto, SP",
        "cor": "#f97316", "cor2": "#7c2d12",
        "tagline": "Uniformes esportivos sob medida · orçamento pelo WhatsApp",
        "servicos": [
            {"nome": "Uniforme de Time", "preco": "orçamento por lote", "img": "soccer,jersey",
             "desc": "Camisa, short e meião com o escudo do time. Sublimação total, numeração e nome."},
            {"nome": "Camisa de Corrida", "preco": "a partir de 20 peças", "img": "running,shirt",
             "desc": "Tecido leve com proteção UV pra assessoria e equipe de rua."},
            {"nome": "Abadá e Camiseta de Evento", "preco": "consulte o lote", "img": "event,tshirt",
             "desc": "Produção rápida pra evento com data marcada. Arte aprovada e prazo fechado."},
            {"nome": "Uniforme Empresarial", "preco": "orçamento", "img": "uniform,company",
             "desc": "Polo e camiseta com bordado ou sublimação pra equipe e confraternização."},
            {"nome": "Kit Atleta Personalizado", "preco": "monte o kit", "img": "sports,kit",
             "desc": "Camisa, sacochila e acessório no mesmo pacote, com a identidade da prova."},
            {"nome": "Arte e Mockup", "preco": "sem custo no fechamento", "img": "design,mockup",
             "desc": "Simulação do uniforme antes de produzir. Aprovou, entra na fila."}]},
    "crossfit-bauru": {
        "negocio": "CrossFit Bauru", "tier": "T3",
        "busca": "CrossFit Bauru, Bauru, SP",
        "cor": "#facc15", "cor2": "#1c1917",
        "tagline": "Box em Bauru · agende sua aula experimental",
        "servicos": [
            {"nome": "Aula Experimental", "preco": "gratuita", "img": "crossfit,box",
             "desc": "Primeira aula sem custo, adaptada pro seu nível. Venha ver como funciona."},
            {"nome": "CrossFit", "preco": "a partir de R$ 190/mês", "img": "crossfit,training",
             "desc": "Treino do dia escalável, com coach corrigindo movimento aula a aula."},
            {"nome": "Iniciante / On-Ramp", "preco": "incluso no plano", "img": "fitness,beginner",
             "desc": "Turma de entrada pra aprender os movimentos antes de cair no WOD."},
            {"nome": "Halterofilismo", "preco": "consulte turmas", "img": "weightlifting,barbell",
             "desc": "Técnica de arranco e arremesso com progressão de carga."},
            {"nome": "Condicionamento", "preco": "consulte", "img": "conditioning,fitness",
             "desc": "Sessões de resistência e cardio pra ganhar fôlego no treino e na vida."},
            {"nome": "Campeonato Interno", "preco": "inscrição por equipe", "img": "competition,fitness",
             "desc": "Competição da casa com kit de participante e premiação."}]},
    "yara-clube": {
        "negocio": "Yara Clube", "tier": "T4",
        "busca": "Yara Clube, Marília, SP",
        "cor": "#22d3ee", "cor2": "#083344",
        "tagline": "Tradição em Marília · sócio, esporte e eventos",
        "servicos": _CLUBE("Marília")},
    "tenis-clube-prudente": {
        "negocio": "Tênis Clube", "tier": "T4",
        "busca": "Tênis Clube, Presidente Prudente, SP",
        "cor": "#a78bfa", "cor2": "#2e1065",
        "tagline": "Clube em Presidente Prudente · estrutura completa pra família",
        "servicos": _CLUBE("Presidente Prudente")},
    "thiago-vianna": {
        "negocio": "Centro de Treinamento Thiago Vianna", "tier": "T4",
        "busca": "Centro de Treinamento Thiago Vianna, Bauru, SP",
        "cor": "#fb7185", "cor2": "#4c0519",
        "tagline": "Treinamento em Bauru · avaliação e planilha individual",
        "servicos": _ASSESSORIA("Bauru")},
    "forca-total-esportes": {
        "negocio": "Força Total Esportes", "tier": "T4",
        "busca": "Força Total Esportes, Araçatuba, SP",
        "cor": "#4ade80", "cor2": "#14532d",
        "tagline": "Assessoria esportiva em Araçatuba · treino com acompanhamento",
        "servicos": _ASSESSORIA("Araçatuba")},
}
NEGOCIOS.update(NOVOS)


# Modelos de serviço reaproveitáveis — é o que permite criar demo pelo painel sem
# escrever copy do zero. Copy boa é o que demora; a estrutura não muda por cliente.
_IMOBILIARIA = lambda cidade: [
    {"nome": "Imóveis de Alto Padrão", "preco": "carteira exclusiva", "img": "luxury,house,interior",
     "desc": f"Casas e apartamentos selecionados em {cidade}, com visita agendada e acompanhamento do início ao fim."},
    {"nome": "Lançamentos", "preco": "condição de tabela", "img": "modern,building,architecture",
     "desc": "Acesso a unidades na planta antes do mercado, com simulação de financiamento na hora."},
    {"nome": "Locação", "preco": "consulte disponibilidade", "img": "apartment,living,room",
     "desc": "Contrato com garantia sem fiador e vistoria documentada. Chave na mão em poucos dias."},
    {"nome": "Avaliação do seu Imóvel", "preco": "gratuita", "img": "house,keys,evaluation",
     "desc": "Quanto vale hoje, com base em negócios fechados na região — não em chute de portal."},
    {"nome": "Venda com Exclusividade", "preco": "comissão combinada", "img": "real,estate,sale",
     "desc": "Fotos profissionais, anúncio em todos os portais e filtro de curioso antes da visita."},
    {"nome": "Falar com um Corretor", "preco": "agora pelo WhatsApp", "img": "realtor,consultation",
     "desc": "Diga o bairro e a faixa de preço; a gente manda as opções que realmente cabem."},
]

MODELOS = {
    "imobiliaria": {"cor": "#c9a227", "cor2": "#111827",
                    "tagline": "Imóveis em {cidade} · fale com um corretor pelo WhatsApp",
                    "servicos": _IMOBILIARIA},
    "clube": {"cor": "#22d3ee", "cor2": "#083344",
              "tagline": "Clube em {cidade} · sócio, esporte e eventos",
              "servicos": _CLUBE},
    "assessoria": {"cor": "#4ade80", "cor2": "#14532d",
                   "tagline": "Assessoria esportiva em {cidade} · treino com acompanhamento",
                   "servicos": _ASSESSORIA},
    "box": {"cor": "#facc15", "cor2": "#1c1917",
            "tagline": "Box em {cidade} · agende sua aula experimental",
            "servicos": lambda cidade: NOVOS["crossfit-bauru"]["servicos"]},
    "uniformes": {"cor": "#f97316", "cor2": "#7c2d12",
                  "tagline": "Uniformes sob medida em {cidade} · orçamento pelo WhatsApp",
                  "servicos": lambda cidade: NOVOS["vloz-sports"]["servicos"]},
    "barbearia": {"cor": "#f5c518", "cor2": "#1a1a1a",
                  "tagline": "Barbearia em {cidade} · agende pelo WhatsApp",
                  "servicos": lambda cidade: NEGOCIOS["charles-cabeleireiros"]["servicos"]},
    "estetica": {"cor": "#a3e635", "cor2": "#14532d",
                 "tagline": "Estética em {cidade} · avaliação pelo WhatsApp",
                 "servicos": lambda cidade: NEGOCIOS["oligoflora"]["servicos"]},
    "advocacia": {"cor": "#c9a227", "cor2": "#0f2740",
                  "tagline": "Advocacia em {cidade} · atendimento pelo WhatsApp",
                  "servicos": lambda cidade: NEGOCIOS["vitor-canevaroli-advocacia"]["servicos"]},
}


def gerar(slugs: list[str] | None = None) -> dict:
    api_key = _chave()
    relatorio = {}
    for slug in (slugs or list(NEGOCIOS)):
        d = NEGOCIOS[slug]
        img = preparar_imagens(slug, d, api_key)
        html = render_com_tier(d, img["mapa"], d["tier"])
        alvo = SAIDA / slug
        alvo.mkdir(parents=True, exist_ok=True)
        (alvo / "index.html").write_text(html, encoding="utf-8")
        relatorio[slug] = {"tier": d["tier"], "motion": motion_alto.nivel(d["tier"]),
                           "fotos_reais": img["reais"], "placeholders": img["placeholders"],
                           "url": f"https://p.jpos.com.br/{slug}/",
                           "ok": img["reais"] >= MIN_FOTOS}
        print(f"{slug:30s} {d['tier']}  motion={motion_alto.nivel(d['tier']):8s} "
              f"fotos={img['reais']}  placeholder={img['placeholders']}")
    return relatorio


if __name__ == "__main__":
    if "--selfcheck" in sys.argv:
        assert motion_alto.nivel("T1") == "nenhum", "T1 não pode receber motion"
        assert motion_alto.nivel("T3") == "completo" and motion_alto.nivel("T4") == "completo"
        assert motion_alto.css("nenhum") == "" and motion_alto.js("nenhum") == ""
        assert NEGOCIOS["charles-cabeleireiros"]["tier"] == "T1"
        assert len(NEGOCIOS) == 11, len(NEGOCIOS)
        for m, cfg in MODELOS.items():   # todo modelo tem de render 6 serviços
            sv = cfg["servicos"]("Lins")
            assert len(sv) == 6 and all(x.get("desc") for x in sv), m
            assert "{cidade}" in cfg["tagline"], m
        for s, d in NEGOCIOS.items():
            assert d.get("busca") and d.get("tier"), s
            assert len(d["servicos"]) == 6, s
        # o fallback aleatório do template não pode sobreviver à troca
        mapa = {i: f"img/{i:02d}.jpg" for i in range(1, 7)}
        h = render_com_tier(NEGOCIOS["charles-cabeleireiros"], mapa, "T1")
        assert "loremflickr" not in h and "picsum" not in h, "fallback aleatório voltou"
        assert 'data-tier="T1"' in h and 'data-motion="nenhum"' in h
        h3 = render_com_tier(NEGOCIOS["oligoflora"], mapa, "T3")
        assert 'data-motion="completo"' in h3 and len(h3) > len(h), "T3 devia carregar motion"

        # preparar_imagens sem rede: o caso "Places devolveu MENOS foto que serviço"
        # é o caminho normal, e foi onde um índice fora de lugar quebrou a geração.
        import gen_demos_venda as eu
        real = eu.fotos_do_negocio
        for n_fotos in (0, 2, 6):
            eu.fotos_do_negocio = lambda *a, n=n_fotos, **k: [b"x" * 9000] * n
            r = eu.preparar_imagens("_selfcheck", NEGOCIOS["oligoflora"], "k")
            assert len(r["mapa"]) == 6, (n_fotos, r)
            assert r["reais"] == n_fotos and r["placeholders"] == 6 - n_fotos
        eu.fotos_do_negocio = real
        print("OK — self-check dos demos passou.")
    else:
        print(json.dumps(gerar(sys.argv[1:] or None), ensure_ascii=False, indent=2))
