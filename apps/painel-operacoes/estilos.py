"""Biblioteca de ESTILOS visuais (morfismos) do motor de sites.

Dois níveis, separados de propósito — o barato entrega hoje, o caro é roadmap:

  1. ESTILO (aqui): camada de SUPERFÍCIE. Sombra, borda, blur, profundidade,
     tipografia dos containers. Aplica como CSS overlay sobre o HTML já gerado —
     troca o "sabor" visual sem tocar no motor nem no esqueleto da página.
  2. CONCEITO (CONCEITOS, só dados): camada de ESTRUTURA (scroll cinematográfico,
     terminal CLI, grid infinito, configurador). Muda o esqueleto = template novo.
     NÃO sai de overlay; fica catalogado por segmento/tier pra virar build depois.

Por que overlay e não tema no engine: o motor-site já tem tokens/tema por segmento
(design.py). Isto é a camada de ACABAMENTO por cima, trocável em 1 clique enquanto o
JP ajusta a demo. Se um estilo virar padrão de um segmento, aí sim desce pro engine.

ponytail: dict puro + função pura (recebe nome, devolve CSS). Sem classe, sem registry.
"""
from __future__ import annotations

# Cada estilo: (rótulo, descrição curta pro operador, CSS overlay)
# O CSS mira containers genéricos que o motor gera (section/card/button/hero) e é
# escrito pra degradar: se o seletor não existir na página, nada quebra.
_BASE_ALVOS = "section, .card, .servico, .plano, .depoimento, article, .box, .jpos-grid figure"

ESTILOS: dict[str, dict] = {
    "": {"rotulo": "Padrão do motor", "desc": "sem overlay — tema do segmento como está", "css": ""},

    "glassmorphism": {
        "rotulo": "Glassmorphism",
        "desc": "vidro fosco translúcido, blur no fundo, borda luminosa",
        "css": f"""
{_BASE_ALVOS}{{background:rgba(255,255,255,.10)!important;backdrop-filter:blur(16px) saturate(140%);
  -webkit-backdrop-filter:blur(16px) saturate(140%);border:1px solid rgba(255,255,255,.22)!important;
  border-radius:18px!important;box-shadow:0 8px 32px rgba(0,0,0,.18)!important}}
button, .cta, .btn, a.botao{{backdrop-filter:blur(10px);-webkit-backdrop-filter:blur(10px);
  border:1px solid rgba(255,255,255,.3)!important;border-radius:999px!important}}
""",
    },
    "neumorphism": {
        "rotulo": "Neumorphism",
        "desc": "relevo suave monocromático, sombra dupla (extrudado do fundo)",
        "css": f"""
body{{background:#e8ecf2!important;color:#31435c!important}}
{_BASE_ALVOS}{{background:#e8ecf2!important;border:0!important;border-radius:22px!important;
  box-shadow:9px 9px 20px #c5ccd6, -9px -9px 20px #ffffff!important}}
button, .cta, .btn, a.botao{{background:#e8ecf2!important;color:#31435c!important;border:0!important;
  border-radius:16px!important;box-shadow:6px 6px 14px #c5ccd6, -6px -6px 14px #fff!important}}
button:active, .cta:active{{box-shadow:inset 5px 5px 12px #c5ccd6, inset -5px -5px 12px #fff!important}}
""",
    },
    "claymorphism": {
        "rotulo": "Claymorphism",
        "desc": "massinha 3D: cantos gordos, sombra interna, cores doces",
        "css": f"""
{_BASE_ALVOS}{{border-radius:32px!important;border:0!important;
  box-shadow:0 18px 38px rgba(80,70,180,.18), inset 0 -8px 16px rgba(0,0,0,.06),
             inset 0 8px 16px rgba(255,255,255,.75)!important}}
button, .cta, .btn, a.botao{{border-radius:999px!important;border:0!important;
  box-shadow:0 10px 20px rgba(80,70,180,.22), inset 0 -5px 10px rgba(0,0,0,.08),
             inset 0 5px 10px rgba(255,255,255,.6)!important}}
""",
    },
    "brutalism": {
        "rotulo": "Brutalism",
        "desc": "sem curva, borda preta grossa, sombra dura, tipografia crua",
        "css": f"""
body{{font-family:"Courier New",ui-monospace,monospace!important}}
{_BASE_ALVOS}{{border:3px solid #000!important;border-radius:0!important;
  box-shadow:8px 8px 0 #000!important;background:#fff!important;color:#000!important}}
h1,h2,h3{{text-transform:uppercase!important;letter-spacing:-.02em!important;font-weight:900!important}}
button, .cta, .btn, a.botao{{border:3px solid #000!important;border-radius:0!important;
  box-shadow:5px 5px 0 #000!important;text-transform:uppercase;font-weight:800}}
button:active,.cta:active{{transform:translate(4px,4px);box-shadow:1px 1px 0 #000!important}}
""",
    },
    "skeuomorphism": {
        "rotulo": "Skeuomorphism",
        "desc": "imita material real: gradiente, brilho, textura, borda esculpida",
        "css": f"""
{_BASE_ALVOS}{{background:linear-gradient(180deg,#fdfdfd,#dfe4ea)!important;
  border:1px solid #b6bec9!important;border-radius:12px!important;
  box-shadow:0 2px 3px rgba(0,0,0,.22), inset 0 1px 0 rgba(255,255,255,.95)!important}}
button, .cta, .btn, a.botao{{background:linear-gradient(180deg,#fefefe,#ccd3dc)!important;
  border:1px solid #97a1ad!important;border-radius:9px!important;color:#25303f!important;
  text-shadow:0 1px 0 rgba(255,255,255,.8);
  box-shadow:0 2px 4px rgba(0,0,0,.28), inset 0 1px 0 rgba(255,255,255,.9)!important}}
""",
    },
    "liquid-glass": {
        "rotulo": "Liquid Glass",
        "desc": "vidro líquido: blur forte + realce especular + brilho de borda",
        "css": f"""
{_BASE_ALVOS}{{position:relative;background:rgba(255,255,255,.12)!important;
  backdrop-filter:blur(26px) saturate(180%);-webkit-backdrop-filter:blur(26px) saturate(180%);
  border:1px solid rgba(255,255,255,.28)!important;border-radius:26px!important;overflow:hidden;
  box-shadow:0 10px 40px rgba(0,0,0,.22), inset 0 1px 1px rgba(255,255,255,.55)!important}}
{_BASE_ALVOS.split(',')[0]}::before{{content:"";position:absolute;inset:0 0 auto 0;height:45%;
  background:linear-gradient(180deg,rgba(255,255,255,.30),transparent);pointer-events:none}}
button, .cta, .btn, a.botao{{backdrop-filter:blur(18px);-webkit-backdrop-filter:blur(18px);
  border-radius:999px!important;border:1px solid rgba(255,255,255,.4)!important;
  box-shadow:inset 0 1px 1px rgba(255,255,255,.6), 0 6px 20px rgba(0,0,0,.18)!important}}
""",
    },
    "spatial": {
        "rotulo": "Spatial UI",
        "desc": "camadas com profundidade real, perspectiva e elevação (visionOS)",
        "css": f"""
body{{perspective:1400px}}
{_BASE_ALVOS}{{transform-style:preserve-3d;border-radius:24px!important;
  border:1px solid rgba(255,255,255,.18)!important;background:rgba(255,255,255,.08)!important;
  backdrop-filter:blur(20px);-webkit-backdrop-filter:blur(20px);
  box-shadow:0 30px 60px -18px rgba(0,0,0,.45), 0 2px 6px rgba(0,0,0,.14)!important;
  transition:transform .45s cubic-bezier(.16,1,.3,1), box-shadow .45s}}
{_BASE_ALVOS.split(',')[1] if ',' in _BASE_ALVOS else 'section'}:hover{{
  transform:translateZ(28px) translateY(-6px);
  box-shadow:0 44px 80px -20px rgba(0,0,0,.5)!important}}
@media (prefers-reduced-motion:reduce){{{_BASE_ALVOS}{{transition:none}}}}
""",
    },
    "minimal": {
        "rotulo": "Minimalismo radical",
        "desc": "tudo respira: sem sombra, sem borda, tipografia é o design",
        "css": f"""
{_BASE_ALVOS}{{background:transparent!important;border:0!important;box-shadow:none!important;
  border-radius:0!important;padding-top:12px;padding-bottom:12px}}
body{{letter-spacing:-.01em}}
h1{{font-size:clamp(2.4rem,7vw,5rem)!important;font-weight:300!important;letter-spacing:-.04em!important;
  line-height:1.02!important}}
h2{{font-weight:400!important;letter-spacing:-.02em!important}}
section{{padding-top:9vh!important;padding-bottom:9vh!important}}
button, .cta, .btn, a.botao{{border:1px solid currentColor!important;background:transparent!important;
  border-radius:0!important;box-shadow:none!important;font-weight:400!important;letter-spacing:.08em;
  text-transform:uppercase;font-size:.8rem!important}}
""",
    },
    "maximal": {
        "rotulo": "Maximalismo",
        "desc": "cor saturada, contraste alto, tipografia enorme, nada tímido",
        "css": f"""
{_BASE_ALVOS}{{border:4px solid currentColor!important;border-radius:20px!important;
  box-shadow:0 0 0 4px #000, 12px 12px 0 rgba(0,0,0,.85)!important}}
h1{{font-size:clamp(2.8rem,9vw,6.5rem)!important;font-weight:900!important;line-height:.92!important;
  letter-spacing:-.045em!important}}
h2{{font-size:clamp(1.7rem,4.5vw,3rem)!important;font-weight:900!important}}
button, .cta, .btn, a.botao{{font-weight:900!important;text-transform:uppercase;letter-spacing:.02em;
  border:4px solid #000!important;border-radius:999px!important;box-shadow:7px 7px 0 #000!important;
  font-size:1.05rem!important}}
""",
    },
    "cinetico": {
        "rotulo": "Cinético (scroll)",
        "desc": "a seção se revela conforme a página rola — motion como acento, não como camada",
        # POR QUE ESTE CSS NÃO DECLARA NENHUM @keyframes: os três nomes usados aqui
        # (cortina, card-fundo, thumb-zoom) já são emitidos por TODO site do motor, dentro
        # de @supports (animation-timeline: view()) + @media (prefers-reduced-motion:
        # no-preference) — ver design.css_motion_scroll. Referenciar em vez de redeclarar dá
        # de graça as duas travas que mais se esquece: navegador sem scroll-timeline e
        # visitante com reduced-motion simplesmente não têm as keyframes, o animation-name
        # fica órfão e o bloco renderiza estático, sem um byte de JS.
        # E nada de @ aqui dentro é obrigatório, não estético: css(escopo=...) descarta
        # regras @ ao escopar um acento numa seção — um @media aqui sumiria calado.
        "css": """
section{animation:cortina linear both;animation-timeline:view();animation-range:entry 4% cover 44%}
.card, article, .faq-item, .sv-card, .preco-card, .cat-card{animation:card-fundo linear both;
  animation-timeline:view();animation-range:entry 2% cover 30%}
img{animation:thumb-zoom linear both;animation-timeline:view()}
""",
    },
}


# CONCEITOS estruturais (camada 2): catálogo por segmento. NÃO são aplicáveis via
# overlay — cada um é template/esqueleto novo. Aqui vive a fila priorizada de build.
CONCEITOS: dict[str, list[str]] = {
    "academia": [
        "contador de resultados da comunidade (kg perdidos, PRs)",
        "aula experimental grátis como CTA único, sem menu distraindo",
        "vídeo de treino real em loop no fundo do hero",
        "grade de horários como seção viva (o que rola agora)",
    ],
    "clinica": [
        "agenda com vagas reais no hero (urgência honesta)",
        "depoimento em vídeo como hero, não banner",
        "tour 360º do consultório antes de marcar",
        "timeline 'sua jornada de tratamento' no lugar de lista de serviços",
    ],
    "imobiliaria": [
        "mapa interativo como homepage",
        "busca por estilo de vida (perto de parque, silencioso)",
        "comparador lado a lado de até 3 imóveis",
        "simulador de financiamento no card do imóvel",
    ],
    "advocacia": [
        "diagnóstico grátis como formulário conversacional (1 pergunta por vez)",
        "calculadora como isca principal (rescisão, imposto)",
        "linha do tempo de casos resolvidos (números, sem nomes)",
    ],
    "restaurante": [
        "cardápio como hero visual, scroll = prato a prato",
        "pedido via WhatsApp com prévia do carrinho",
        "tema que muda por horário (café/almoço/jantar)",
    ],
    "ecommerce": [
        "vitrine editorial (produto em cena, não fundo branco)",
        "configurador visual com preview instantâneo",
        "IA nativa que sugere por conversa, não por filtro",
    ],
    "_transversal": [
        "densidade adaptativa por tier (T1 enxuto -> T4 completo)",
        "geração condicional: tem foto real -> hero fotográfico; não tem -> ilustrativo",
        "slots de prova social preenchidos por reviews do Google",
        "CTA com verbo por estágio do funil (T1 'peça seu site' -> T4 'fale com a Noemi')",
        "micro-copy por segmento (advocacia formal, pet descontraído)",
    ],
}


# ── COMPOSIÇÃO: o motor escolhe VÁRIOS morfismos e diz por quê ───────────────────
#
# Morfismo não é enfeite: cada um comunica uma coisa. O motor veste a página com um
# `principal` e troca o morfismo em seções específicas (`acentos`) onde outro comunica
# melhor — preço em brutalismo grita a oferta dentro de um site minimal.
#
# ISTO NÃO É UM SELETOR. O operador não escolhe 1 de 9: o motor compõe e REGISTRA a
# justificativa de cada decisão. A lista de 9 é vocabulário, não menu.
#
# Duas travas, porque a versão anterior compunha no papel e não na tela:
#   (1) ALVO TEM QUE EXISTIR. 4 dos 7 perfis miravam `preco`/`antes-depois`, seções que
#       o motor nunca emitiu — o CSS saía como `section.preco{...}` e não casava com
#       nada. A ficha dizia "spatial + brutalism em preço" e o site saía só spatial.
#   (2) ACENTO TEM QUE APARECER. O perfil da clínica pedia vidro sobre neumorfismo;
#       neumorfismo chapa o body em #e8ecf2 e o vidro é branco a 10% — a diferença dá
#       2/2/1 por canal, invisível, e `backdrop-filter` não tem textura pra borrar.
#
# Empilhar mais estilos sem essas duas travas multiplicaria acento fantasma.

# Seções que o motor REALMENTE emite. Medido no HTML publicado (varredura de
# <section class="..."> em /var/www/sites, 2026-08-12). Se o motor ganhar seção nova,
# ela entra aqui e o teste de alvo passa a aceitá-la.
SECOES_EMITIDAS = {"servicos", "faq", "lead", "cta-final", "depo", "calc", "jpos-galeria"}
# Frequência medida em 71 sites publicados (2026-08-12): nenhuma seção é universal,
# mas há duas ligas. As FREQUENTES aparecem na maioria; `depo` saiu em 18% dos sites e
# `calc` em 4% — dependem do cliente ter depoimento ou do segmento ter calculadora.
# O preview do Studio precisa dizer isso: prometer um acento que só entra em 4% dos
# casos é o preview mentindo, e preview que mente é pior que preview nenhum.
SECOES_FREQUENTES = {"servicos", "faq", "lead", "cta-final"}

# Derivado do CSS de cada estilo, não de gosto:
#   CHAPA_FUNDO     — escreve body{background:...}, apagando o que estiver por baixo.
#   PRECISA_TEXTURA — usa backdrop-filter/rgba translúcido: só aparece se houver
#                     textura atrás pra borrar. Sobre fundo chapado, some.
CHAPA_FUNDO = {"neumorphism"}
PRECISA_TEXTURA = {"glassmorphism", "liquid-glass", "spatial"}

# Densidade visual. Acento com o MESMO peso do principal não acentua nada — é troca
# lateral que o visitante não percebe e o operador não sabe explicar.
PESO = {"minimal": 0, "spatial": 1, "glassmorphism": 1, "neumorphism": 1,
        "claymorphism": 2, "skeuomorphism": 2, "liquid-glass": 2, "cinetico": 2,
        "brutalism": 3, "maximal": 3}

# O que cada morfismo COMUNICA. É daqui que sai a justificativa que vai pra ficha —
# e que o JP repete pro dono quando ele pergunta "por que meu site é assim?".
COMUNICA = {
    "glassmorphism": "tecnologia e leveza, sem parecer frio",
    "neumorphism":   "cuidado e suavidade, toque físico",
    "claymorphism":  "acolhimento, informal e amigável",
    "brutalism":     "urgência e preço — grita sem pedir licença",
    "skeuomorphism": "tradição e solidez, textura de documento",
    "liquid-glass":  "produto premium, superfície viva",
    "spatial":       "profundidade e modernidade",
    "minimal":       "autoridade e sofisticação pelo espaço vazio",
    "maximal":       "fartura e energia, muita coisa acontecendo",
    "cinetico":      "cuidado de produção — a página responde a quem rola",
}


def compativel(principal: str, acento: str) -> tuple[bool, str]:
    """(pode, motivo). Motivo preenchido só quando NÃO pode — vira log e teste."""
    principal, acento = (principal or "").strip(), (acento or "").strip()
    if not acento or acento not in ESTILOS:
        return False, f"morfismo {acento!r} não existe"
    if acento == principal:
        return False, "acento igual ao principal não acentua nada"
    if principal in CHAPA_FUNDO and acento in PRECISA_TEXTURA:
        return False, (f"{acento} depende de translucidez e {principal} chapa o fundo — "
                       f"o acento ficaria invisível")
    if abs(PESO.get(acento, 1) - PESO.get(principal, 1)) < 1:
        return False, f"{acento} tem o mesmo peso visual de {principal} — troca lateral"
    return True, ""


# Cada acento mira uma seção QUE EXISTE e carrega o porquê comercial, não estético.
#
# `principais` é LISTA porque "Gerar outro" precisa ter poder real: girando só a ordem
# dos acentos, o mesmo candidato era descartado nas duas rodadas e o botão devolvia a
# MESMA página. Um botão que não muda nada envenena a memória — o operador clica de
# novo achando que rejeitou algo diferente, e o sistema conta duas rejeições da mesma
# composição que ele nunca viu variar.
# São ALTERNATIVAS DEFENSÁVEIS do segmento, nunca os 9 em sorteio: as duas comunicam
# a mesma coisa por caminhos diferentes.
PERFIS: dict[str, dict] = {
    "academia": {
        "principais": [
            ("spatial", "academia vende transformação — profundidade dá a sensação de progresso"),
            ("maximal", "a outra leitura da mesma promessa: energia e movimento em excesso"),
        ],
        "acentos": [
            {"secao": "cta-final", "estilo": "brutalism",
             "porque": "a matrícula é a única coisa que precisa gritar num site leve"},
            {"secao": "servicos", "estilo": "claymorphism",
             "porque": "modalidade é escolha pessoal — cards com corpo convidam a tocar"},
            {"secao": "servicos", "estilo": "cinetico",
             "porque": "treino é movimento — a grade se revela conforme o visitante rola"},
        ],
    },
    "clinica": {
        "principais": [
            ("neumorphism", "paciente decide por confiança; relevo suave passa cuidado, não venda"),
            ("minimal", "a leitura clínica da mesma confiança: limpeza e espaço, sem ruído"),
        ],
        "acentos": [
            {"secao": "faq", "estilo": "skeuomorphism",
             "porque": "dúvida sobre procedimento pede textura de documento, não de app"},
            {"secao": "depo", "estilo": "claymorphism",
             "porque": "depoimento é a parte humana — merece o bloco mais macio da página"},
        ],
    },
    "salao": {
        "principais": [
            ("claymorphism", "beleza é prazer, não protocolo — formas gordas e cores doces"),
            ("maximal", "a versão festiva: cor e fartura como promessa de transformação"),
        ],
        "acentos": [
            {"secao": "servicos", "estilo": "glassmorphism",
             "porque": "a vitrine de serviços fica sobre foto: vidro deixa a imagem trabalhar"},
            {"secao": "lead", "estilo": "minimal",
             "porque": "no meio do colorido, o agendamento precisa ser o lugar calmo"},
        ],
    },
    "imobiliaria": {
        "principais": [
            ("minimal", "imóvel caro se vende com espaço vazio; enfeite parece corretor afobado"),
            ("glassmorphism", "a mesma sobriedade com a foto do imóvel mandando na tela"),
        ],
        "acentos": [
            {"secao": "servicos", "estilo": "claymorphism",
             "porque": "card de imóvel ganha corpo e convida ao toque na listagem"},
            {"secao": "cta-final", "estilo": "brutalism",
             "porque": "agendar visita é o único momento de pressa do site"},
            {"secao": "servicos", "estilo": "cinetico",
             "porque": "imóvel se vende pela foto: revelar cada uma no scroll segura o olho"},
        ],
    },
    "advocacia": {
        "principais": [
            ("minimal", "cliente procura autoridade; sobriedade é o argumento visual"),
            ("skeuomorphism", "a autoridade pela tradição: textura de papel e peso de documento"),
        ],
        "acentos": [
            {"secao": "faq", "estilo": "skeuomorphism",
             "porque": "dúvida jurídica lida como papel pesa mais que dúvida lida como app"},
            {"secao": "cta-final", "estilo": "brutalism",
             "porque": "procurar advogado é decisão adiada — o contato precisa parar o scroll"},
            {"secao": "calc", "estilo": "brutalism",
             "porque": "a calculadora é a isca: número grande e borda dura param o scroll"},
        ],
    },
    "restaurante": {
        "principais": [
            ("maximal", "comida entra pelos olhos — abundância visual é o próprio produto"),
            ("claymorphism", "a leitura afetiva: comida de casa, informal e acolhedora"),
        ],
        "acentos": [
            {"secao": "servicos", "estilo": "glassmorphism",
             "porque": "o prato é a estrela: o card precisa desaparecer sobre a foto"},
            {"secao": "lead", "estilo": "minimal",
             "porque": "reservar mesa no meio do excesso só funciona se o formulário respirar"},
        ],
    },
    "ecommerce": {
        "principais": [
            ("liquid-glass", "loja online compete por desejo — superfície viva parece produto novo"),
            ("spatial", "o mesmo desejo por profundidade: o produto flutuando à frente"),
        ],
        "acentos": [
            {"secao": "cta-final", "estilo": "brutalism",
             "porque": "comprar é decisão de segundos: o botão não pode ser elegante demais"},
            {"secao": "servicos", "estilo": "minimal",
             "porque": "a vitrine precisa de silêncio em volta pro produto aparecer"},
            {"secao": "servicos", "estilo": "cinetico",
             "porque": "loja online compete por desejo — produto que entra em cena vende mais que produto parado"},
        ],
    },
}

# Tier ajusta a AMBIÇÃO visual: T1 é isca (tem que carregar rápido e ser óbvio);
# T4 é apresentação com a Noemi junto (pode ousar). Motor único, densidade por tier.
_TIER_PRINCIPAL = {"T1": "minimal", "T2": ""}  # '' = usa o do segmento
# Quantos acentos por tier. Não é limite técnico, é limite de LEITURA: três morfismos
# distintos numa página já é o teto do que alguém consegue processar como intenção em
# vez de bagunça. T1 é isca e não paga elaboração.
_TIER_ACENTOS = {"T1": 0, "T2": 1, "T3": 2, "T4": 2}


def _ascii(t: str) -> str:
    import unicodedata
    t = unicodedata.normalize("NFKD", (t or "").strip().lower())
    return t.encode("ascii", "ignore").decode()


def escolher(segmento: str, tier: str = "", semente: int = 0,
             evitar: list[str] | None = None) -> dict:
    """Composição automática: principal + N acentos, cada decisão justificada.

    Devolve `acento` ({secao: morfismo}) por compatibilidade com quem já consumia, e
    `decisoes` — a lista estruturada [{alvo, estilo, comunica, porque}] que vira ficha,
    painel e resposta pro dono quando ele pergunta por que o site ficou assim.

    `semente` (id do lead) gira quais acentos entram, sem trocar o principal: variedade
    entre clientes do mesmo nicho sem virar loteria — a cara do segmento permanece.

    `evitar` = composições que este operador já rejeitou (ver memoria_estilo). Não é
    proibição: se sobrar nada, a decisão volta a valer e o motivo fica registrado.
    """
    seg = _ascii(segmento)
    chave_perfil = next((k for k in PERFIS if k in seg), "")
    if not chave_perfil:
        # SEGUNDA PASSADA pelo vocabulário: "podólogo" não contém "clinica", mas é
        # clínica. Sem isto o painel exibia "perfil: clinica" (que lê o vocabulário)
        # ao lado de uma composição VAZIA (que não lia) — a tela afirmando um perfil
        # que o motor não estava usando. Uma UI que mente é pior que uma UI que
        # admite não saber.
        try:
            import vocabulario
            fam = vocabulario.segmento_do_nicho(segmento)
            chave_perfil = fam if fam in PERFIS else ""
        except Exception:  # noqa: BLE001 — vocabulário enriquece, não é crítico
            chave_perfil = ""
    perfil = PERFIS.get(chave_perfil) or {"principais": [], "acentos": []}
    t = (tier or "").strip().upper()

    opcoes = perfil["principais"]
    # a semente escolhe ENTRE AS ALTERNATIVAS DO SEGMENTO — nunca entre os 9. É o que
    # dá poder real ao "Gerar outro" sem transformar a identidade do nicho em loteria.
    base, porque_base = opcoes[semente % len(opcoes)] if opcoes else ("", "")
    forcado = _TIER_PRINCIPAL.get(t, "")     # '' = tier não força nada
    principal = forcado or base
    porque_principal = (
        "T1 é isca: precisa carregar rápido e ser óbvio na primeira olhada"
        if forcado and forcado != base else porque_base)

    decisoes = []
    if principal:
        decisoes.append({"alvo": "página", "estilo": principal,
                         "comunica": COMUNICA.get(principal, ""), "porque": porque_principal})

    teto = _TIER_ACENTOS.get(t, 1)
    candidatos = list(perfil["acentos"])
    # a semente gira a ORDEM, não sorteia: dois leads do mesmo nicho recebem acentos
    # diferentes, e o mesmo lead recebe sempre o mesmo (regerar tem que ser estável)
    if candidatos:
        giro = semente % len(candidatos)
        candidatos = candidatos[giro:] + candidatos[:giro]

    aptos: list[dict] = []          # compatíveis, na ordem de preferência
    recusados = []
    for c in candidatos:
        if c["secao"] not in SECOES_EMITIDAS:
            recusados.append(f"{c['estilo']} em {c['secao']}: seção não existe no HTML gerado")
            continue
        ok, motivo = compativel(principal, c["estilo"])
        if not ok:
            recusados.append(f"{c['estilo']} em {c['secao']}: {motivo}")
            continue
        if evitar and f"{c['secao']}:{c['estilo']}" in evitar:
            recusados.append(f"{c['estilo']} em {c['secao']}: rejeitado antes pelo operador")
            continue
        aptos.append({"alvo": c["secao"], "estilo": c["estilo"],
                      "comunica": COMUNICA.get(c["estilo"], ""), "porque": c["porque"],
                      "condicional": c["secao"] not in SECOES_FREQUENTES})

    # `acento` já vem selecionado pra quem consome sem HTML em mãos (preview do Studio).
    # Quem TEM o HTML deve chamar compor(), que seleciona sobre o que aparece de fato.
    escolhidos, _ = _selecionar(aptos, teto)
    decisoes += escolhidos
    return {"principal": principal,
            "acento": {d["alvo"]: d["estilo"] for d in escolhidos},
            "candidatos": aptos, "teto": teto,
            "decisoes": decisoes, "recusados": recusados,
            "porque": _resumo(decisoes)}


def _selecionar(candidatos: list[dict], teto: int,
                presentes: set[str] | None = None) -> tuple[list[dict], list[str]]:
    """Os acentos que de fato entram. (escolhidos, motivos dos que ficaram de fora).

    TODA regra que descarta roda AQUI, no mesmo lugar, depois de saber o que existe na
    página. Aplicar qualquer uma antes custou caro duas vezes: o teto gastava vaga com
    seção ausente, e a dedup de morfismo barrava `brutalism` no cta-final por causa de
    um `brutalism` no `calc` que depois era descartado — sobrava nenhum brutalism e a
    vaga se perdia num candidato que nunca apareceu na tela.
    """
    escolhidos: list[dict] = []
    fora: list[str] = []
    for c in candidatos:
        if presentes is not None and c["alvo"] not in presentes:
            fora.append(f"{c['estilo']} em {c['alvo']}: a seção não existe nesta página")
            continue
        if len(escolhidos) >= teto:
            fora.append(f"{c['estilo']} em {c['alvo']}: teto de acentos do tier já cheio")
            continue
        # o MESMO morfismo em dois alvos é repetição, não composição: o visitante não
        # lê dois blocos brutalistas como "duas ênfases", lê como "o site é assim".
        if any(e["estilo"] == c["estilo"] for e in escolhidos):
            fora.append(f"{c['estilo']} em {c['alvo']}: já usado em outra seção — "
                        f"repetir não acentua")
            continue
        escolhidos.append(dict(c))
    return escolhidos, fora


def _resumo(decisoes: list[dict]) -> str:
    return " + ".join(
        f"{d['estilo']} na página" if d["alvo"] == "página" else f"{d['estilo']} em {d['alvo']}"
        for d in decisoes) or "tema do motor"


def compor(escolha: dict, html: str) -> dict:
    """A composição FINAL desta página: só o que existe nela, teto aplicado depois.

    O teto por tier é de LEITURA, não técnico — três morfismos é o máximo que alguém
    processa como intenção. Aplicá-lo antes de saber o que aparece desperdiçava a vaga
    com acento fantasma: a advocacia gastava um slot em `calc`, seção que só existe
    quando o site tem calculadora, e ficava com um acento a menos que o tier pagou.
    """
    presentes = secoes_no_html(html)
    principal = escolha.get("principal", "")
    decisoes = [{"alvo": "página", "estilo": principal,
                 "comunica": COMUNICA.get(principal, ""),
                 "porque": next((d["porque"] for d in escolha.get("decisoes", [])
                                 if d["alvo"] == "página"), "")}] if principal else []
    escolhidos, fora = _selecionar(escolha.get("candidatos", []),
                                   escolha.get("teto", 1), presentes)
    decisoes += escolhidos
    return {"principal": principal,
            "acento": {d["alvo"]: d["estilo"] for d in decisoes if d["alvo"] != "página"},
            "decisoes": decisoes, "descartes": fora, "porque": _resumo(decisoes)}


def css(estilo: str, escopo: str = "") -> str:
    """CSS overlay do estilo. `escopo` = classe de seção (ex: 'preco') aplica SÓ nela.
    '' se o estilo não existir (degrada pro tema do motor)."""
    c = (ESTILOS.get((estilo or "").strip().lower()) or {}).get("css", "") or ""
    if not c or not escopo:
        return c
    # prefixa cada seletor com section.<escopo> — o morfismo passa a valer só ali
    esc = f"section.{escopo.strip().lstrip('.')}"
    fora = []
    for regra in c.split("}"):
        if "{" not in regra:
            continue
        sel, _, corpo = regra.partition("{")
        sel = sel.strip()
        if not sel or sel.startswith("@") or sel == "body":
            continue  # @media/body não fazem sentido escopados a uma seção
        novos = []
        for s in sel.split(","):
            s = s.strip()
            if not s:
                continue
            novos.append(esc if s in ("section", esc) else f"{esc} {s}")
        fora.append(f"{esc}{corpo}}}" if sel == "section" else f"{', '.join(novos)}{{{corpo}}}")
    return "\n".join(fora)


def secoes_no_html(html: str) -> set[str]:
    """Classes de <section> presentes NESTE HTML. É a verdade do artefato.

    A lista `SECOES_EMITIDAS` é pré-filtro de sanidade; esta função é a trava final.
    Seção condicional (a `calc` só aparece em site de advocacia com calculadora, a
    `depo` só com depoimento) faz qualquer lista estática mentir mais cedo ou mais
    tarde — e acento que não casa com nada é um estilo declarado na ficha e ausente
    da tela, que foi exatamente o defeito que a composição veio corrigir.
    """
    import re
    achadas: set[str] = set()
    for m in re.finditer(r'<section[^>]*\sclass="([^"]+)"', html or ""):
        achadas |= {c for c in m.group(1).split() if c and c != "reveal"}
    return achadas


def aplicaveis(acento: dict | None, html: str) -> tuple[dict, list[str]]:
    """(acentos que casam neste HTML, motivos dos que não casam)."""
    presentes = secoes_no_html(html)
    fica, fora = {}, []
    for secao, est in (acento or {}).items():
        if secao in presentes:
            fica[secao] = est
        else:
            fora.append(f"{est} em {secao}: a seção não existe nesta página")
    return fica, fora


def bloco(estilo: str, acento: dict | None = None) -> str:
    """<style> pronto pra injetar. `acento` = {classe_da_secao: morfismo} aplica um
    morfismo DIFERENTE só naquela seção (o acento vem depois, então vence na cascata).
    '' quando não há nada a aplicar."""
    partes = []
    if c := css(estilo):
        partes.append(f"/* principal: {estilo} */\n{c}")
    for secao, est in (acento or {}).items():
        if ca := css(est, escopo=secao):
            partes.append(f"/* acento: {est} em .{secao} */\n{ca}")
    if not partes:
        return ""
    marca = estilo + ("+" + "+".join(f"{k}:{v}" for k, v in (acento or {}).items()) if acento else "")
    return f'\n<style data-jpos-estilo="{marca}">\n' + "\n".join(partes) + "\n</style>"


def listar() -> list[dict]:
    """O VOCABULÁRIO: [{valor, rotulo, desc, comunica, peso}].

    Não é menu de seleção. É a referência do que o motor tem à disposição e do que
    cada morfismo comunica — quem lê a lista entende a decisão que a máquina tomou,
    em vez de ser obrigado a tomar a decisão no lugar dela.
    """
    return [{"valor": k, "rotulo": v["rotulo"], "desc": v["desc"],
             "comunica": COMUNICA.get(k, ""), "peso": PESO.get(k)}
            for k, v in ESTILOS.items()]


def conceitos(segmento: str) -> list[str]:
    """Conceitos estruturais sugeridos pro segmento + os transversais."""
    s = (segmento or "").strip().lower()
    achado: list[str] = []
    for chave, lista in CONCEITOS.items():
        if chave != "_transversal" and chave in s:
            achado = list(lista)
            break
    return achado + CONCEITOS["_transversal"]


if __name__ == "__main__":  # self-check
    assert css("") == "" and css("nao-existe") == ""
    assert bloco("") == "" and bloco("nao-existe") == ""
    for nome in ("glassmorphism", "neumorphism", "claymorphism", "brutalism",
                 "skeuomorphism", "liquid-glass", "spatial", "minimal", "maximal"):
        c = css(nome)
        assert c and "{" in c, nome
        assert bloco(nome).startswith("\n<style") and nome in bloco(nome), nome
    assert css("GLASSMORPHISM") == css("glassmorphism")  # case-insensitive
    # ESCOLHA AUTOMÁTICA (sem dropdown)
    a = escolher("academia", "T2", 0)
    assert a["principal"] == "spatial" and a["acento"], a
    assert all(d["porque"] and d["comunica"] for d in a["decisoes"]), a["decisoes"]
    assert escolher("clinica odontológica", "T3", 0)["principal"] == "neumorphism"
    # acento no nicho não pode furar o match (clínica/salão/imobiliária vêm acentuados)
    assert escolher("clínica odontológica", semente=0)["principal"] == "neumorphism"
    assert escolher("salão de beleza", semente=0)["principal"] == "claymorphism"
    assert escolher("imobiliária", semente=0)["principal"] == "minimal"
    assert escolher("academia", "T1")["principal"] == "minimal", "T1 é isca: leve e direto"
    assert escolher("loja de parafuso")["principal"] == "", "segmento fora do mapa = tema do motor"
    # acento alterna com a semente, principal fica estável (variedade sem virar loteria)
    # o principal ALTERNA entre as alternativas declaradas do segmento (é o que dá
    # poder ao "Gerar outro"), mas nunca sai delas — variedade sem virar loteria
    _decl = {e for e, _ in PERFIS["academia"]["principais"]}
    assert {escolher("academia", "T2", s)["principal"] for s in range(8)} <= _decl
    assert escolher("academia", "T2", 3) == escolher("academia", "T2", 3)
    # ESCOPO POR SEÇÃO: o CSS do acento só vale dentro da seção
    esc = css("brutalism", escopo="preco")
    assert "section.preco" in esc and "\nbody{" not in esc
    assert all(l.startswith(("section.preco", "/*")) or "section.preco" in l
               for l in esc.splitlines() if "{" in l), esc[:300]
    # bloco com acento traz os dois, e o acento vem DEPOIS (vence na cascata)
    b = bloco("minimal", {"preco": "brutalism"})
    assert "principal: minimal" in b and "acento: brutalism em .preco" in b
    assert b.index("acento:") > b.index("principal:")
    assert bloco("", {}) == "" and bloco("", {"preco": "brutalism"}) != ""
    ls = listar()
    assert len(ls) == len(ESTILOS) and ls[0]["valor"] == ""  # padrão primeiro
    assert any("PRs" in x for x in conceitos("academia"))
    assert any("tier" in x for x in conceitos("nicho-que-nao-existe"))  # transversal sempre vem
    # COMPOSIÇÃO: alvo que existe, acento visível, nada repetido
    for _seg in PERFIS:
        for _s in range(4):
            _c = escolher(_seg, "T4", semente=_s)
            _us = [d["estilo"] for d in _c["decisoes"]]
            assert len(_us) == len(set(_us)), (_seg, _s, _us)
            for _a in _c["acento"]:
                assert _a in SECOES_EMITIDAS, (_seg, _a)
    assert compativel("neumorphism", "glassmorphism")[0] is False
    assert compativel("minimal", "brutalism")[0] is True
    _h = '<section class="faq reveal">x</section>'
    assert "faq" in compor(escolher("advocacia", "T3", 0), _h)["acento"]
    assert compor(escolher("advocacia", "T3", 0), "<p>nada</p>")["acento"] == {}
    # MOTION COMO ACENTO: T2 paga com o único slot que tem; T1 não tem slot nenhum
    assert "cinetico" in ESTILOS and PESO["cinetico"] == 2
    _cin = css("cinetico", escopo="servicos")
    # o escopador joga fora QUALQUER regra @ — um @keyframes/@media aqui sumiria calado
    # e o acento não animaria nada. Por isso o CSS do cinetico só REFERENCIA keyframes
    # que o motor já emite (design.css_motion_scroll), sem declarar nenhuma.
    assert "@" not in _cin, "acento escopado com regra @ é acento que some"
    assert "section.servicos" in _cin and "cortina" in _cin
    assert escolher("academia", "T1")["acento"] == {}, "T1 não recebe acento nenhum"
    _t2 = [escolher("academia", "T2", _s)["acento"] for _s in range(6)]
    assert all(len(a) <= 1 for a in _t2), "T2 tem teto de 1 acento"
    assert any("cinetico" in a.values() for a in _t2), "cinetico nunca entra em T2"
    print(f"estilos OK — {len(ESTILOS)-1} morfismos, composição por segmento/tier com "
          f"justificativa, alvo verificado no HTML, degrada sem estilo")
