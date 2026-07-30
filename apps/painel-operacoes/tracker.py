"""Tracker de prospecção JPOS — a planilha do JP dentro do painel.

Espelha o "TRACKER DE PROSPECÇÃO — JPOS SITES": prospects curados à mão +
sócios/decisores por empresa. O bloco de cold calls é o prospeccao_log
(proslog.py) — não duplica aqui.

Colunas MANUAIS ficam no banco; a coluna de CONTATO (última ligação / canal /
resultado) é DERIVADA do prospeccao_log por telefone — "contatado preenche
automático": todo approach registrado (whatsapp, email, ligação) aparece no
tracker sem digitar de novo. Status fica manual (o rótulo do funil do JP).

Grava no mesmo leads.db (SQLite WAL). Funções puras: recebe dict, devolve dict.
"""
from __future__ import annotations

import os
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

# Status do funil — sugestões pra UI; o campo é livre, JP escreve o que quiser.
STATUS = ("A contatar", "Contato inicial", "Em conversa", "Proposta enviada",
          "Fechado", "Perdido")
TIERS = ("T1", "T2", "T3", "T4")


def _tel8(t: str) -> str:
    """Últimos 8 dígitos — mesma chave de match que o proslog usa (ignora DDI/DDD)."""
    return re.sub(r"\D", "", str(t or ""))[-8:]


def _db() -> sqlite3.Connection:
    p = Path(os.environ.get("LEADS_DB", str(Path(__file__).resolve().parents[2] / "data" / "leads.db")))
    p.parent.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(p, timeout=10)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA journal_mode=WAL")
    c.execute("""CREATE TABLE IF NOT EXISTS tracker_prospects (
        id INTEGER PRIMARY KEY AUTOINCREMENT, empresa TEXT, cnpj TEXT, segmento TEXT,
        cidade_uf TEXT, contato TEXT, cargo TEXT, telefone TEXT, tier TEXT, sinal TEXT,
        status TEXT DEFAULT 'A contatar', proxima_acao TEXT, data_proxima_acao TEXT,
        criado_em TEXT, atualizado_em TEXT)""")
    c.execute("""CREATE TABLE IF NOT EXISTS tracker_socios (
        id INTEGER PRIMARY KEY AUTOINCREMENT, prospect_id INTEGER, empresa TEXT,
        nome TEXT, cargo TEXT, telefone TEXT, poder_decisao TEXT, obs TEXT)""")
    c.commit()
    return c


def _contato_por_tel(c: sqlite3.Connection) -> dict[str, dict]:
    """Mapa {tel8 -> último contato} lido do prospeccao_log (a parte AUTOMÁTICA).

    Um só varrimento do log (mais recente primeiro) — o 1º que casa cada telefone
    é o último contato daquele número. Evita N queries (1 por prospect)."""
    fora: dict[str, dict] = {}
    try:
        rows = c.execute("SELECT telefone, canal, resultado, criado_em FROM prospeccao_log "
                         "ORDER BY id DESC").fetchall()
    except sqlite3.Error:
        return fora
    for r in rows:
        k = _tel8(r["telefone"])
        if k and k not in fora:
            fora[k] = {"data_ultimo_contato": (r["criado_em"] or "")[:10],
                       "canal": r["canal"] or "", "ultimo_resultado": r["resultado"] or ""}
    return fora


_CAMPOS_PROSPECT = ("empresa", "cnpj", "segmento", "cidade_uf", "contato", "cargo",
                    "telefone", "tier", "sinal", "status", "proxima_acao", "data_proxima_acao")


def _saneia_prospect(d: dict) -> dict:
    limites = {"empresa": 120, "cnpj": 20, "segmento": 60, "cidade_uf": 60, "contato": 80,
               "cargo": 60, "telefone": 30, "tier": 4, "sinal": 300, "status": 40,
               "proxima_acao": 200, "data_proxima_acao": 10}
    return {k: str(d.get(k) or "")[:limites[k]] for k in _CAMPOS_PROSPECT}


def prospect_salvar(d: dict) -> dict:
    """Upsert 1 prospect. id presente = update; ausente = insert. Devolve a linha."""
    campos = _saneia_prospect(d)
    if not campos["status"]:
        campos["status"] = "A contatar"
    agora = datetime.now(timezone.utc).isoformat()
    pid = d.get("id")
    with _db() as c:
        if pid:
            sets = ", ".join(f"{k}=?" for k in _CAMPOS_PROSPECT)
            c.execute(f"UPDATE tracker_prospects SET {sets}, atualizado_em=? WHERE id=?",
                      (*campos.values(), agora, int(pid)))
        else:
            cols = ", ".join(_CAMPOS_PROSPECT)
            ph = ", ".join("?" for _ in _CAMPOS_PROSPECT)
            cur = c.execute(f"INSERT INTO tracker_prospects ({cols}, criado_em, atualizado_em) "
                            f"VALUES ({ph}, ?, ?)", (*campos.values(), agora, agora))
            pid = cur.lastrowid
        c.commit()
    return {**campos, "id": int(pid)}


def prospect_deletar(pid: int) -> dict:
    with _db() as c:
        c.execute("DELETE FROM tracker_prospects WHERE id=?", (int(pid),))
        c.execute("DELETE FROM tracker_socios WHERE prospect_id=?", (int(pid),))
        c.commit()
    return {"ok": True, "id": int(pid)}


def prospects_listar() -> list[dict]:
    """Prospects + a coluna de contato derivada do log (a parte automática)."""
    with _db() as c:
        contatos = _contato_por_tel(c)
        rows = c.execute("SELECT * FROM tracker_prospects ORDER BY id").fetchall()
    saida = []
    for r in rows:
        p = dict(r)
        info = contatos.get(_tel8(p["telefone"]))
        p["contatado"] = bool(info)
        p["data_ultimo_contato"] = info["data_ultimo_contato"] if info else ""
        p["canal_ultimo_contato"] = info["canal"] if info else ""
        p["ultimo_resultado"] = info["ultimo_resultado"] if info else ""
        saida.append(p)
    return saida


def socio_salvar(d: dict) -> dict:
    campos = {"prospect_id": int(d.get("prospect_id") or 0) or None,
              "empresa": str(d.get("empresa") or "")[:120], "nome": str(d.get("nome") or "")[:80],
              "cargo": str(d.get("cargo") or "")[:80], "telefone": str(d.get("telefone") or "")[:30],
              "poder_decisao": str(d.get("poder_decisao") or "")[:20], "obs": str(d.get("obs") or "")[:300]}
    sid = d.get("id")
    with _db() as c:
        if sid:
            sets = ", ".join(f"{k}=?" for k in campos)
            c.execute(f"UPDATE tracker_socios SET {sets} WHERE id=?", (*campos.values(), int(sid)))
        else:
            cols = ", ".join(campos)
            ph = ", ".join("?" for _ in campos)
            cur = c.execute(f"INSERT INTO tracker_socios ({cols}) VALUES ({ph})", tuple(campos.values()))
            sid = cur.lastrowid
        c.commit()
    return {**campos, "id": int(sid)}


def socio_deletar(sid: int) -> dict:
    with _db() as c:
        c.execute("DELETE FROM tracker_socios WHERE id=?", (int(sid),))
        c.commit()
    return {"ok": True, "id": int(sid)}


def socios_listar() -> list[dict]:
    with _db() as c:
        rows = c.execute("SELECT * FROM tracker_socios ORDER BY prospect_id, id").fetchall()
    return [dict(r) for r in rows]


def importar_de_leads(limite: int = 30) -> dict:
    """Puxa os melhores leads_clinicas (passa_corte, maior score) pro tracker — pra
    não começar vazio. Pula telefones já no tracker (não duplica). Best-effort: se a
    tabela de leads não existe, devolve 0."""
    limite = max(1, min(200, int(limite)))
    agora = datetime.now(timezone.utc).isoformat()
    inseridos = 0
    with _db() as c:
        ja = {_tel8(r["telefone"]) for r in c.execute("SELECT telefone FROM tracker_prospects")}
        try:
            leads = c.execute(
                "SELECT nome, categoria, cidade_origem, telefone, tier_sugerido, motivo_da_dor "
                "FROM leads_clinicas WHERE passa_corte=1 ORDER BY score_final DESC LIMIT ?",
                (limite * 3,)).fetchall()  # margem: alguns caem no filtro de duplicado
        except sqlite3.Error:
            return {"ok": False, "inseridos": 0, "erro": "leads_clinicas indisponível"}
        for l in leads:
            if inseridos >= limite:
                break
            k = _tel8(l["telefone"])
            if k and k in ja:
                continue
            ja.add(k)
            c.execute("INSERT INTO tracker_prospects (empresa,cnpj,segmento,cidade_uf,contato,"
                      "cargo,telefone,tier,sinal,status,proxima_acao,data_proxima_acao,criado_em,atualizado_em) "
                      "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                      (str(l["nome"] or "")[:120], "", str(l["categoria"] or "")[:60],
                       str(l["cidade_origem"] or "")[:60], "", "", str(l["telefone"] or "")[:30],
                       str(l["tier_sugerido"] or "")[:4], str(l["motivo_da_dor"] or "")[:300],
                       "A contatar", "", "", agora, agora))
            inseridos += 1
        c.commit()
    return {"ok": True, "inseridos": inseridos}


def resumo() -> dict:
    """Contadores pro bloco RESUMO da planilha (prospects + funil do log)."""
    with _db() as c:
        prospects = c.execute("SELECT COUNT(*) FROM tracker_prospects").fetchone()[0]
        por_status = {r["status"]: r["n"] for r in c.execute(
            "SELECT status, COUNT(*) n FROM tracker_prospects GROUP BY status")}
        socios = c.execute("SELECT COUNT(*) FROM tracker_socios").fetchone()[0]
        contatos = _contato_por_tel(c)
        tels = [_tel8(r["telefone"]) for r in c.execute("SELECT telefone FROM tracker_prospects")]
        contatados = sum(1 for t in tels if t and t in contatos)
    return {"prospects": prospects, "contatados": contatados,
            "a_contatar": max(0, prospects - contatados), "socios": socios,
            "fechados": por_status.get("Fechado", 0), "perdidos": por_status.get("Perdido", 0),
            "por_status": por_status}


if __name__ == "__main__":  # self-check: usa DB temporário, não toca o real
    import tempfile
    os.environ["LEADS_DB"] = tempfile.mktemp()
    # 1) insert + update do prospect
    p = prospect_salvar({"empresa": "Clínica X", "telefone": "(14) 99999-8877", "tier": "T2"})
    assert p["id"] and p["status"] == "A contatar"
    p2 = prospect_salvar({"id": p["id"], "empresa": "Clínica X", "telefone": "(14) 99999-8877",
                          "status": "Em conversa", "tier": "T2"})
    assert p2["id"] == p["id"]
    assert prospects_listar()[0]["status"] == "Em conversa"
    # 2) contato derivado: sem log = não contatado
    assert prospects_listar()[0]["contatado"] is False
    # simula um approach no log (mesmo DB) por email → tracker reflete sozinho
    with _db() as c:
        c.execute("CREATE TABLE IF NOT EXISTS prospeccao_log (id INTEGER PRIMARY KEY AUTOINCREMENT,"
                  "empresa TEXT, telefone TEXT, canal TEXT, resultado TEXT, objecao TEXT,"
                  "o_que_falei TEXT, proximo_passo TEXT, criado_em TEXT)")
        c.execute("INSERT INTO prospeccao_log (telefone,canal,resultado,criado_em) VALUES (?,?,?,?)",
                  ("999998877", "email", "respondeu", "2026-07-30T10:00:00+00:00"))
        c.commit()
    row = prospects_listar()[0]
    assert row["contatado"] is True and row["canal_ultimo_contato"] == "email"
    assert row["data_ultimo_contato"] == "2026-07-30"
    # 3) sócio
    s = socio_salvar({"prospect_id": p["id"], "empresa": "Clínica X", "nome": "Dr. Fulano",
                      "poder_decisao": "Sim"})
    assert s["id"] and socios_listar()[0]["nome"] == "Dr. Fulano"
    # 4) resumo conta o contatado
    r = resumo()
    assert r["prospects"] == 1 and r["contatados"] == 1 and r["socios"] == 1
    # 5) delete leva os sócios junto
    prospect_deletar(p["id"])
    assert prospects_listar() == [] and socios_listar() == []
    print("tracker OK — prospect upsert, contato derivado do log (auto-fill), sócios, resumo, delete")
