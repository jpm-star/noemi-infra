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

_PROMPT_VISAO = (
    "Você audita a captura de tela de uma LANDING PAGE que será enviada a um dono de "
    "negócio como demonstração paga. Procure APENAS defeitos visíveis:\n"
    "- texto sobreposto, cortado ou ilegível;\n"
    "- elemento gigante/desproporcional, ou espaço vazio enorme no meio do conteúdo;\n"
    "- imagem que claramente não tem relação com o ramo do negócio;\n"
    "- contraste ruim (texto quase invisível sobre o fundo);\n"
    "- qualquer coisa que pareça QUEBRADA ou inacabada.\n"
    "NÃO comente gosto pessoal, escolha de cor ou de fonte. Só defeito.\n"
    'Responda SOMENTE JSON: {"ok": true|false, "defeitos": ["frase curta", ...]}. '
    "Sem defeito: ok=true e defeitos=[]."
)


def _visao_julga(png: bytes) -> tuple[bool, list[str], str]:
    """(ok, defeitos, fonte). Sem visão disponível devolve (True, [], 'sem_visao') — as
    sondas já rodaram e reprovaram o que sabem; a visão é camada ADICIONAL, e travar tudo
    porque o LLM caiu tornaria o gate inútil justamente no dia de pico."""
    raiz = str(Path(__file__).resolve().parents[2] / "packages")
    if raiz not in sys.path:
        sys.path.insert(0, raiz)
    try:
        from shared_core.ai import visao
        txt, fonte = visao.analisar_frames([png], prompt=_PROMPT_VISAO)
    except Exception as e:  # noqa: BLE001
        return True, [], f"erro:{type(e).__name__}"
    if fonte != "groq" or not (txt or "").strip():
        return True, [], f"sem_juiz:{fonte}"
    import re
    m = re.search(r"\{.*\}", txt, re.S)
    try:
        d = json.loads(m.group(0)) if m else {}
    except ValueError:
        return True, [], "json_invalido"
    defeitos = [str(x)[:140] for x in (d.get("defeitos") or [])][:6]
    return (not defeitos), defeitos, fonte


def auditar(url: str, com_visao: bool = True, largura: int = LARGURA) -> dict:
    """Abre a URL, roda as sondas e (se passarem) a visão. Nunca levanta."""
    from playwright.sync_api import sync_playwright

    r = {"url": url, "sondas": [], "defeitos_visao": [], "fonte_visao": "-", "erro": ""}
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
        r["aprovado"] = False
        return r
    # visão só depois das sondas: se já reprovou por regra, não gasta LLM pra confirmar
    if com_visao and not r["sondas"]:
        _ok, defs, fonte = _visao_julga(png)
        r["defeitos_visao"], r["fonte_visao"] = defs, fonte
    r["aprovado"] = not r["sondas"] and not r["defeitos_visao"]
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
        log.info("%s %s", "OK  " if r["aprovado"] else "REPROVA", s)
    aprov = [i for i in itens if i["aprovado"]]
    tipos: dict[str, int] = {}
    for i in itens:
        for s in i["sondas"]:
            tipos[s["sonda"]] = tipos.get(s["sonda"], 0) + 1
        if i["defeitos_visao"]:
            tipos["visao"] = tipos.get("visao", 0) + len(i["defeitos_visao"])
    return {"total": len(itens), "aprovados": len(aprov), "reprovados": len(itens) - len(aprov),
            "por_tipo": tipos, "itens": itens}


def markdown(r: dict) -> str:
    L = [f"# QA visual — {r['aprovados']}/{r['total']} aprovados", "",
         f"- **Reprovados:** {r['reprovados']}",
         f"- **Por tipo de defeito:** " + (", ".join(f"`{k}` ×{v}" for k, v in
                                                     sorted(r["por_tipo"].items(), key=lambda x: -x[1])) or "nenhum"),
         ""]
    for i in r["itens"]:
        if i["aprovado"]:
            continue
        L.append(f"### ⛔ {i['slug']}")
        if i["erro"]:
            L.append(f"- não abriu: `{i['erro']}`")
        for s in i["sondas"][:6]:
            L.append(f"- `{s['sonda']}` — {s['el']}: {s['txt']}")
        for d in i["defeitos_visao"]:
            L.append(f"- visão: {d}")
        L.append("")
    return "\n".join(L)


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="Gate visual dos sites publicados.")
    ap.add_argument("slugs", nargs="*", help="vazio = todos os publicados")
    ap.add_argument("--sem-visao", action="store_true", help="só as sondas (rápido, sem LLM)")
    ap.add_argument("--saida", default="")
    a = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    r = auditar_todos(a.slugs or None, com_visao=not a.sem_visao)
    txt = markdown(r)
    if a.saida:
        Path(a.saida).write_text(txt, encoding="utf-8")
        print(f"\n-> {a.saida}")
    print("\n" + txt[:3000])
