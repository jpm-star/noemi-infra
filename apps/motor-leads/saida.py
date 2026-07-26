"""Camada 4 — OUTPUT: banco (SQLite padrão / Postgres via DSN) + CSV + Google Sheet.

Upsert por place_id preservando o `status` (não reseta um lead já 'ligado' pra
'novo'). SQLite por padrão (CLAUDE.md: não toca o Postgres de prod); Postgres só
se LEADS_PG_DSN estiver setado — o JP decide apontar. Sheet via gspread (import
tardio): só ativa com service account; senão o CSV já cobre.

Env: LEADS_DB (sqlite path, default data/leads.db), LEADS_PG_DSN (opcional),
GOOGLE_SHEET_ID, GOOGLE_SA_JSON (service account json path).
"""
from __future__ import annotations

import csv
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

# colunas persistidas (ordem estável); status NÃO é sobrescrito no update
COLUNAS = ("place_id", "cidade_origem", "categoria", "nome", "telefone", "website",
           "email", "rating", "total_reviews", "endereco", "horario", "sem_site",
           "http_status", "tem_ssl", "responsivo", "generator", "ano_rodape",
           "site_abandonado", "tem_wa_button", "tem_chat", "reviews_reclamam_demora",
           "atividade_recente", "n_unidades", "score_movimento", "score_dor",
           "score_final", "tier_sugerido", "motivo_da_dor", "passa_corte")
_STATUS_VALIDOS = ("novo", "ligado", "agendado", "fechado", "hostil")


def _db_path() -> Path:
    p = Path(os.environ.get("LEADS_DB", "data/leads.db"))
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def _conn():
    """(conn, dialect). Postgres se LEADS_PG_DSN setado (psycopg lazy), senão SQLite."""
    dsn = os.environ.get("LEADS_PG_DSN", "").strip()
    if dsn:
        try:
            import psycopg
        except ImportError:
            raise RuntimeError("LEADS_PG_DSN setado mas psycopg não instalado "
                               "(pip install 'psycopg[binary]'). Ou remova o DSN pra usar SQLite.")
        return psycopg.connect(dsn), "pg"
    c = sqlite3.connect(_db_path(), timeout=10)
    c.execute("PRAGMA journal_mode=WAL")
    return c, "sqlite"


def _ph(dialect: str, n: int) -> str:
    return ", ".join(["%s" if dialect == "pg" else "?"] * n)


def criar_tabela(conn, dialect: str) -> None:
    tipo_pk = "TEXT PRIMARY KEY"
    conn.execute(f"""
        CREATE TABLE IF NOT EXISTS leads_clinicas (
          place_id {tipo_pk}, cidade_origem TEXT, categoria TEXT, nome TEXT,
          telefone TEXT, website TEXT, email TEXT, rating REAL, total_reviews INTEGER,
          endereco TEXT, horario TEXT, sem_site INTEGER, http_status INTEGER,
          tem_ssl INTEGER, responsivo INTEGER, generator TEXT, ano_rodape INTEGER,
          site_abandonado INTEGER, tem_wa_button INTEGER, tem_chat INTEGER,
          reviews_reclamam_demora INTEGER, atividade_recente INTEGER, n_unidades INTEGER,
          score_movimento REAL, score_dor INTEGER, score_final REAL, tier_sugerido TEXT,
          motivo_da_dor TEXT, passa_corte INTEGER,
          status TEXT DEFAULT 'novo', criado_em TEXT, atualizado_em TEXT
        )""")
    conn.commit()


def _val(lead: dict, col: str):
    v = lead.get(col)
    return int(v) if isinstance(v, bool) else v


def gravar(leads: list[dict]) -> dict:
    """Upsert dos leads por place_id (preserva status/criado_em). Devolve contagem."""
    conn, dialect = _conn()
    try:
        criar_tabela(conn, dialect)
        agora = datetime.now(timezone.utc).isoformat()
        cols = ", ".join(COLUNAS)
        upd = ", ".join(f"{c}=excluded.{c}" for c in COLUNAS if c != "place_id")
        sql = (f"INSERT INTO leads_clinicas ({cols}, status, criado_em, atualizado_em) "
               f"VALUES ({_ph(dialect, len(COLUNAS))}, "
               f"{'%s,%s,%s' if dialect=='pg' else '?,?,?'}) "
               f"ON CONFLICT (place_id) DO UPDATE SET {upd}, atualizado_em=excluded.atualizado_em")
        # quantos são NOVOS (não existiam) — pro contador do grid (lead novo ≠ repetido)
        ids = [l.get("place_id") for l in leads if l.get("place_id")]
        existentes = set()
        if ids:
            ph = _ph(dialect, len(ids))
            existentes = {r[0] for r in conn.execute(
                f"SELECT place_id FROM leads_clinicas WHERE place_id IN ({ph})", ids)}
        novos = sum(1 for i in ids if i not in existentes)
        n = 0
        for l in leads:
            params = [_val(l, c) for c in COLUNAS] + ["novo", agora, agora]
            conn.execute(sql, params)
            n += 1
        conn.commit()
        return {"gravados": n, "novos": novos, "dialect": dialect}
    finally:
        conn.close()


def exportar_csv(leads: list[dict], caminho: str) -> str:
    """CSV completo (todas as colunas + status). Devolve o caminho."""
    p = Path(caminho)
    p.parent.mkdir(parents=True, exist_ok=True)
    campos = list(COLUNAS) + ["status"]
    with p.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=campos, extrasaction="ignore")
        w.writeheader()
        for l in leads:
            w.writerow({**{k: _val(l, k) for k in COLUNAS}, "status": l.get("status", "novo")})
    return str(p)


def exportar_sheets(caminho: str, *, so_fila: bool = False) -> dict:
    """CSV no formato do JP (nome·telefone·cidade·tier·site·email·endereco·
    avaliacao·multi_unidade·observacoes), DEDUP por telefone (só dígitos) ou
    domínio do site. Lê do BD. Devolve contagem + taxa de e-mail."""
    import re
    conn, _ = _conn()
    conn.row_factory = sqlite3.Row
    try:
        criar_tabela(conn, "sqlite")
        q = "SELECT * FROM leads_clinicas" + (" WHERE passa_corte=1" if so_fila else "")
        rows = [dict(r) for r in conn.execute(q + " ORDER BY score_final DESC")]
    finally:
        conn.close()
    # dedup por TELEFONE (único por unidade — preserva franquias com mesmo domínio
    # corporativo mas telefones diferentes). Domínio só desempata quem NÃO tem tel.
    vistos_tel, vistos_dom, linhas = set(), set(), []
    com_email = 0
    for r in rows:
        tel = re.sub(r"\D", "", r.get("telefone") or "")
        dom = re.sub(r"^www\.", "", (r.get("website") or "").split("//")[-1].split("/")[0]).lower()
        if tel and tel in vistos_tel:
            continue
        if not tel and dom and dom in vistos_dom:  # sem telefone: usa domínio
            continue
        if tel:
            vistos_tel.add(tel)
        elif dom:
            vistos_dom.add(dom)
        if r.get("email"):
            com_email += 1
        linhas.append({
            "nome": r.get("nome"), "telefone": r.get("telefone"), "cidade": r.get("cidade_origem"),
            "tier": r.get("tier_sugerido"), "site": r.get("website"), "email": r.get("email") or "",
            "endereco": r.get("endereco"), "avaliacao": r.get("rating"),
            "multi_unidade": bool((r.get("n_unidades") or 1) >= 2),
            "observacoes": r.get("motivo_da_dor")})
    p = Path(caminho)
    p.parent.mkdir(parents=True, exist_ok=True)
    campos = ["nome", "telefone", "cidade", "tier", "site", "email", "endereco",
              "avaliacao", "multi_unidade", "observacoes"]
    with p.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=campos)
        w.writeheader()
        w.writerows(linhas)
    total = len(linhas)
    return {"total": total, "com_email": com_email,
            "taxa_email_pct": round(100 * com_email / total, 1) if total else 0.0,
            "caminho": str(p)}


def sincronizar_sheet(leads: list[dict], *, sheet_id: str = "", sa_json: str = "") -> bool:
    """Sync na Google Sheet (colunas do time: nome, telefone, tier, score, motivo,
    status). Só ativa com service account; senão retorna False (CSV cobre)."""
    sheet_id = sheet_id or os.environ.get("GOOGLE_SHEET_ID", "")
    sa_json = sa_json or os.environ.get("GOOGLE_SA_JSON", "")
    if not sheet_id or not sa_json or not Path(sa_json).exists():
        return False
    try:
        import gspread  # dep opcional (pip install gspread); import tardio
    except ImportError:
        return False
    gc = gspread.service_account(filename=sa_json)
    ws = gc.open_by_key(sheet_id).sheet1
    linhas = [["nome", "telefone", "tier_sugerido", "score", "motivo_da_dor", "status"]]
    for l in sorted(leads, key=lambda x: -(x.get("score_final") or 0)):
        linhas.append([l.get("nome"), l.get("telefone"), l.get("tier_sugerido"),
                       l.get("score_final"), l.get("motivo_da_dor"), l.get("status", "novo")])
    ws.clear()
    ws.update(linhas, "A1")
    return True


if __name__ == "__main__":  # self-check: grava em SQLite temp, preserva status, CSV
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        os.environ["LEADS_DB"] = str(Path(td) / "t.db")
        os.environ.pop("LEADS_PG_DSN", None)
        lead = {"place_id": "x1", "nome": "Clínica A", "telefone": "14 3333",
                "tier_sugerido": "T2", "score_final": 55.0, "passa_corte": True,
                "sem_site": True, "cidade_origem": "Lins"}
        assert gravar([lead])["gravados"] == 1
        # marca como 'ligado' e re-grava: status NÃO pode voltar pra 'novo'
        conn, _ = _conn(); conn.execute("UPDATE leads_clinicas SET status='ligado'"); conn.commit(); conn.close()
        gravar([{**lead, "score_final": 99}])
        conn, _ = _conn()
        st, sc = conn.execute("SELECT status, score_final FROM leads_clinicas").fetchone(); conn.close()
        assert st == "ligado" and sc == 99, (st, sc)  # status preservado, score atualizado
        csvp = exportar_csv([lead], str(Path(td) / "o.csv"))
        assert "Clínica A" in Path(csvp).read_text()
        assert sincronizar_sheet([lead]) is False  # sem service account = no-op
        print("saida OK — upsert preserva status, atualiza score, CSV, sheet no-op sem SA")
