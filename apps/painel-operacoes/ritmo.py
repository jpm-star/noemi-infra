"""Contador de ritmo: quanto falta pra meta e quanto tem que sair POR DIA ÚTIL.

A meta é R$50.000 em 27 dias úteis. O número que muda decisão não é o total — é o
"quanto por dia a partir de HOJE", porque ele sobe sozinho a cada dia que passa sem
venda. Ver esse número subir é o que faz mudar o plano no dia 5 em vez do dia 20.

HONESTIDADE DO NÚMERO. Sem cliente fechado não existe taxa de conversão, então tudo que
depender dela é chute. Este módulo separa os dois estados e diz qual está mostrando:
  · ESTIMADA  — usa premissa (ticket do cartucho, conversão suposta). Aviso na cara.
  · CALIBRADA — só depois de `MIN_CONTATOS_CALIBRAR` contatos reais registrados no
    prospeccao_log; aí a conversão vem do que ACONTECEU, não do que se esperava.
Um painel que mostra estimativa com cara de fato é pior que painel nenhum: ele dá
confiança onde não há informação.

ponytail: funções puras + leitura do banco que já existe. Sem tabela nova — o valor
fechado mora numa coluna aditiva de tracker_prospects, no mesmo padrão de `demo_url`.
"""
from __future__ import annotations

import os
import sqlite3
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

SP = ZoneInfo("America/Sao_Paulo")

META_REAIS = float(os.environ.get("META_REAIS", "50000"))
DIAS_UTEIS_META = int(os.environ.get("DIAS_UTEIS_META", "27"))
INICIO = os.environ.get("META_INICIO", "2026-08-07")   # 1º dia útil da contagem
MIN_CONTATOS_CALIBRAR = 10   # abaixo disto, taxa de conversão é opinião

# Feriados nacionais que caem dentro da janela. Lista curta e explícita: um feriado
# esquecido inflaciona os dias úteis e faz a meta diária sair menor do que precisa ser.
FERIADOS = {
    date(2026, 9, 7), date(2026, 10, 12), date(2026, 11, 2),
    date(2026, 11, 15), date(2026, 11, 20), date(2026, 12, 25),
}

# Ticket usado enquanto não há venda real. Premissa DECLARADA, não fato — é exatamente
# por isso que o painel mostra "estimada" enquanto ela estiver em uso.
TICKET_PREMISSA = float(os.environ.get("TICKET_PREMISSA", "1200"))


def _db() -> sqlite3.Connection:
    p = Path(os.environ.get("LEADS_DB", str(Path(__file__).resolve().parents[2] / "data" / "leads.db")))
    c = sqlite3.connect(p, timeout=10)
    c.row_factory = sqlite3.Row
    return c


def dia_util(d: date) -> bool:
    return d.weekday() < 5 and d not in FERIADOS


def uteis_entre(inicio: date, fim: date) -> int:
    """Dias úteis de `inicio` até `fim`, ambos incluídos. 0 se fim < inicio."""
    n, d = 0, inicio
    while d <= fim:
        n += dia_util(d)
        d += timedelta(days=1)
    return n


def fim_da_janela(inicio: date | None = None, uteis: int = DIAS_UTEIS_META) -> date:
    """A data do N-ésimo dia útil. Anda dia a dia porque feriado não é regra fechada."""
    d = inicio or date.fromisoformat(INICIO)
    restam = uteis
    while True:
        if dia_util(d):
            restam -= 1
            if restam <= 0:
                return d
        d += timedelta(days=1)


def _fechado() -> tuple[float, int]:
    """(R$ somado, nº de clientes) já fechados. `valor_fechado` é coluna ADITIVA: banco
    sem ela devolve 0 em vez de quebrar o painel (mesmo padrão de `demo_url`)."""
    try:
        with _db() as c:
            cols = {r[1] for r in c.execute("PRAGMA table_info(tracker_prospects)")}
            if "valor_fechado" not in cols:
                return 0.0, 0
            r = c.execute("SELECT COALESCE(SUM(valor_fechado),0) v, COUNT(*) n "
                          "FROM tracker_prospects WHERE COALESCE(valor_fechado,0) > 0").fetchone()
            return float(r["v"] or 0), int(r["n"] or 0)
    except sqlite3.Error:
        return 0.0, 0


def _contatos_reais() -> int:
    try:
        with _db() as c:
            return int(c.execute("SELECT COUNT(*) FROM prospeccao_log").fetchone()[0])
    except sqlite3.Error:
        return 0


def garantir_coluna() -> bool:
    """Cria `valor_fechado` se faltar. Idempotente; True se criou agora."""
    try:
        with _db() as c:
            if "valor_fechado" in {r[1] for r in c.execute("PRAGMA table_info(tracker_prospects)")}:
                return False
            c.execute("ALTER TABLE tracker_prospects ADD COLUMN valor_fechado REAL")
            c.commit()
            return True
    except sqlite3.Error:
        return False


def painel(hoje: date | None = None) -> dict:
    """Tudo que o widget mostra, já calculado. Função pura sobre o banco."""
    hoje = hoje or datetime.now(SP).date()
    inicio = date.fromisoformat(INICIO)
    fim = fim_da_janela(inicio)
    restantes = uteis_entre(max(hoje, inicio), fim)
    fechado, clientes = _fechado()
    contatos = _contatos_reais()
    falta = max(META_REAIS - fechado, 0.0)
    calibrada = contatos >= MIN_CONTATOS_CALIBRAR
    # a divisão por dia é o número que muda decisão; sem dia útil sobrando ele não existe
    por_dia = round(falta / restantes, 2) if restantes else None
    return {
        "meta": META_REAIS, "fechado": round(fechado, 2), "falta": round(falta, 2),
        "clientes_fechados": clientes,
        "inicio": inicio.isoformat(), "fim": fim.isoformat(),
        "dias_uteis_total": DIAS_UTEIS_META,
        "dias_uteis_restantes": restantes,
        "dias_uteis_corridos": max(uteis_entre(inicio, min(hoje, fim)) - (1 if dia_util(hoje) and hoje <= fim else 0), 0),
        "por_dia_util": por_dia,
        "pct": round(fechado / META_REAIS * 100, 1) if META_REAIS else 0.0,
        "estado": "calibrada" if calibrada else "estimada",
        "contatos_reais": contatos,
        "faltam_pra_calibrar": max(MIN_CONTATOS_CALIBRAR - contatos, 0),
        # premissa só aparece enquanto for premissa — some quando houver venda de verdade
        "clientes_necessarios_premissa": (
            None if calibrada or not TICKET_PREMISSA else int(-(-falta // TICKET_PREMISSA))),
        "ticket_premissa": TICKET_PREMISSA if not calibrada else None,
        "aviso": ("" if calibrada else
                  f"Número ESTIMADO: ainda não há venda fechada pra calcular conversão. "
                  f"Calibra sozinho depois de {MIN_CONTATOS_CALIBRAR} contatos "
                  f"registrados (faltam {max(MIN_CONTATOS_CALIBRAR - contatos, 0)})."),
    }


if __name__ == "__main__":
    assert dia_util(date(2026, 8, 7)) and not dia_util(date(2026, 8, 8))
    assert not dia_util(date(2026, 9, 7)), "7 de setembro é feriado"
    assert uteis_entre(date(2026, 8, 7), date(2026, 8, 7)) == 1
    assert uteis_entre(date(2026, 8, 10), date(2026, 8, 14)) == 5
    assert uteis_entre(date(2026, 8, 14), date(2026, 8, 10)) == 0, "intervalo invertido = 0"
    f = fim_da_janela(date(2026, 8, 7), 27)
    assert uteis_entre(date(2026, 8, 7), f) == 27, uteis_entre(date(2026, 8, 7), f)
    garantir_coluna()
    d = painel(date(2026, 8, 6))
    assert d["estado"] == "estimada" and d["aviso"]
    print(f"ritmo OK — janela {d['inicio']} → {d['fim']} ({d['dias_uteis_total']} úteis)")
    print(f"  meta R$ {d['meta']:,.0f} · fechado R$ {d['fechado']:,.0f} ({d['pct']}%) · "
          f"restam {d['dias_uteis_restantes']} dias úteis")
    print(f"  precisa de R$ {d['por_dia_util']:,.2f} por dia útil  [{d['estado']}]")
    print(f"  premissa: {d['clientes_necessarios_premissa']} clientes a "
          f"R$ {d['ticket_premissa']:,.0f}")
    print(f"  {d['aviso']}")
