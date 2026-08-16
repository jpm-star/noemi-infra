"""Gate visual: olha a página renderizada antes de ela virar material de venda.

POR QUE EXISTE: em 2026-08-06 três bugs visuais foram ao ar no template-base — título
invisível, letra gigante ocupando o card de serviço, linha de credibilidade colada no CTA.
Todos os testes passavam. Nenhum deles é detectável lendo HTML: o título tinha `opacity: 1`
e 299px de largura, e estava pintado de transparente.

DUAS CAMADAS, nesta ordem, e a ordem é o ponto:

  1. SONDAS DETERMINÍSTICAS (JS no DOM renderizado) — baratas, reprodutíveis e sem LLM.
     Pegam exatamente as classes de defeito que já nos morderam. Uma sonda que já viu o
     bug uma vez vale mais que um juiz genérico, porque não muda de opinião.
  2. VISÃO MULTIMODAL — só depois, e só se as sondas passarem. Pega o que não dá pra
     enumerar: feiura, desequilíbrio, coisa que "parece quebrada" sem violar regra.

A lição que gerou a ordem: um QA por GEOMETRIA teria aprovado a página do título
invisível. Largura e opacidade não dizem se o texto tem cor.

Interface fixa de visão (`shared_core.ai.visao`), nunca o provider direto — regra do
CLAUDE.md. Hoje resolve para Groq multimodal; com ANTHROPIC_API_KEY passa a poder usar
Claude sem mudar uma linha daqui.
DEPENDÊNCIA: playwright, e a VERSÃO IMPORTA. Ele baixa um Chromium com número de build
casado à versão da lib; instalar uma versão diferente da que já tem navegador em
~/.cache/ms-playwright faz `launch()` procurar um binário que não existe. Alinhado em
1.61.0 (o build 1228 que já está no disco):
    uv pip install --python /root/noemi-infra/.venv/bin/python "playwright==1.61.0"
"""
from __future__ import annotations

import json
import logging
import os
import sys
from pathlib import Path

log = logging.getLogger(__name__)

SITES_DIR = Path(os.environ.get("SITE_OUT_DIR", "/var/www/sites"))
BASE_URL = os.environ.get("SITE_BASE_URL", "https://p.jpos.com.br")
LARGURA, ALTURA = 1280, 900

# ── camada 1: sondas ─────────────────────────────────────────────────────────────
# Cada uma nasceu de um bug real que foi ao ar. Rodam no DOM já renderizado.
_SONDAS_JS = r"""
() => {
  const out = [];
  const vis = el => { const r = el.getBoundingClientRect(); return r.width > 0 && r.height > 0; };

  // 1. TEXTO INVISÍVEL POR COR. O caso do h1 fatiado: text-fill transparente sem
  //    gradiente atrás. Geometria e opacidade não pegam isto.
  for (const el of document.querySelectorAll('h1, h2, h3, p, a, li, span')) {
    if (!el.textContent.trim() || !vis(el)) continue;
    const c = getComputedStyle(el);
    const transp = c.webkitTextFillColor === 'rgba(0, 0, 0, 0)' || c.color === 'rgba(0, 0, 0, 0)';
    if (!transp) continue;
    // transparente é LEGÍTIMO quando há gradiente clipado no texto DESTE elemento
    const temGrad = c.backgroundImage && c.backgroundImage !== 'none' &&
                    (c.webkitBackgroundClip === 'text' || c.backgroundClip === 'text');
    if (!temGrad) out.push({sonda: 'texto_invisivel', el: el.tagName.toLowerCase(),
                            txt: el.textContent.trim().slice(0, 60)});
  }

  // 2. SOBREPOSIÇÃO REAL entre blocos de conteúdo irmãos.
  // Camada de FUNDO não conta: vídeo/orbe/aurora são absolute atrás do conteúdo por
  // design — compará-los com o texto acusa "sobreposição" em toda página que tem hero
  // com mídia. Só entram elementos do FLUXO normal.
  const deFundo = el => {
    const c = getComputedStyle(el);
    return c.position === 'absolute' || c.position === 'fixed' ||
           /hero-media|hero-orb|aurora|scroll-prog|zap-fixo/.test(el.className || '');
  };
  const alvos = [...document.querySelectorAll('.hero > *, .sv-card, .card, .preco-card')]
                  .filter(el => vis(el) && !deFundo(el));
  for (let i = 0; i < alvos.length; i++)
    for (let j = i + 1; j < alvos.length; j++) {
      const a = alvos[i].getBoundingClientRect(), b = alvos[j].getBoundingClientRect();
      if (alvos[i].contains(alvos[j]) || alvos[j].contains(alvos[i])) continue;
      const cruza = !(a.right <= b.left || b.right <= a.left || a.bottom <= b.top || b.bottom <= a.top);
      // 4px de tolerância: sombra e borda encostam sem ser defeito
      const area = Math.max(0, Math.min(a.right,b.right)-Math.max(a.left,b.left)) *
                   Math.max(0, Math.min(a.bottom,b.bottom)-Math.max(a.top,b.top));
      if (cruza && area > 16) out.push({sonda: 'sobreposicao',
        el: alvos[i].className + ' × ' + alvos[j].className, txt: Math.round(area) + 'px²'});
    }

  // 3. TIPOGRAFIA GIGANTE SEM PALAVRA. O card com um "A" de 60px: texto curtíssimo em
  //    corpo enorme é placeholder quebrado, não design.
  for (const el of document.querySelectorAll('*')) {
    const t = el.textContent.trim();
    if (t.length > 3 || !t || el.children.length) continue;
    if (!vis(el)) continue;
    if (parseFloat(getComputedStyle(el).fontSize) >= 40)
      out.push({sonda: 'letra_gigante', el: el.className || el.tagName, txt: t});
  }

  // 4. ESTOURO HORIZONTAL: página que rola pro lado no celular.
  if (document.documentElement.scrollWidth > window.innerWidth + 2)
    out.push({sonda: 'estouro_horizontal', el: 'html',
              txt: document.documentElement.scrollWidth + ' > ' + window.innerWidth});

  // 5. IMAGEM QUEBRADA.
  for (const img of document.querySelectorAll('img'))
    if (img.complete && img.naturalWidth === 0)
      out.push({sonda: 'imagem_quebrada', el: 'img', txt: (img.src || '').slice(-60)});

  // 6. HERO SEM TÍTULO VISÍVEL — o sintoma que motivou tudo, checado direto.
  const h1 = document.querySelector('h1');
  if (!h1 || !h1.textContent.trim()) out.push({sonda: 'sem_h1', el: 'h1', txt: ''});

  // 7. PLACEHOLDER DE CONTEÚDO que vazou pro ar.
  const corpo = document.body.innerText.toLowerCase();
  for (const p of ['lorem ipsum', 'em breve', 'sua empresa aqui', 'texto de exemplo',
                   'coming soon', 'descrição do serviço aqui'])
    if (corpo.includes(p)) out.push({sonda: 'placeholder', el: 'body', txt: p});

  return out;
}
"""

# CURTO DE PROPÓSITO, e isto foi MEDIDO (2026-08-16), não estilo.
#
# O juiz é o qwen3.6, modelo de raciocínio, e `_orcamento()` do `visao.py` lhe dá 5.100
# tokens pra PENSAR E RESPONDER — o mesmo bolso pras duas coisas. A versão anterior deste
# prompt listava 5 categorias de defeito e 2 proibições; o modelo gastava o bolso inteiro
# deliberando e a resposta saía truncada. Medição, mesma foto, 2 tentativas cada:
#     prompt longo -> 19.734 chars de <think>, resposta VAZIA, 2/2 (sempre o mesmo número:
#                     era determinístico, não instabilidade)
#     prompt curto -> resposta JSON válida, 2/2, e achou defeito real que as sondas não pegam
# Ou seja: com o prompt longo o juiz de visão NUNCA respondeu em site nenhum. Cada defeito
# só detectável por visão passou batido desde que o gate existe.
# Se for pra acrescentar categoria aqui, meça de novo — cada linha a mais custa resposta.
_PROMPT_VISAO = (
    "Esta imagem é a tela de um site que vai ser mostrado a um cliente. "
    "Há algum DEFEITO VISÍVEL (texto cortado, ilegível ou sobreposto; elemento "
    "desproporcional; buraco vazio enorme; algo quebrado)? Ignore gosto de cor e fonte. "
    'Responda só JSON: {"ok":true|false,"defeitos":["frase curta"]}'
)


def _visao_julga(png: bytes) -> tuple[str, list[str], str]:
    """(veredito, defeitos, fonte) — veredito ∈ 'ok' | 'defeito' | 'indeterminado'.

    ATÉ 2026-08-16 ISTO DEVOLVIA `True` QUANDO O JUIZ FALHAVA, e `auditar()` publicava
    "aprovado: true" pra uma página que ninguém olhou. Não é detalhe de log: é o gate
    afirmando um fato que não apurou, e qualquer relatório citando "passou no QA visual"
    herdando a mentira.

    Nem por isso vira reprovação: reprovar por indisponibilidade transforma queda de
    provider em fila de site travado sem defeito nenhum. O terceiro estado é o honesto —
    'indeterminado' diz o que houve e devolve a decisão pra quem lê.
    """
    raiz = str(Path(__file__).resolve().parents[2] / "packages")
    if raiz not in sys.path:
        sys.path.insert(0, raiz)
    try:
        from shared_core.ai import visao
        txt, fonte = visao.analisar_frames([png], prompt=_PROMPT_VISAO)
    except Exception as e:  # noqa: BLE001
        return "indeterminado", [], f"erro:{type(e).__name__}"
    if fonte != "groq" or not (txt or "").strip():
        # resposta vazia = estourou o teto de tokens no raciocínio e não sobrou veredito
        return "indeterminado", [], f"sem_juiz:{fonte}"
    import re
    m = re.search(r"\{.*\}", txt, re.S)
    try:
        d = json.loads(m.group(0)) if m else {}
    except ValueError:
        return "indeterminado", [], "json_invalido"
    defeitos = [str(x)[:140] for x in (d.get("defeitos") or [])][:6]
    # a EVIDÊNCIA ganha da autodeclaração: listou defeito, reprovou — mesmo com ok=true
    # (mesma regra de auditor_copy.py, onde o modelo já se contradisse na prática)
    return ("defeito" if defeitos else "ok"), defeitos, fonte


def _veredito(r: dict) -> str:
    """'aprovado' | 'reprovado' | 'indeterminado', a partir das duas camadas.

    `aprovado` exige que alguém TENHA OLHADO e não achado defeito. Juiz que não respondeu
    não vira aval. `--sem-visao` é escolha consciente de quem roda, então aprova pelas
    sondas — mas o campo `visao` guarda que ninguém olhou, e é isso que distingue
    "não pedi juiz" de "pedi e ele caiu".
    """
    if r["erro"] or r["sondas"] or r["defeitos_visao"]:
        return "reprovado"
    return "indeterminado" if r["visao"] == "indeterminado" else "aprovado"


def auditar(url: str, com_visao: bool = True, largura: int = LARGURA) -> dict:
    """Abre a URL, roda as sondas e (se passarem) a visão. Nunca levanta."""
    from playwright.sync_api import sync_playwright

    r = {"url": url, "sondas": [], "defeitos_visao": [], "fonte_visao": "-", "erro": "",
         "visao": "nao_pedida"}
    try:
        with sync_playwright() as p:
            b = p.chromium.launch()
            pg = b.new_page(viewport={"width": largura, "height": ALTURA})
            pg.goto(url, wait_until="networkidle", timeout=60000)
            pg.wait_for_timeout(2500)          # deixa a animação de entrada terminar
            r["sondas"] = pg.evaluate(_SONDAS_JS)
            png = pg.screenshot(full_page=False)
            b.close()
    except Exception as e:  # noqa: BLE001 — página que nem abre é reprovação, não crash
        r["erro"] = f"{type(e).__name__}: {e}"[:160]
        r["veredito"], r["aprovado"] = "reprovado", False
        return r
    # visão só depois das sondas: se já reprovou por regra, não gasta LLM pra confirmar
    if com_visao and not r["sondas"]:
        r["visao"], r["defeitos_visao"], r["fonte_visao"] = _visao_julga(png)
    r["veredito"] = _veredito(r)
    r["aprovado"] = r["veredito"] == "aprovado"   # derivado; nunca a fonte da verdade
    return r


def slugs_publicados() -> list[str]:
    return sorted(d.name for d in SITES_DIR.iterdir()
                  if d.is_dir() and not d.name.startswith("_") and (d / "index.html").is_file())


def auditar_todos(slugs: list[str] | None = None, com_visao: bool = True) -> dict:
    alvos = slugs or slugs_publicados()
    itens = []
    for s in alvos:
        r = auditar(f"{BASE_URL}/{s}/", com_visao=com_visao)
        r["slug"] = s
        itens.append(r)
        log.info("%-13s %s", r["veredito"].upper(), s)
    conta = {"aprovado": 0, "reprovado": 0, "indeterminado": 0}
    tipos: dict[str, int] = {}
    for i in itens:
        conta[i["veredito"]] += 1
        for s in i["sondas"]:
            tipos[s["sonda"]] = tipos.get(s["sonda"], 0) + 1
        if i["defeitos_visao"]:
            tipos["visao"] = tipos.get("visao", 0) + len(i["defeitos_visao"])
    return {"total": len(itens), "aprovados": conta["aprovado"],
            "reprovados": conta["reprovado"], "indeterminados": conta["indeterminado"],
            "por_tipo": tipos, "itens": itens}


def markdown(r: dict) -> str:
    """O indeterminado aparece SEPARADO, nunca somado aos aprovados.

    Se ele fosse contado como ok, o relatório voltaria a dizer '74/74 aprovados' num dia
    em que o juiz de visão não respondeu nenhuma vez — que é exatamente o defeito que a
    separação existe pra impedir."""
    ind = r.get("indeterminados", 0)
    L = [f"# QA visual — {r['aprovados']}/{r['total']} aprovados", "",
         f"- **Reprovados:** {r['reprovados']}",
         f"- **Sem veredito (juiz de visão não respondeu):** {ind}"
         + ("  ← não são aprovados: ninguém olhou" if ind else ""),
         f"- **Por tipo de defeito:** " + (", ".join(f"`{k}` ×{v}" for k, v in
                                                     sorted(r["por_tipo"].items(), key=lambda x: -x[1])) or "nenhum"),
         ""]
    for i in r["itens"]:
        if i["veredito"] == "aprovado":
            continue
        L.append(f"### {'⛔' if i['veredito'] == 'reprovado' else '⚠️'} {i['slug']}"
                 + ("" if i["veredito"] == "reprovado" else "  — sem veredito visual"))
        if i["erro"]:
            L.append(f"- não abriu: `{i['erro']}`")
        for s in i["sondas"][:6]:
            L.append(f"- `{s['sonda']}` — {s['el']}: {s['txt']}")
        for d in i["defeitos_visao"]:
            L.append(f"- visão: {d}")
        if i["veredito"] == "indeterminado":
            L.append(f"- sondas passaram, mas a visão não julgou (`{i['fonte_visao']}`) — "
                     "olhe você, ou rode de novo quando o provider voltar")
        L.append("")
    return "\n".join(L)


def _autoteste() -> None:
    """A trava do falso verde. Se alguém reescrever `_veredito` pra 'simplificar' e
    voltar a tratar juiz ausente como aval, isto quebra."""
    base = {"erro": "", "sondas": [], "defeitos_visao": [], "visao": "ok"}
    assert _veredito(base) == "aprovado"
    assert _veredito({**base, "visao": "indeterminado"}) == "indeterminado", \
        "juiz que não respondeu virou aprovação — é o bug de 2026-08-16 de volta"
    assert _veredito({**base, "visao": "nao_pedida"}) == "aprovado", "--sem-visao é escolha"
    assert _veredito({**base, "sondas": [{"sonda": "sem_h1"}]}) == "reprovado"
    assert _veredito({**base, "defeitos_visao": ["texto cortado"]}) == "reprovado"
    # defeito achado ganha de juiz ausente: reprovar é mais forte que não saber
    assert _veredito({**base, "visao": "indeterminado",
                      "sondas": [{"sonda": "x"}]}) == "reprovado"
    assert _veredito({**base, "erro": "TimeoutError"}) == "reprovado", "página que não abre"
    # e o contrato de _visao_julga: o texto vazio do juiz não pode virar 'ok'
    r = {"total": 3, "aprovados": 1, "reprovados": 1, "indeterminados": 1, "por_tipo": {},
         "itens": [{"slug": "a", "veredito": "aprovado", "erro": "", "sondas": [],
                    "defeitos_visao": [], "fonte_visao": "groq"},
                   {"slug": "b", "veredito": "indeterminado", "erro": "", "sondas": [],
                    "defeitos_visao": [], "fonte_visao": "sem_juiz:ocr"}]}
    md = markdown(r)
    assert "Sem veredito" in md and "⚠️ b" in md and "### ⛔" not in md, md
    assert "1/3 aprovados" in md, "indeterminado não pode inflar o placar"
    print("qa_visual OK — juiz ausente vira 'indeterminado', não aprovação; "
          "defeito ganha de não-sei; relatório conta os três separados")


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="Gate visual dos sites publicados.")
    ap.add_argument("slugs", nargs="*", help="vazio = todos os publicados")
    ap.add_argument("--sem-visao", action="store_true", help="só as sondas (rápido, sem LLM)")
    ap.add_argument("--saida", default="")
    ap.add_argument("--check", action="store_true", help="só o autoteste da lógica")
    a = ap.parse_args()
    if a.check:
        _autoteste()
        raise SystemExit(0)
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    r = auditar_todos(a.slugs or None, com_visao=not a.sem_visao)
    txt = markdown(r)
    if a.saida:
        Path(a.saida).write_text(txt, encoding="utf-8")
        print(f"\n-> {a.saida}")
    print("\n" + txt[:3000])
