"""Memória das decisões de composição visual: o que o motor escolheu, por quê, e se colou.

POR QUE EXISTE: o motor passou a COMPOR (principal + acentos por seção) em vez de
aplicar um estilo só. Composição sem memória é chute repetido — a mesma escolha que o
operador rejeitou ontem volta amanhã, e ninguém consegue dizer se o motor está
melhorando ou andando em círculo.

O SINAL. Não existe hoje "essa composição fechou venda": ligar isso exigiria
lead_id -> CRM -> status de pagamento, e com a carteira atual o N é perto de zero.
Aprender com N=0 é inventar métrica e chamar de dado.

O que EXISTE e é honesto: o botão "Gerar outro". Clicar nele é o operador dizendo
"não gostei desta composição" — rejeição real, medida, de graça, no momento em que
ela acontece. Composição que sobreviveu sem "Gerar outro" foi aceita; a que veio antes
de um "Gerar outro" foi recusada. É sinal fraco, e é rotulado como fraco em todo lugar
que aparece.

DUAS TRAVAS contra virar superstição:
  1. Um par só entra na lista de evitar com >= MIN_REJEICOES rejeições. Uma rejeição é
     gosto do dia, não padrão.
  2. `evitar` NUNCA proíbe: se a filtragem esvaziar a composição, o motor usa a escolha
     original e registra o motivo. Memória que zera o resultado é pior que memória
     nenhuma.
"""
from __future__ import annotations

import json
import logging
import sqlite3
from datetime import datetime, timezone

log = logging.getLogger("painel.memoria_estilo")

# 2 = o mínimo que distingue padrão de gosto do dia. Acima disso a lista demora demais
# pra reagir; abaixo, uma rejeição isolada vira regra.
MIN_REJEICOES = 2

_DDL = """
CREATE TABLE IF NOT EXISTS estilo_decisoes (
  id        INTEGER PRIMARY KEY AUTOINCREMENT,
  slug      TEXT    NOT NULL,
  nicho     TEXT    NOT NULL DEFAULT '',
  tier      TEXT    NOT NULL DEFAULT '',
  semente   INTEGER NOT NULL DEFAULT 0,
  variacao  INTEGER NOT NULL DEFAULT 0,
  composicao TEXT   NOT NULL,
  rejeitada INTEGER NOT NULL DEFAULT 0,
  quando    TEXT    NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_estilo_nicho ON estilo_decisoes(nicho);
CREATE INDEX IF NOT EXISTS ix_estilo_slug  ON estilo_decisoes(slug, variacao);
"""


def _conn() -> sqlite3.Connection:
    """Mesma conexão do resto do painel. O sys.path é garantido AQUI porque este
    módulo não pode depender de quem importou primeiro — `criacao` já prepara o
    caminho, mas o self-check e o endpoint de placar entram sozinhos."""
    import sys
    from pathlib import Path
    pkgs = str(Path(__file__).resolve().parents[2] / "packages")
    if pkgs not in sys.path:
        sys.path.insert(0, pkgs)
    from shared_core.storage import db
    c = db.conn()
    c.executescript(_DDL)
    return c


def _pares(decisoes: list[dict]) -> list[str]:
    """['faq:skeuomorphism', ...] — a unidade que se aprende é o PAR seção+estilo.

    Não a composição inteira: rejeitar "minimal + skeuomorphism no faq" quase nunca é
    rejeitar o minimal, é rejeitar o skeuomorphism naquele lugar. Guardar a composição
    inteira como chave faria cada rejeição ensinar quase nada.
    """
    return [f"{d.get('alvo')}:{d.get('estilo')}" for d in (decisoes or [])
            if d.get("alvo") and d.get("alvo") != "página" and d.get("estilo")]


def registrar(slug: str, nicho: str, tier: str, semente: int, variacao: int,
              decisoes: list[dict]) -> None:
    """Grava a decisão. Nunca levanta — memória não pode derrubar geração de site."""
    try:
        with _conn() as c:
            # "Gerar outro" = a composição ANTERIOR deste mesmo slug foi recusada.
            # É o sinal inteiro do sistema: chega no momento exato da rejeição, sem
            # perguntar nada a ninguém.
            if variacao > 0:
                c.execute("UPDATE estilo_decisoes SET rejeitada=1 "
                          "WHERE slug=? AND variacao<? AND rejeitada=0", (slug, variacao))
            c.execute(
                "INSERT INTO estilo_decisoes "
                "(slug,nicho,tier,semente,variacao,composicao,quando) VALUES (?,?,?,?,?,?,?)",
                (slug, (nicho or "").strip().lower(), (tier or "").upper(), int(semente),
                 int(variacao), json.dumps(decisoes or [], ensure_ascii=False),
                 datetime.now(timezone.utc).isoformat(timespec="seconds")))
    except Exception:  # noqa: BLE001 — registro é observabilidade, não caminho crítico
        log.warning("não consegui registrar a composição de %r", slug, exc_info=True)


def evitar(nicho: str, minimo: int = MIN_REJEICOES) -> list[str]:
    """Pares 'secao:estilo' que este nicho já rejeitou `minimo`+ vezes. [] se nada."""
    try:
        with _conn() as c:
            linhas = c.execute(
                "SELECT composicao FROM estilo_decisoes WHERE nicho=? AND rejeitada=1",
                ((nicho or "").strip().lower(),)).fetchall()
    except Exception:  # noqa: BLE001
        return []
    conta: dict[str, int] = {}
    for (comp,) in linhas:
        try:
            for par in _pares(json.loads(comp)):
                conta[par] = conta.get(par, 0) + 1
        except ValueError:
            continue
    return sorted(p for p, n in conta.items() if n >= minimo)


def placar(nicho: str = "") -> dict:
    """O que o painel mostra: quantas composições vingaram, quais pares caem mais.

    `aceita` aqui significa APENAS "o operador não pediu outra" — não significa que
    vendeu. O rótulo vai junto do número em toda a UI, senão vira métrica de vaidade.
    """
    try:
        with _conn() as c:
            onde, args = ("WHERE nicho=?", ((nicho or "").strip().lower(),)) if nicho else ("", ())
            linhas = c.execute(
                f"SELECT nicho,composicao,rejeitada FROM estilo_decisoes {onde}", args).fetchall()
    except Exception:  # noqa: BLE001
        return {"total": 0, "aceitas": 0, "rejeitadas": 0, "pares": [], "sinal": "sem dados"}

    conta: dict[str, dict] = {}
    aceitas = rejeitadas = 0
    for _n, comp, rej in linhas:
        rejeitadas += bool(rej)
        aceitas += not rej
        try:
            pares = _pares(json.loads(comp))
        except ValueError:
            continue
        for p in pares:
            d = conta.setdefault(p, {"par": p, "usos": 0, "rejeicoes": 0})
            d["usos"] += 1
            d["rejeicoes"] += bool(rej)
    pares = sorted(conta.values(), key=lambda d: (-d["rejeicoes"], -d["usos"]))
    return {"total": len(linhas), "aceitas": aceitas, "rejeitadas": rejeitadas,
            "pares": pares, "evitando": evitar(nicho) if nicho else [],
            "min_rejeicoes": MIN_REJEICOES,
            "sinal": "fraco — 'aceita' quer dizer que o operador não pediu outra, "
                     "não que fechou venda"}


def historico(slug: str) -> list[dict]:
    """As composições já tentadas para este site, da mais nova pra mais velha."""
    try:
        with _conn() as c:
            linhas = c.execute(
                "SELECT variacao,composicao,rejeitada,quando FROM estilo_decisoes "
                "WHERE slug=? ORDER BY id DESC", (slug,)).fetchall()
    except Exception:  # noqa: BLE001
        return []
    saida = []
    for v, comp, rej, quando in linhas:
        try:
            dec = json.loads(comp)
        except ValueError:
            dec = []
        saida.append({"variacao": v, "decisoes": dec, "rejeitada": bool(rej), "quando": quando})
    return saida


if __name__ == "__main__":
    import os
    import tempfile
    os.environ["NOEMI_DATA_DIR"] = tempfile.mkdtemp()

    D1 = [{"alvo": "página", "estilo": "minimal"}, {"alvo": "faq", "estilo": "skeuomorphism"}]
    D2 = [{"alvo": "página", "estilo": "minimal"}, {"alvo": "cta-final", "estilo": "brutalism"}]

    assert _pares(D1) == ["faq:skeuomorphism"], "o principal não é par aprendível"
    assert _pares([]) == [] and _pares(None) == []

    # 1ª composição aceita (ninguém pediu outra)
    registrar("site-a", "advocacia", "T2", 10, 0, D1)
    assert placar("advocacia")["aceitas"] == 1

    # o operador clica "Gerar outro" -> a anterior vira rejeitada
    registrar("site-a", "advocacia", "T2", 11, 1, D2)
    p = placar("advocacia")
    assert p["rejeitadas"] == 1 and p["aceitas"] == 1, p
    assert evitar("advocacia") == [], "1 rejeição é gosto do dia, não padrão"

    # segundo cliente do mesmo nicho rejeita o MESMO par -> aí vira padrão
    registrar("site-b", "advocacia", "T2", 20, 0, D1)
    registrar("site-b", "advocacia", "T2", 21, 1, D2)
    assert evitar("advocacia") == ["faq:skeuomorphism"], evitar("advocacia")

    # nicho diferente não herda a rejeição do vizinho
    assert evitar("clinica") == []

    h = historico("site-a")
    assert len(h) == 2 and h[0]["variacao"] == 1 and h[1]["rejeitada"] is True

    # banco quebrado degrada em silêncio: memória nunca derruba geração
    logging.disable(logging.CRITICAL)   # o traceback abaixo é ESPERADO; não poluir a saída
    os.environ["NOEMI_DATA_DIR"] = "/proc/impossivel/nao-da"
    assert evitar("advocacia") == [] and placar()["total"] == 0
    registrar("site-c", "x", "T2", 1, 0, D1)   # não levanta

    print("memoria_estilo OK — par seção:estilo é a unidade, 'Gerar outro' marca a "
          f"anterior, >= {MIN_REJEICOES} rejeições vira padrão, banco morto degrada")
