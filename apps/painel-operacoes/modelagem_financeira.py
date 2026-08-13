#!/usr/bin/env python3
"""Modelagem financeira da JPOS em .xlsx — gerada da FONTE, não digitada à mão.

Roda assim:  python3 modelagem_financeira.py [saida.xlsx]

De onde sai cada número:
  catálogo ....... precos.json (a mesma fonte única que o painel e o PDF leem)
  funil .......... data/leads.db, tabela tracker_prospects (contagem real)
  conversão ...... NÃO SAI DE LUGAR NENHUM — é célula de entrada do JP

A última linha é o ponto da planilha inteira. Em 13/08/2026 o tracker tinha 1.532
prospects e ZERO vendas fechadas (`valor_fechado` vazio em 100% das linhas, 1.530
ainda em "A contatar", e os 30 e-mails de prospecção todos em `pending`). Não é
amostra pequena: é amostra nenhuma. Então a planilha não projeta receita — ela
MODELA, com a taxa como entrada visível e uma tabela de sensibilidade ao lado.
Cravar "2% de conversão" aqui viraria, em duas semanas, "a planilha diz que dá
R$X" — e o X seria invenção minha com cara de dado.
"""
from __future__ import annotations

import json
import sqlite3
import sys
from datetime import date
from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

RAIZ = Path(__file__).resolve().parent
PRECOS = RAIZ / "precos.json"
BANCO = Path("/root/noemi-infra/data/leads.db")

TIERS = ("T1", "T2", "T3", "T4")

TINTA = "1F2933"
ENTRADA = PatternFill("solid", fgColor="FFF3C4")      # amarelo = você edita
CALC = PatternFill("solid", fgColor="F0F4F8")         # cinza = fórmula
CABECA = PatternFill("solid", fgColor="1F2933")
ALERTA = PatternFill("solid", fgColor="FFE3E3")
FINA = Side(style="thin", color="D9E2EC")
GRADE = Border(left=FINA, right=FINA, top=FINA, bottom=FINA)
MOEDA = 'R$ #,##0.00'
# positivo;negativo;ZERO — o zero vira travessão. O precos.py já estabelece a regra:
# "R$ 0,00 mentiria dizendo que é grátis, quando na verdade é 'não se cobra nessa
# coluna'". O T1 não tem mensalidade; mostrar R$ 0,00 na planilha faria o JP responder
# "é de graça?" na frente do cliente. O valor continua 0 pra fórmula somar.
MOEDA_OU_TRACO = 'R$ #,##0.00;-R$ #,##0.00;"—"'
PCT = '0.00%'


def _titulo(ws, linha, texto, largura=6):
    c = ws.cell(linha, 1, texto)
    c.font = Font(bold=True, size=13, color=TINTA)
    ws.merge_cells(start_row=linha, start_column=1, end_row=linha, end_column=largura)
    ws.row_dimensions[linha].height = 22
    return linha + 1


def _cabecalho(ws, linha, colunas):
    for i, nome in enumerate(colunas, start=1):
        c = ws.cell(linha, i, nome)
        c.font = Font(bold=True, color="FFFFFF", size=10)
        c.fill = CABECA
        c.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        c.border = GRADE
    ws.row_dimensions[linha].height = 30
    return linha + 1


def _nota(ws, linha, texto, largura=6, alerta=False):
    c = ws.cell(linha, 1, texto)
    c.font = Font(italic=True, size=9, color="52606D")
    c.alignment = Alignment(wrap_text=True, vertical="top")
    ws.merge_cells(start_row=linha, start_column=1, end_row=linha, end_column=largura)
    if alerta:
        for i in range(1, largura + 1):
            ws.cell(linha, i).fill = ALERTA
        c.font = Font(italic=False, bold=True, size=9, color="8B0000")
    ws.row_dimensions[linha].height = max(16, 13 * (len(texto) // (largura * 22) + 1))
    return linha + 1


def _larguras(ws, larguras):
    for i, w in enumerate(larguras, start=1):
        ws.column_dimensions[get_column_letter(i)].width = w


def ler_precos() -> dict:
    return json.loads(PRECOS.read_text(encoding="utf-8"))


def ler_funil() -> dict:
    """Mix real de leads por tier + estado do funil. Só leitura."""
    if not BANCO.exists():
        return {"erro": f"banco não encontrado em {BANCO}", "por_tier": {}, "status": {}}
    con = sqlite3.connect(f"file:{BANCO}?mode=ro", uri=True)
    try:
        por_tier = {t: 0 for t in TIERS}
        sem_tier = 0
        for tier, n in con.execute(
                "SELECT tier, COUNT(*) FROM tracker_prospects GROUP BY tier"):
            if tier in por_tier:
                por_tier[tier] = n
            else:
                # prospect sem tier NÃO pode sumir da conta: some da soma por tier,
                # continua na soma por status, e a planilha passa a mostrar dois
                # totais diferentes pra mesma tabela. Ninguém confia na terceira aba
                # depois de ver isso.
                sem_tier += n
        status = dict(con.execute(
            "SELECT COALESCE(NULLIF(status,''),'(vazio)'), COUNT(*) "
            "FROM tracker_prospects GROUP BY 1"))
        fechados = con.execute(
            "SELECT COUNT(*) FROM tracker_prospects "
            "WHERE COALESCE(NULLIF(valor_fechado,''),'0') NOT IN ('0')").fetchone()[0]
        total = con.execute("SELECT COUNT(*) FROM tracker_prospects").fetchone()[0]
        return {"por_tier": por_tier, "sem_tier": sem_tier, "status": status,
                "fechados": fechados, "total": total}
    finally:
        con.close()


# ---------------------------------------------------------------- abas


def aba_leia(wb, precos, funil):
    ws = wb.create_sheet("Leia primeiro")
    _larguras(ws, [26, 18, 18, 18, 18, 18])
    L = 1
    L = _titulo(ws, L, "Modelagem financeira JPOS")
    L = _nota(ws, L, f"Gerada em {date.today():%d/%m/%Y} por modelagem_financeira.py. "
                     f"Preços lidos de precos.json (fonte única); funil lido de leads.db. "
                     f"Para atualizar, rode o script de novo — não edite os números à mão.")
    L += 1
    L = _titulo(ws, L, "O que é medido e o que é premissa sua")
    L = _cabecalho(ws, L, ["", "De onde vem", "Confiança"])
    for rotulo, origem, conf in [
        ("Preço por tier e upsell", "precos.json", "Medido — é a fonte única"),
        ("Mix de leads por tier", "leads.db / tracker_prospects", "Medido — contagem real"),
        ("Custo do vídeo IA", "job real medido (n=1)", "Medido, amostra pequena"),
        ("Custo do Calendar", "service account, sem cota paga", "Medido — R$0 por cliente"),
        ("TAXA DE CONVERSÃO", "VOCÊ preenche", "LACUNA — não existe no sistema"),
        ("Taxa de anexo do upsell", "VOCÊ preenche", "LACUNA — não existe no sistema"),
    ]:
        ws.cell(L, 1, rotulo).font = Font(bold=rotulo.isupper(), size=10)
        ws.cell(L, 2, origem).font = Font(size=10)
        ws.cell(L, 3, conf).font = Font(size=10)
        for i in (1, 2, 3):
            ws.cell(L, i).border = GRADE
            if "LACUNA" in conf:
                ws.cell(L, i).fill = ALERTA
        L += 1
    L += 1
    fechados = funil.get("fechados", 0)
    total = funil.get("total", 0)
    L = _nota(ws, L, (
        f"POR QUE A CONVERSÃO É LACUNA E NÃO ESTIMATIVA: o tracker tem {total} prospects "
        f"e {fechados} vendas com valor fechado. Não é amostra pequena — é amostra "
        f"nenhuma. Qualquer taxa que eu escrevesse aqui seria chute com aparência de "
        f"dado, e em duas semanas viraria 'a planilha diz que dá R$X'. Preencha a sua "
        f"premissa na aba Projeção; a tabela de sensibilidade ao lado mostra o que "
        f"acontece se você errar pra mais ou pra menos."), alerta=True)
    L += 1
    L = _titulo(ws, L, "Como usar")
    for txt in ["1. Aba Catálogo: confira se o preço bate com o que você vende hoje.",
                "2. Aba Funil real: é o seu estoque de leads, por tier, medido agora.",
                "3. Aba Projeção: preencha as células AMARELAS. O resto é fórmula.",
                "4. Aba Upsell Calendar: o cenário específico do módulo pra T1/T2."]:
        ws.cell(L, 1, txt).font = Font(size=10)
        ws.merge_cells(start_row=L, start_column=1, end_row=L, end_column=6)
        L += 1
    return ws


def aba_catalogo(wb, precos):
    ws = wb.create_sheet("Catálogo")
    _larguras(ws, [10, 20, 46, 14, 14, 16, 16])
    L = 1
    L = _titulo(ws, L, "Catálogo — tiers", 7)
    L = _cabecalho(ws, L, ["Tier", "Nome", "O que entrega", "Setup",
                           "Mensal", "1º pagamento", "12 meses"])
    primeira = L
    for t in precos["tiers"]:
        ws.cell(L, 1, t["id"]).font = Font(bold=True)
        ws.cell(L, 2, t["nome"])
        ws.cell(L, 3, "; ".join(t["entrega"])).alignment = Alignment(wrap_text=True, vertical="top")
        ws.cell(L, 4, t.get("setup") or 0).number_format = MOEDA_OU_TRACO
        ws.cell(L, 5, t.get("mensal") or 0).number_format = MOEDA_OU_TRACO
        # 1º pagamento = setup + 1ª mensalidade: é o número que o dono ouve na porta
        ws.cell(L, 6, f"=D{L}+E{L}").number_format = MOEDA
        ws.cell(L, 7, f"=D{L}+E{L}*12").number_format = MOEDA
        for i in (6, 7):
            ws.cell(L, i).fill = CALC
        for i in range(1, 8):
            ws.cell(L, i).border = GRADE
        ws.row_dimensions[L].height = 32
        L += 1
    ws.cell(L, 3, "MÉDIA").font = Font(bold=True)
    for col in (4, 5, 6, 7):
        c = get_column_letter(col)
        ws.cell(L, col, f"=AVERAGE({c}{primeira}:{c}{L-1})").number_format = MOEDA
        ws.cell(L, col).font = Font(bold=True)
        ws.cell(L, col).fill = CALC
    L += 2

    L = _titulo(ws, L, "Upsells", 7)
    L = _cabecalho(ws, L, ["", "Item", "Resumo", "Setup", "Mensal", "Para quem", "12 meses"])
    for u in precos["upsells"]:
        em = u.get("disponivel_em") or list(TIERS)
        escopo = "qualquer plano" if set(em) >= set(TIERS) else "só " + " e ".join(
            x for x in TIERS if x in em)
        ws.cell(L, 2, u["nome"])
        ws.cell(L, 3, u.get("resumo", "")).alignment = Alignment(wrap_text=True, vertical="top")
        ws.cell(L, 4, u.get("setup") or 0).number_format = MOEDA_OU_TRACO
        ws.cell(L, 5, u.get("mensal") or 0).number_format = MOEDA_OU_TRACO
        ws.cell(L, 6, escopo)
        ws.cell(L, 7, f"=D{L}+E{L}*12").number_format = MOEDA
        ws.cell(L, 7).fill = CALC
        if u.get("provisorio"):
            for i in range(2, 8):
                ws.cell(L, i).fill = ALERTA
            ws.cell(L, 6, escopo + " — PROVISÓRIO, não vai pra material de cliente")
        for i in range(1, 8):
            ws.cell(L, i).border = GRADE
        ws.row_dimensions[L].height = 30
        L += 1
    L += 1
    L = _nota(ws, L, "O Calendar+e-mail vale só pra T1/T2 porque T3 e T4 já o entregam no "
                     "plano. Oferecer aos quatro seria cobrar duas vezes pela mesma peça.", 7)
    return ws


def aba_funil(wb, funil):
    ws = wb.create_sheet("Funil real")
    _larguras(ws, [16, 16, 16, 44, 16, 16])
    L = 1
    L = _titulo(ws, L, "Funil real — medido agora, sem estimativa")
    L = _cabecalho(ws, L, ["Tier", "Leads", "% do funil", "Leitura"])
    por_tier = funil.get("por_tier", {})
    total = sum(por_tier.values()) or 1
    primeira = L
    leitura = {
        "T1": "Volume de entrada. Ticket baixo, fecha no mesmo dial.",
        "T2": "Onde está o funil de verdade — 2 em cada 3 leads.",
        "T3": "Poucos, mas é onde o Calendar vira argumento de venda.",
        "T4": "White glove. Cada um vale ~7 T1; não fecha por telefone.",
    }
    for t in TIERS:
        ws.cell(L, 1, t).font = Font(bold=True)
        ws.cell(L, 2, por_tier.get(t, 0))
        ws.cell(L, 3, f"=B{L}/SUM($B${primeira}:$B${primeira + 4})").number_format = PCT
        ws.cell(L, 3).fill = CALC
        ws.cell(L, 4, leitura[t]).alignment = Alignment(wrap_text=True)
        for i in range(1, 5):
            ws.cell(L, i).border = GRADE
        L += 1
    sem_tier = funil.get("sem_tier", 0)
    if sem_tier:
        ws.cell(L, 1, "(sem tier)").font = Font(italic=True)
        ws.cell(L, 2, sem_tier)
        ws.cell(L, 3, f"=B{L}/SUM($B${primeira}:$B${primeira + 4})").number_format = PCT
        ws.cell(L, 3).fill = CALC
        ws.cell(L, 4, "Não classificados. Aparecem aqui pro total bater com o "
                      "de status — some da soma por tier, mas existe no funil.")
        ws.cell(L, 4).alignment = Alignment(wrap_text=True)
        for i in range(1, 5):
            ws.cell(L, i).border = GRADE
        L += 1
    ws.cell(L, 1, "Total").font = Font(bold=True)
    ws.cell(L, 2, f"=SUM(B{primeira}:B{L-1})").font = Font(bold=True)
    ws.cell(L, 2).fill = CALC
    ws.cell(L, 2).border = GRADE
    L += 2

    L = _titulo(ws, L, "Estado do funil")
    L = _cabecalho(ws, L, ["Status", "Prospects"])
    for st, n in sorted(funil.get("status", {}).items(), key=lambda x: -x[1]):
        ws.cell(L, 1, st)
        ws.cell(L, 2, n)
        for i in (1, 2):
            ws.cell(L, i).border = GRADE
        L += 1
    L += 1
    L = _nota(ws, L, (
        f"Vendas com valor fechado registrado: {funil.get('fechados', 0)}. "
        f"É daqui que vem a lacuna de conversão — o funil está cheio e parado, "
        f"não cheio e convertendo mal. São coisas diferentes e só a segunda dá taxa."),
        alerta=True)
    return ws


def aba_projecao(wb, precos, funil):
    ws = wb.create_sheet("Projeção")
    _larguras(ws, [22, 14, 14, 16, 16, 18, 18])
    por_tier = funil.get("por_tier", {})
    preco = {t["id"]: t for t in precos["tiers"]}
    L = 1
    L = _titulo(ws, L, "Projeção de receita — modelo, não previsão", 7)
    L = _nota(ws, L, "Preencha só as células AMARELAS. Tudo o mais é fórmula. "
                     "Não há taxa de conversão medida no sistema (ver aba Leia primeiro).", 7)
    L += 1
    L = _cabecalho(ws, L, ["Tier", "Leads", "Conversão (você)", "Clientes",
                           "Setup total", "MRR", "Receita 12m"])
    primeira = L
    for t in TIERS:
        ws.cell(L, 1, t).font = Font(bold=True)
        ws.cell(L, 2, por_tier.get(t, 0))
        alvo = ws.cell(L, 3, None)                 # VAZIA de propósito
        alvo.fill = ENTRADA
        alvo.number_format = PCT
        ws.cell(L, 4, f"=B{L}*C{L}").number_format = '0.0'
        ws.cell(L, 5, f"=D{L}*{preco[t].get('setup') or 0}").number_format = MOEDA
        ws.cell(L, 6, f"=D{L}*{preco[t].get('mensal') or 0}").number_format = MOEDA_OU_TRACO
        ws.cell(L, 7, f"=E{L}+F{L}*12").number_format = MOEDA
        for i in (4, 5, 6, 7):
            ws.cell(L, i).fill = CALC
        for i in range(1, 8):
            ws.cell(L, i).border = GRADE
        L += 1
    ws.cell(L, 1, "TOTAL").font = Font(bold=True)
    for col in (4, 5, 6, 7):
        c = get_column_letter(col)
        ws.cell(L, col, f"=SUM({c}{primeira}:{c}{L-1})")
        ws.cell(L, col).number_format = '0.0' if col == 4 else MOEDA
        ws.cell(L, col).font = Font(bold=True)
        ws.cell(L, col).fill = CALC
        ws.cell(L, col).border = GRADE
    total_L = L
    L += 2

    L = _titulo(ws, L, "Sensibilidade — o que muda se você errar a premissa", 7)
    L = _nota(ws, L, "Isto NÃO é previsão. É a mesma conta rodada com taxas diferentes, "
                     "aplicada igual nos 4 tiers, pra mostrar a ordem de grandeza.", 7)
    L = _cabecalho(ws, L, ["Se a conversão for", "Clientes", "Setup total",
                           "MRR", "Receita 12m"])
    leads = {t: por_tier.get(t, 0) for t in TIERS}
    for taxa in (0.005, 0.01, 0.02, 0.05):
        clientes = sum(leads[t] * taxa for t in TIERS)
        setup = sum(leads[t] * taxa * (preco[t].get("setup") or 0) for t in TIERS)
        mrr = sum(leads[t] * taxa * (preco[t].get("mensal") or 0) for t in TIERS)
        ws.cell(L, 1, taxa).number_format = PCT
        ws.cell(L, 2, round(clientes, 1)).number_format = '0.0'
        ws.cell(L, 3, round(setup, 2)).number_format = MOEDA
        ws.cell(L, 4, round(mrr, 2)).number_format = MOEDA
        ws.cell(L, 5, f"=C{L}+D{L}*12").number_format = MOEDA
        ws.cell(L, 5).fill = CALC
        for i in range(1, 6):
            ws.cell(L, i).border = GRADE
        L += 1
    return ws, total_L


def aba_upsell(wb, precos, funil, linha_total_projecao):
    ws = wb.create_sheet("Upsell Calendar")
    _larguras(ws, [30, 16, 16, 18, 18, 18])
    up = next((u for u in precos["upsells"] if u["id"] == "calendar_email"), None)
    setup_up = (up or {}).get("setup") or 0
    mensal_up = (up or {}).get("mensal") or 0
    por_tier = funil.get("por_tier", {})
    L = 1
    L = _titulo(ws, L, "Cenário: Calendar+e-mail como upsell de T1/T2")
    L = _nota(ws, L, (
        f"O módulo é entrega core no T3/T4. Este cenário mede só o incremento em quem "
        f"está no T1/T2 e compraria a peça sem subir de plano. "
        f"Preço modelado: R$ {setup_up:,.0f} de setup + R$ {mensal_up:,.0f}/mês."
        .replace(",", ".")))
    L += 1
    L = _cabecalho(ws, L, ["", "T1", "T2", "Total"])
    ws.cell(L, 1, "Leads no funil").font = Font(bold=True)
    ws.cell(L, 2, por_tier.get("T1", 0))
    ws.cell(L, 3, por_tier.get("T2", 0))
    ws.cell(L, 4, f"=B{L}+C{L}").fill = CALC
    lin_leads = L
    L += 1
    ws.cell(L, 1, "Conversão do tier (você)").font = Font(bold=True)
    for col in (2, 3):
        ws.cell(L, col).fill = ENTRADA
        ws.cell(L, col).number_format = PCT
    lin_conv = L
    L += 1
    ws.cell(L, 1, "Clientes no tier").font = Font(bold=True)
    for col in (2, 3):
        c = get_column_letter(col)
        ws.cell(L, col, f"={c}{lin_leads}*{c}{lin_conv}").number_format = '0.0'
        ws.cell(L, col).fill = CALC
    ws.cell(L, 4, f"=B{L}+C{L}").number_format = '0.0'
    ws.cell(L, 4).fill = CALC
    lin_cli = L
    L += 1
    ws.cell(L, 1, "% que compra o Calendar (você)").font = Font(bold=True)
    for col in (2, 3):
        ws.cell(L, col).fill = ENTRADA
        ws.cell(L, col).number_format = PCT
    lin_anexo = L
    L += 1
    ws.cell(L, 1, "Compram o módulo").font = Font(bold=True)
    for col in (2, 3):
        c = get_column_letter(col)
        ws.cell(L, col, f"={c}{lin_cli}*{c}{lin_anexo}").number_format = '0.0'
        ws.cell(L, col).fill = CALC
    ws.cell(L, 4, f"=B{L}+C{L}").number_format = '0.0'
    ws.cell(L, 4).fill = CALC
    lin_compram = L
    L += 2

    L = _titulo(ws, L, "Receita incremental do módulo")
    L = _cabecalho(ws, L, ["", "Valor"])
    for rotulo, formula in [
        ("Setup (uma vez)", f"=D{lin_compram}*{setup_up}"),
        ("MRR incremental", f"=D{lin_compram}*{mensal_up}"),
        ("Receita 12 meses", f"=D{lin_compram}*{setup_up}+D{lin_compram}*{mensal_up}*12"),
    ]:
        ws.cell(L, 1, rotulo).font = Font(bold=True)
        ws.cell(L, 2, formula).number_format = MOEDA
        ws.cell(L, 2).fill = CALC
        for i in (1, 2):
            ws.cell(L, i).border = GRADE
        L += 1
    L += 1
    L = _nota(ws, L, (
        "MARGEM: o custo marginal deste módulo é R$ 0,00 por cliente — service account, "
        "sem cota paga por evento, sem instância nova. O único custo é o tempo de "
        "provisionar a agenda e o dono aceitar o convite, que é o que o setup cobre. "
        "Então praticamente toda esta linha é margem — diferente do vídeo IA, que tem "
        "custo de crédito por peça."))
    L = _nota(ws, L, (
        "SENSIBILIDADE: o número que manda aqui é o '% que compra o Calendar'. Ele "
        "também não existe no sistema — nenhum upsell foi vendido ainda. Trate as duas "
        "células amarelas como a sua aposta, não como dado."), alerta=True)
    return ws


def main() -> int:
    precos = ler_precos()
    funil = ler_funil()
    wb = Workbook()
    wb.remove(wb.active)
    aba_leia(wb, precos, funil)
    aba_catalogo(wb, precos)
    aba_funil(wb, funil)
    _, total_L = aba_projecao(wb, precos, funil)
    aba_upsell(wb, precos, funil, total_L)
    saida = Path(sys.argv[1]) if len(sys.argv) > 1 else (
        Path("/root/jpos-entregaveis") / f"MODELAGEM_FINANCEIRA_{date.today():%Y-%m-%d}.xlsx")
    saida.parent.mkdir(parents=True, exist_ok=True)
    wb.save(saida)
    print(f"planilha: {saida}")
    print(f"  abas ...... {', '.join(wb.sheetnames)}")
    print(f"  tiers ..... {len(precos['tiers'])} | upsells {len(precos['upsells'])}")
    print(f"  funil ..... {funil.get('total', 0)} prospects "
          f"({sum(funil.get('por_tier', {}).values())} com tier + "
          f"{funil.get('sem_tier', 0)} sem), {funil.get('fechados', 0)} vendas fechadas")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
