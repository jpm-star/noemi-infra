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


def css(estilo: str) -> str:
    """CSS overlay do estilo. '' se não existir (degrada pro tema do motor)."""
    return (ESTILOS.get((estilo or "").strip().lower()) or {}).get("css", "") or ""


def bloco(estilo: str) -> str:
    """<style> pronto pra injetar no HTML gerado. '' quando não há estilo."""
    c = css(estilo)
    return f'\n<style data-jpos-estilo="{estilo}">/* estilo: {estilo} */{c}</style>' if c else ""


def listar() -> list[dict]:
    """[{valor, rotulo, desc}] pra montar o seletor da UI."""
    return [{"valor": k, "rotulo": v["rotulo"], "desc": v["desc"]} for k, v in ESTILOS.items()]


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
    ls = listar()
    assert len(ls) == len(ESTILOS) and ls[0]["valor"] == ""  # padrão primeiro
    assert any("PRs" in x for x in conceitos("academia"))
    assert any("tier" in x for x in conceitos("nicho-que-nao-existe"))  # transversal sempre vem
    print(f"estilos OK — {len(ESTILOS)-1} morfismos aplicáveis, conceitos por segmento, degrada sem estilo")
