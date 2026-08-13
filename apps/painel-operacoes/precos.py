"""Preço da JPOS — fonte ÚNICA, versionada, editável à mão.

Por que existe: até hoje o preço vivia na apostila e na cabeça do JP. Cada material
novo divergia do anterior, e um tier chegou a ser vendido com uma entrega que o
produto não fazia (Calendar no T3). Preço que não está em lugar nenhum não pode ser
conferido — então diverge por padrão, não por acidente.

`precos.json` ao lado é a verdade. Este módulo só lê, valida e serve. Editar é abrir
o JSON, salvar e reiniciar o painel — de propósito: um CRUD de preço seria mais
código pra manter e mais uma tela pra errar, num dado que muda 2x por ano.

TRAVA COMERCIAL: item com `provisorio: true` não pode ir pra material de cliente.
`para_cliente()` já devolve só o que está liberado — quem gerar proposta usa essa,
não a lista crua.
"""
from __future__ import annotations

import json
import datetime as _dt
from pathlib import Path

_ARQ = Path(__file__).resolve().parent / "precos.json"


def _bruto() -> dict:
    return json.loads(_ARQ.read_text(encoding="utf-8"))


def moeda(v: float | None) -> str:
    """Formata pra exibição. None vira travessão — 'R$ 0,00' mentiria dizendo
    que é grátis, quando na verdade é 'não se cobra nessa coluna'."""
    if v is None:
        return "—"
    return f"R$ {v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


TODOS_OS_TIERS = ("T1", "T2", "T3", "T4")


def escopo_upsell(u: dict) -> str:
    """Para quem o upsell vale. "" quando vale pra todo mundo.

    `disponivel_em` existia em todo upsell desde o começo e NENHUM renderizador lia
    — passou despercebido porque todos valiam pros 4 tiers. O primeiro upsell restrito
    (Calendar, que o T3/T4 já tem no core) transforma o campo decorativo em erro de
    cobrança: oferecer a um T3 uma peça que ele já paga. Por isso a leitura mora aqui,
    uma vez, e não em cada material.
    """
    em = tuple(u.get("disponivel_em") or TODOS_OS_TIERS)
    if set(em) >= set(TODOS_OS_TIERS):
        return ""
    return "só " + " e ".join(x for x in TODOS_OS_TIERS if x in em)


def tudo() -> dict:
    """Tudo, inclusive provisório. Uso INTERNO (painel do JP)."""
    d = _bruto()
    return {"moeda": d.get("moeda", "R$"), "atualizado_em": d.get("_atualizado_em"),
            "tiers": d["tiers"], "upsells": d["upsells"]}


def para_cliente() -> dict:
    """Só o que pode ser mostrado a cliente: nada provisório, nada sem preço.

    É esta função que qualquer gerador de proposta/apostila deve chamar. Filtrar no
    ponto de USO seria repetir a regra em todo lugar novo — e esquecer numa delas
    é exatamente como um preço não confirmado vaza pra fora.
    """
    d = _bruto()
    upsells = [u for u in d["upsells"]
               if not u.get("provisorio") and (u.get("setup") or u.get("mensal"))]
    return {"moeda": d.get("moeda", "R$"), "tiers": d["tiers"], "upsells": upsells}


def tabela_markdown(cliente: bool = True) -> str:
    """A tabela pronta pra colar em apostila/proposta — some do sistema, não do Word."""
    d = para_cliente() if cliente else tudo()
    linhas = ["| Tier | O que é | Setup | Mensal |", "|---|---|---|---|"]
    for t in d["tiers"]:
        linhas.append(f"| **{t['id']} — {t['nome']}** | {'; '.join(t['entrega'])} "
                      f"| {moeda(t['setup'])} | {moeda(t['mensal'])} |")
    linhas += ["", "| Upsell | Para quem | Setup | Mensal |", "|---|---|---|---|"]
    for u in d["upsells"]:
        marca = "" if cliente else (" ⚠️ provisório" if u.get("provisorio") else "")
        linhas.append(f"| {u['nome']}{marca} | {escopo_upsell(u) or 'qualquer plano'} "
                      f"| {moeda(u.get('setup'))} | {moeda(u.get('mensal'))} |")
    return "\n".join(linhas)


def validar() -> list[str]:
    """Problemas que fariam o preço mentir. Roda no self-check e no boot do painel."""
    d = _bruto()
    erros = []
    ids = [t["id"] for t in d["tiers"]]
    if ids != ["T1", "T2", "T3", "T4"]:
        erros.append(f"tiers fora de ordem ou faltando: {ids}")
    # escada cumulativa: preço tem que subir. T2 mais barato que T1 seria erro de
    # digitação que ninguém nota lendo, e vira desconto acidental na call.
    for a, b in zip(d["tiers"], d["tiers"][1:]):
        if (b["setup"] or 0) <= (a["setup"] or 0):
            erros.append(f"{b['id']} não custa mais que {a['id']} — escada quebrada")
    for u in d["upsells"]:
        if not u.get("provisorio") and not (u.get("setup") or u.get("mensal")):
            erros.append(f"upsell '{u['id']}' sem preço e sem flag de provisório")
    return erros


if __name__ == "__main__":
    erros = validar()
    assert not erros, erros
    t = tudo()
    c = para_cliente()
    escondidos = len(t["upsells"]) - len(c["upsells"])
    # o que importa não é a QUANTIDADE de provisórios (ela muda quando um custo é
    # confirmado) — é que nenhum provisório vaze pra visão do cliente
    assert not any(u.get("provisorio") for u in c["upsells"]), "provisório vazou pro cliente"
    assert escondidos == sum(1 for u in t["upsells"] if u.get("provisorio"))
    print(tabela_markdown(cliente=False))
    print(f"\n{len(t['tiers'])} tiers · {len(t['upsells'])} upsells "
          f"({escondidos} provisórios, ocultos pro cliente) · validação OK")


def _primeiro_pagamento(t: dict) -> int | None:
    """Setup + 1ª mensalidade. É o número que o dono ouve na porta.

    Existe porque a mesma venda já foi citada como "1.500" e como "1.397" na mesma
    semana: um era chute de âncora, o outro era o primeiro pagamento real do T2
    (1000 + 397). Preço que muda de valor conforme quem conta não é preço, é ruído —
    e o dono percebe. Aqui sai calculado da fonte única, sempre.
    """
    if t.get("setup") is None and t.get("mensal") is None:
        return None
    return (t.get("setup") or 0) + (t.get("mensal") or 0)


def catalogo_html(cliente: bool = True) -> str:
    """O catálogo em HTML pronto pra virar PDF (wkhtmltopdf) ou impressão.

    Feito pra PAPEL na mão de um dono de negócio, não pra tela: A4, tinta econômica
    (sem bloco chapado, que borra em jato de tinta e come cartucho), corpo grande o
    bastante pra ler sem óculos, e a escada de preço legível de relance. O acento é
    uma régua fina — a hierarquia vem do tamanho e do espaço, não de cor.
    """
    from html import escape as _e
    d = para_cliente() if cliente else tudo()
    hoje = _dt.date.today().strftime("%d/%m/%Y")

    cards = []
    for t in d["tiers"]:
        pp = _primeiro_pagamento(t)
        recorrencia = (f"depois {moeda(t['mensal'])}/mês" if t.get("mensal")
                       else "sem mensalidade")
        itens = "".join(f"<li>{_e(str(x))}</li>" for x in t["entrega"])
        cards.append(f"""
      <article class="tier">
        <header>
          <span class="id">{_e(t['id'])}</span>
          <h2>{_e(t['nome'])}</h2>
        </header>
        <p class="preco"><strong>{moeda(pp)}</strong> <span>para começar</span></p>
        <p class="rec">{_e(recorrencia)}</p>
        <ul>{itens}</ul>
      </article>""")

    ups = "".join(
        f"<tr><td>{_e(u['nome'])}"
        f"{f'<span class=\'so\'>{_e(escopo_upsell(u))}</span>' if escopo_upsell(u) else ''}</td>"
        f"<td>{moeda(u.get('setup'))}</td>"
        f"<td>{moeda(u.get('mensal'))}{'/mês' if u.get('mensal') else ''}</td></tr>"
        for u in d["upsells"])

    return f"""<!doctype html>
<html lang="pt-BR"><head><meta charset="utf-8">
<title>JPOS — o que a gente faz e quanto custa</title>
<style>
  @page {{ size: A4; margin: 14mm 13mm; }}
  * {{ box-sizing: border-box; }}
  body {{ font: 11.5pt/1.5 Georgia, "Times New Roman", serif; color: #111; margin: 0; }}
  h1, h2, .id, th {{ font-family: Helvetica, Arial, sans-serif; }}
  .topo {{ border-bottom: 2px solid #111; padding-bottom: 6mm; margin-bottom: 7mm; }}
  h1 {{ font-size: 19pt; margin: 0 0 2mm; letter-spacing: -.2px; }}
  .sub {{ margin: 0; font-size: 10.5pt; color: #444; }}
  /* COLUNA ÚNICA de propósito. O WebKit do wkhtmltopdf não implementa CSS Grid, então
     duas colunas viravam uma só no PDF e duas no navegador — o material impresso não
     podia divergir da tela. E lendo em pé, na porta do cliente, a lista corrida é mais
     fácil de acompanhar com o dedo do que duas colunas. */
  .grade {{ display: block; }}
  .grade .tier + .tier {{ margin-top: 5mm; }}
  /* sem fundo chapado: régua fina à esquerda. Imprime igual em P&B e não come tinta. */
  .tier {{ border-left: 3px solid #111; padding: 0 0 3mm 5mm; break-inside: avoid; }}
  .tier header {{ display: flex; align-items: baseline; gap: 3mm; }}
  .id {{ font-size: 9pt; font-weight: 700; letter-spacing: 1px; color: #666; }}
  .tier h2 {{ font-size: 13.5pt; margin: 0 0 1mm; }}
  .preco {{ margin: 1mm 0 0; font-size: 10.5pt; }}
  .preco strong {{ font-size: 17pt; letter-spacing: -.5px; }}
  .preco span {{ color: #555; }}
  .rec {{ margin: 0 0 2mm; font-size: 10pt; color: #555; }}
  .tier ul {{ margin: 0; padding-left: 4.5mm; }}
  .tier li {{ margin-bottom: .8mm; }}
  h3 {{ font-family: Helvetica, Arial, sans-serif; font-size: 11pt; text-transform: uppercase;
       letter-spacing: 1.5px; margin: 9mm 0 3mm; color: #444; }}
  table {{ width: 100%; border-collapse: collapse; font-size: 10.5pt; }}
  th {{ text-align: left; font-size: 8.5pt; text-transform: uppercase; letter-spacing: .8px;
       color: #666; border-bottom: 1px solid #bbb; padding-bottom: 1.5mm; }}
  td {{ padding: 1.8mm 0; border-bottom: 1px solid #e6e6e6; }}
  /* nowrap: sem isto "R$ 97,00/mês" quebra em duas linhas e o preço fica ilegível */
  td + td, th + th {{ text-align: right; width: 30mm; white-space: nowrap; }}
  /* escopo do upsell: cinza e menor, ao lado do nome. Sem isto o catálogo impresso
     oferece ao T3 uma peça que ele já paga no plano. */
  .so {{ display: block; font-size: 9pt; color: #666; }}
  .pe {{ margin-top: 8mm; padding-top: 4mm; border-top: 1px solid #bbb;
        font-size: 9.5pt; color: #555; display: flex; justify-content: space-between; }}
</style></head>
<body>
  <div class="topo">
    <h1>O que a gente faz — e quanto custa</h1>
    <p class="sub">JPOS · site, presença e atendimento por IA para negócio local</p>
  </div>
  <div class="grade">{"".join(cards)}</div>
  <h3>Pode somar a qualquer plano</h3>
  <table>
    <tr><th>Item</th><th>Entrada</th><th>Depois</th></tr>
    {ups}
  </table>
  <div class="pe">
    <span>Preços de {hoje}. Sem fidelidade — cancela quando quiser.</span>
    <span>jpos.com.br</span>
  </div>
</body></html>"""
