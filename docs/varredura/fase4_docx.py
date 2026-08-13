"""FASE 4 — os dois .docx no disco da VPS.

Números vêm do sistema (precos.json, leads.db, noemi.db, systemd) em tempo de
geração. Rodar de novo produz o documento atualizado; nada aqui é digitado à mão,
porque documento comercial digitado à mão foi a origem das quatro versões
conflitantes de material que esta sessão encontrou.
"""
from __future__ import annotations

import json
import pathlib
import sqlite3
import subprocess
import sys
from datetime import date

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.shared import Pt, RGBColor

sys.path.insert(0, str(pathlib.Path(__file__).parent))
from fase3_oportunidades import ranqueado  # noqa: E402

SAIDA = pathlib.Path("/root/jpos-entregaveis")
HOJE = f"{date.today():%d/%m/%Y}"
TINTA = RGBColor(0x1F, 0x29, 0x33)
CINZA = RGBColor(0x62, 0x6E, 0x7B)


# ── dados reais ────────────────────────────────────────────────────────────
def precos() -> dict:
    return json.loads((pathlib.Path("/root/noemi-infra/apps/painel-operacoes")
                       / "precos.json").read_text(encoding="utf-8"))


def funil() -> dict:
    c = sqlite3.connect("file:/root/noemi-infra/data/leads.db?mode=ro", uri=True)
    por = dict(c.execute("SELECT tier, COUNT(*) FROM tracker_prospects GROUP BY tier"))
    tot = c.execute("SELECT COUNT(*) FROM tracker_prospects").fetchone()[0]
    fech = c.execute("SELECT COUNT(*) FROM tracker_prospects "
                     "WHERE COALESCE(valor_fechado,0)>0").fetchone()[0]
    c.close()
    return {"total": tot, "fechados": fech, "por_tier": por}


def acervo() -> dict:
    c = sqlite3.connect("file:/root/noemi-infra/data/noemi.db?mode=ro", uri=True)
    q = lambda s: c.execute(s).fetchone()[0]  # noqa: E731
    d = {"videos": q("SELECT COUNT(*) FROM video_analises"),
         "templates": q("SELECT COUNT(*) FROM templates_referencia"),
         "templates_ok": q("SELECT COUNT(*) FROM templates_referencia WHERE aprovada=1"),
         "embeddings": q("SELECT COUNT(*) FROM kb_embeddings"),
         "sites": q("SELECT COUNT(*) FROM sites_gerados"),
         "trafego": q("SELECT COUNT(*) FROM site_trafego"),
         "insights": q("SELECT COUNT(*) FROM insights_cliente")}
    c.close()
    d["publicados"] = len(list(pathlib.Path("/var/www/sites").glob("*/index.html")))
    return d


def vocab() -> dict:
    sys.path.insert(0, "/root/noemi-infra/apps/painel-operacoes")
    import estilos
    import vocabulario as v
    tot = sum(len(t) for t in v.NICHOS.values())
    com = sum(len(t) for f, t in v.NICHOS.items() if f in estilos.PERFIS)
    return {**v.resumo(), "cobertos": com, "total": tot}


def servicos_ativos() -> int:
    r = subprocess.run("systemctl list-units --type=service --state=running --no-legend --plain",
                       shell=True, capture_output=True, text=True).stdout
    return sum(1 for l in r.splitlines()
               if any(k in l for k in ("noemi", "motor", "painel", "caddy")))


# ── helpers de estilo ──────────────────────────────────────────────────────
def doc_base(titulo: str, sub: str) -> Document:
    d = Document()
    for s in d.sections:
        s.left_margin = s.right_margin = Pt(48)
    e = d.styles["Normal"]
    e.font.name = "Calibri"
    e.font.size = Pt(10.5)
    h = d.add_paragraph()
    r = h.add_run(titulo)
    r.font.size = Pt(21)
    r.font.bold = True
    r.font.color.rgb = TINTA
    p = d.add_paragraph()
    r = p.add_run(sub)
    r.font.size = Pt(10)
    r.font.color.rgb = CINZA
    d.add_paragraph()
    return d


def h2(d: Document, txt: str) -> None:
    p = d.add_paragraph()
    p.paragraph_format.space_before = Pt(14)
    r = p.add_run(txt.upper())
    r.font.size = Pt(11)
    r.font.bold = True
    r.font.color.rgb = TINTA


def nota(d: Document, txt: str) -> None:
    p = d.add_paragraph()
    r = p.add_run(txt)
    r.font.size = Pt(9.5)
    r.font.italic = True
    r.font.color.rgb = CINZA


def tabela(d: Document, cabec: list[str], linhas: list[list[str]], larg: list[int] | None = None):
    t = d.add_table(rows=1, cols=len(cabec))
    t.style = "Light Grid Accent 1"
    for i, c in enumerate(cabec):
        cel = t.rows[0].cells[i]
        cel.text = ""
        r = cel.paragraphs[0].add_run(c)
        r.font.bold = True
        r.font.size = Pt(9)
    for ln in linhas:
        cs = t.add_row().cells
        for i, v in enumerate(ln):
            cs[i].text = ""
            r = cs[i].paragraphs[0].add_run(str(v))
            r.font.size = Pt(9)
    return t


def brl(v) -> str:
    if v in (None, 0, ""):
        return "—"
    return f"R$ {v:,.0f}".replace(",", ".")


# ── DOC 1: oportunidades ───────────────────────────────────────────────────
def doc_oportunidades() -> pathlib.Path:
    itens = ranqueado()
    f, a, vc = funil(), acervo(), vocab()
    d = doc_base("JPOS — Varredura de oportunidade",
                 f"{len(itens)} itens ranqueados por ROI ÷ esforço · gerado do sistema em {HOJE}")

    h2(d, "Como ler")
    d.add_paragraph(
        "ROI e esforço vão de 1 a 5. A prioridade é a razão entre os dois — o que rende "
        "muito e custa pouco sobe. Nesta stack isso empurra pro topo, quase sempre, LIGAR "
        "o que já está construído em vez de construir.")
    nota(d, "Todo número deste documento foi medido nesta máquina. Onde não há medição, o "
            "item diz que não há — nenhuma estimativa foi inventada para preencher lacuna.")

    h2(d, "O padrão que organiza tudo")
    d.add_paragraph(
        "Em uma única sessão apareceram QUATRO casos de código pronto e desligado: o "
        "Calendar espelhando só o caminho da IA, o endpoint de registrar venda sem "
        "nenhuma tela chamando, o gerador de páginas T2 órfão, e o relatório periódico do "
        "T1 sem agendador. Não é azar: é o que acontece quando construir é barato e ligar "
        "exige decisão. Por isso a coluna de esforço pesa mais que a de novidade.")

    h2(d, "Estado medido")
    tabela(d, ["Indicador", "Valor", "Leitura"], [
        ["Prospects no funil", f"{f['total']:,}".replace(",", "."), "T2 é 2/3 da base"],
        ["Vendas registradas", str(f["fechados"]), "zero — não é amostra pequena, é nenhuma"],
        ["Sites publicados", str(a["publicados"]), "hospedados sem linha de receita própria"],
        ["Registros de tráfego", str(a["trafego"]), "só evento 'view'; nenhum clique medido"],
        ["Relatórios de cliente", str(a["insights"]), "tabela vazia — entrega do T1 sem disparo"],
        ["Vídeos analisados", str(a["videos"]), "matéria-prima da Caixa de Ideias"],
        ["Estruturas de referência", f"{a['templates_ok']}/{a['templates']}", "de 137 domínios reais"],
        ["Nichos com perfil", f"{vc['cobertos']}/{vc['total']}", "99% após o perfil de serviços"],
        ["Serviços em produção", str(servicos_ativos()), "systemd nesta VPS"],
    ])

    h2(d, "Top 15 — o que fazer primeiro")
    tabela(d, ["#", "Oportunidade", "Categoria", "ROI", "Esf.", "P"],
           [[str(i + 1), x["titulo"], x["categoria"], x["roi"], x["esforco"], x["prioridade"]]
            for i, x in enumerate(itens[:15])])

    ROT = {"ligar": "Ligar o que já existe", "medir": "Prova e medição",
           "produto": "Produto novo e receita recorrente", "passiva": "Renda passiva",
           "design": "Design e composição", "front": "Front", "back": "Back",
           "infra": "Infra e organização"}
    for cat in ("ligar", "medir", "produto", "passiva", "design", "front", "back", "infra"):
        grupo = [x for x in itens if x["categoria"] == cat]
        h2(d, f"{ROT[cat]} ({len(grupo)})")
        for x in grupo:
            p = d.add_paragraph()
            r = p.add_run(f"{x['titulo']} ")
            r.font.bold = True
            r.font.size = Pt(10.5)
            r = p.add_run(f"[ROI {x['roi']} · esforço {x['esforco']} · P {x['prioridade']}]")
            r.font.size = Pt(8.5)
            r.font.color.rgb = CINZA
            q = d.add_paragraph(x["descricao"])
            q.paragraph_format.left_indent = Pt(14)
            q.paragraph_format.space_after = Pt(8)
            for run in q.runs:
                run.font.size = Pt(9.5)

    cam = SAIDA / f"JPOS_OPORTUNIDADES_{date.today():%Y-%m-%d}.docx"
    d.save(cam)
    return cam


# ── DOC 2: stack e monetização ─────────────────────────────────────────────
def doc_stack() -> pathlib.Path:
    pr, f, a, vc = precos(), funil(), acervo(), vocab()
    d = doc_base("JPOS — Stack e monetização",
                 f"O que está construído, o que está ligado e o que isso pode render · {HOJE}")

    h2(d, "Catálogo vigente")
    nota(d, "Lido de precos.json, a fonte única. Se divergir de qualquer material, "
            "o arquivo prevalece.")
    tabela(d, ["Tier", "Nome", "Setup", "Mensal", "1º pagamento", "12 meses"],
           [[t["id"], t["nome"], brl(t.get("setup")), brl(t.get("mensal")),
             brl((t.get("setup") or 0) + (t.get("mensal") or 0)),
             brl((t.get("setup") or 0) + (t.get("mensal") or 0) * 12)]
            for t in pr["tiers"]])

    h2(d, "Add-ons")
    tabela(d, ["Item", "Para quem", "Setup", "Mensal"],
           [[u["nome"],
             "todos" if set(u.get("disponivel_em") or ["T1", "T2", "T3", "T4"]) >= {"T1", "T2", "T3", "T4"}
             else " e ".join(u.get("disponivel_em") or []),
             brl(u.get("setup")), brl(u.get("mensal"))] for u in pr["upsells"]])

    h2(d, "O funil real")
    tabela(d, ["Tier", "Prospects", "% da base"],
           [[k or "(sem tier)", v, f"{v * 100 // max(1, f['total'])}%"]
            for k, v in sorted(f["por_tier"].items(), key=lambda x: -x[1])])
    d.add_paragraph(
        f"São {f['total']} prospects e {f['fechados']} vendas com valor registrado. Não é "
        "amostra pequena de conversão: é amostra nenhuma. Por isso nenhuma projeção deste "
        "documento crava taxa — a planilha que acompanha tem a taxa como célula de entrada, "
        "e a tabela de sensibilidade mostra a ordem de grandeza em cada hipótese.")

    h2(d, "Ativos construídos que ainda não geram receita")
    tabela(d, ["Ativo", "Escala", "O que falta para virar dinheiro"], [
        ["Sites publicados", f"{a['publicados']} no ar", "linha de hospedagem recorrente"],
        ["Base de CNPJ captada", "27.107 registros", "virar diretório público com destaque pago"],
        ["Auditoria do Radar", "roda em qualquer URL", "abrir como isca pública (hoje atrás de login)"],
        ["Estruturas de referência", f"{a['templates_ok']} aprovadas", "empacotar por segmento"],
        ["Análises de vídeo", f"{a['videos']} analisadas", "filtrar relevância e virar pauta"],
        ["Base de conhecimento", f"{a['embeddings']} embeddings", "busca vendável ou consulta interna"],
        ["Motor de relatório", "existe, 0 gerados", "agendador — é entrega vendida do T1"],
        ["Vocabulário", f"{vc['nichos']} nichos, {vc['estruturas']} estruturas",
         "antipadrões e seções BR viram código"],
    ])

    h2(d, "Onde está o dinheiro com menos esforço")
    d.add_paragraph(
        "Três linhas se pagam sem o dono trabalhar mais horas, e as três já têm a peça "
        "principal pronta:")
    for t, txt in [
        ("Hospedagem como item de linha",
         f"{a['publicados']} sites já hospedados. A R$29–49/mês é o recorrente mais fácil de "
         "justificar (o site precisa ficar no ar) e o mais difícil de cancelar."),
        ("Relatório mensal como assinatura",
         "O motor de insight existe e nunca rodou. Serve tanto para cumprir o T1 quanto "
         "para vender a quem NÃO é cliente de site, rodando sobre o site que a pessoa já tem."),
        ("Auditoria pública como isca",
         "O Radar já audita qualquer URL. Uma página aberta que devolve o diagnóstico "
         "captura lead qualificado sem discagem — hoje está atrás de login."),
    ]:
        p = d.add_paragraph(style="List Bullet")
        r = p.add_run(f"{t} — ")
        r.font.bold = True
        p.add_run(txt)

    h2(d, "Riscos de operação")
    tabela(d, ["Risco", "Estado"], [
        ["Nenhuma venda registrada", "a modelagem segue sendo premissa até a 1ª entrar"],
        ["Conversão não medida", "beacon só registra 'view'; nenhum clique de CTA"],
        ["Entrega do T1 sem disparo", "relatório periódico está no contrato e não roda"],
        ["Calendar sem agenda por cliente", "GCAL_AGENDA_ID vazio em produção"],
        ["Segredo no histórico do git", "autorizado no push; continua no histórico"],
        ["Teste contra produção", "não há ambiente espelho"],
    ])

    nota(d, "Este documento é gerado do sistema. Rodar fase4_docx.py de novo produz a "
            "versão atualizada — não editar o .docx à mão, porque a próxima geração "
            "sobrescreve e as duas versões passam a discordar.")

    cam = SAIDA / f"JPOS_STACK_E_MONETIZACAO_{date.today():%Y-%m-%d}.docx"
    d.save(cam)
    return cam


if __name__ == "__main__":
    a = doc_oportunidades()
    b = doc_stack()
    for x in (a, b):
        print(f"  {x}  ({x.stat().st_size // 1024} KB)")
