"""Miniaturas da vitrine: screenshot REAL de cada site, não mockup.

Um mockup bonito de site que não existe é o que qualquer agência faz. Aqui a imagem
é o site no ar, capturado agora — se o site cair, a miniatura some junto e isso é uma
propriedade desejada: a vitrine não sobrevive ao produto.

JPEG e não WebP: `page.screenshot` só emite png/jpeg, e trocar isso custaria Pillow
por ~15% de bytes. ponytail: jpeg q=72; se a vitrine crescer muito, aí vale converter.

Rodar:  python thumbs.py            (só o que falta)
        python thumbs.py --refazer  (todas de novo)
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import dados  # noqa: E402

SAIDA = Path("/var/www/jpos/vitrine")
LARGURA, ALTURA = 1200, 700   # recorte no HERO: abaixo dele começa o branco entre seções


def gerar(refazer: bool = False) -> dict:
    from playwright.sync_api import sync_playwright

    SAIDA.mkdir(parents=True, exist_ok=True)
    itens = dados.vitrine()
    feitas, puladas, erros = [], [], []
    with sync_playwright() as p:
        b = p.chromium.launch()
        pg = b.new_page(viewport={"width": LARGURA, "height": ALTURA},
                        device_scale_factor=1.5)   # 1.5x: nítido em tela retina sem dobrar peso
        for it in itens:
            destino = SAIDA / f"{it['slug']}.jpg"
            if destino.exists() and not refazer:
                puladas.append(it["slug"])
                continue
            try:
                pg.goto(it["url"], wait_until="networkidle", timeout=45000)
                # o motor anima na entrada (cortina/reveal): sem esperar, a foto sai
                # no meio da animação e o site parece meio-carregado na vitrine
                pg.wait_for_timeout(1800)
                pg.screenshot(path=str(destino), type="jpeg", quality=72)
                feitas.append(it["slug"])
            except Exception as e:  # noqa: BLE001 — um site fora do ar não derruba a vitrine
                erros.append((it["slug"], str(e)[:80]))
        b.close()
    return {"feitas": feitas, "puladas": puladas, "erros": erros}


if __name__ == "__main__":
    r = gerar("--refazer" in sys.argv[1:])
    for s in r["feitas"]:
        print("+", s)
    for s, e in r["erros"]:
        print("!", s, e)
    print(f"\n{len(r['feitas'])} capturadas · {len(r['puladas'])} já existiam · "
          f"{len(r['erros'])} falharam")
