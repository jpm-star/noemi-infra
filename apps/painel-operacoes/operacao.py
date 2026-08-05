#!/usr/bin/env python3
"""STUDIO #4 — OPERAÇÃO: o que acontece DEPOIS do site existir.

A galeria mostra o que foi feito. Esta aba mostra se deu dinheiro.

O que ela responde, na ordem em que importa:
  1. dos sites gerados, quantos viraram cliente pagante (conversão real, não volume)
  2. por tier, quantos fecharam no mês contra a meta de 10
  3. cada site ligado ao lead que o originou
  4. estado do canal por cliente (e-mail / WhatsApp / demo / handoff / fechado)
  5. custo por venda — só do que está INSTRUMENTADO; o resto sai marcado como
     não medido, porque margem com número inventado é pior que margem nenhuma

A PONTE QUE NÃO EXISTIA: `sites_gerados` (noemi.db) não tinha `prospect_id`, e
`tracker_prospects` mora em OUTRO arquivo SQLite (leads.db) — nem FK dava. Aqui a
coluna é criada e preenchida por casamento de nome normalizado, uma vez; depois disso
a ligação é por id e não depende mais de string parecida.

Não duplica funil: `coluna_de`, `_estado_sdr` e `_emails_enviados` vêm de
prospeccao_dia, a mesma fonte do CRM em /obs/prospeccao.
"""
from __future__ import annotations

import re
import sqlite3
import sys
import unicodedata
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

_AQUI = Path(__file__).resolve().parent
sys.path.insert(0, str(_AQUI))
sys.path.insert(0, str(_AQUI.parents[1] / "packages"))  # shared_core (db.conn do noemi.db)

META_MES = 10  # meta de vendas por tier no mês (definida pelo JP)

# Custo por insumo. Só entra aqui o que tem preço CONHECIDO e volume medido.
# `None` = consumido mas não instrumentado — aparece no relatório como "não medido"
# em vez de virar zero e inflar a margem.
CUSTOS = {
    "groq_llm": {"rotulo": "LLM (Groq)", "unit": 0.0,
                 "nota": "free tier — custo real R$0, teto é cota, não dinheiro"},
    "cnpja": {"rotulo": "CNPJá", "unit": None, "nota": "crédito pré-pago, sem preço por lead no banco"},
    "resend": {"rotulo": "Resend", "unit": None, "nota": "plano mensal, não por e-mail"},
    "higgsfield": {"rotulo": "Higgsfield", "unit": None, "nota": "sem crédito de API ativo"},
    "places": {"rotulo": "Google Places", "unit": None, "nota": "SKU medido em places_uso, preço não configurado"},
}


def _norm(s: str) -> str:
    """Nome comparável: sem acento, sem pontuação, sem sufixo de razão social.
    'Clínica Aurêa Ltda.' e 'clinica aurea' viram a mesma chave."""
    s = unicodedata.normalize("NFKD", (s or "").strip().lower())
    s = s.encode("ascii", "ignore").decode()
    s = re.sub(r"\b(ltda|me|epp|eireli|sa|s/a|cia)\b", " ", s)
    return re.sub(r"[^a-z0-9]+", " ", s).strip()


def _db_noemi() -> sqlite3.Connection:
    import criacao
    return criacao._db_noemi()


def _db_leads() -> sqlite3.Connection:
    import prospeccao_dia
    return prospeccao_dia._db()


def _garante_ponte(c: sqlite3.Connection) -> None:
    """Cria `sites_gerados.prospect_id`. Idempotente — roda a cada leitura sem custo."""
    cols = {r[1] for r in c.execute("PRAGMA table_info(sites_gerados)")}
    if "prospect_id" not in cols:
        c.execute("ALTER TABLE sites_gerados ADD COLUMN prospect_id INTEGER")


def vincular() -> dict:
    """Liga site → lead por nome normalizado. Só preenche o que está VAZIO: uma
    vinculação manual futura (ou correção) nunca é sobrescrita por heurística.

    Nome ambíguo (2+ leads com a mesma chave) fica sem vínculo de propósito —
    ligar o site ao lead errado estraga a conversão de forma silenciosa."""
    chaves: dict[str, list[int]] = {}
    try:
        with _db_leads() as l:
            for pid, emp in l.execute("SELECT id, empresa FROM tracker_prospects"):
                chaves.setdefault(_norm(emp), []).append(pid)
    except sqlite3.Error as e:
        # CRM ausente/vazio não pode derrubar a aba inteira: os sites e os custos
        # continuam legíveis, só o vínculo com lead fica em branco.
        return {"ligados": 0, "ambiguos": 0, "erro": str(e)[:120]}
    ligados = ambiguos = 0
    with _db_noemi() as c:
        _garante_ponte(c)
        for sid, cliente in c.execute(
                "SELECT id, cliente FROM sites_gerados WHERE prospect_id IS NULL").fetchall():
            achou = chaves.get(_norm(cliente)) or []
            if len(achou) == 1:
                c.execute("UPDATE sites_gerados SET prospect_id=? WHERE id=?", (achou[0], sid))
                ligados += 1
            elif len(achou) > 1:
                ambiguos += 1
    return {"ligados": ligados, "ambiguos": ambiguos}


def _leads_por_id(ids: set[int]) -> dict[int, dict]:
    if not ids:
        return {}
    marca = ",".join("?" * len(ids))
    try:
        with _db_leads() as l:
            return {r["id"]: dict(r) for r in l.execute(
                f"SELECT id,empresa,tier,status,telefone,segmento,cidade_uf,contato,cnpj "
                f"FROM tracker_prospects WHERE id IN ({marca})", tuple(ids))}
    except sqlite3.Error:
        return {}


def _email_por_cnpj() -> dict[str, str]:
    """{cnpj -> status do e-mail}. `emails.lead_id` guarda o CNPJ (vem do leads_cnpja),
    NÃO um id de tracker — descobri isso olhando o dado, não o nome da coluna. E
    `pending` não é 'enviado': ficaria mentindo no indicador de canal."""
    fora: dict[str, str] = {}
    try:
        with _db_leads() as l:
            for lid, st in l.execute("SELECT lead_id, status FROM emails"):
                k = re.sub(r"\D", "", str(lid or ""))
                if k and fora.get(k) != "sent":   # 'sent' de qualquer linha vence
                    fora[k] = str(st or "")
    except sqlite3.Error:
        pass
    return fora


def _mes_atual() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m")


def sites_com_lead() -> list[dict]:
    """Cada site com o lead que o originou e o estado do canal. Site sem lead
    aparece igual — é justamente o que precisa de atenção (demo órfã de dono)."""
    import prospeccao_dia as pd
    vincular()
    with _db_noemi() as c:
        _garante_ponte(c)
        # DEDUP POR SLUG: regerar um site insere linha nova, e contar o mesmo site 3x
        # infla a conversão (o denominador cresce sem existir site novo). id DESC =
        # fica a geração mais recente, que é a que está no ar.
        vistos: set[str] = set()
        linhas = []
        for r in c.execute("SELECT id,cliente,segmento,slug,url,criado_em,prospect_id "
                           "FROM sites_gerados ORDER BY id DESC"):
            if r["slug"] in vistos:
                continue
            vistos.add(r["slug"])
            linhas.append(dict(r))
    leads = _leads_por_id({x["prospect_id"] for x in linhas if x["prospect_id"]})
    auto = pd._estado_sdr()      # {tel8 -> status da automação} (Postgres do sdr)
    mails = _email_por_cnpj()
    fora = []
    for x in linhas:
        ld = leads.get(x["prospect_id"] or 0) or {}
        tel8 = re.sub(r"\D", "", str(ld.get("telefone") or ""))[-8:]
        st_auto = auto.get(tel8, "")
        st_mail = mails.get(re.sub(r"\D", "", str(ld.get("cnpj") or "")), "")
        fora.append({**x, "empresa": ld.get("empresa") or x["cliente"],
                     "tier": ld.get("tier") or "", "status": ld.get("status") or "",
                     "cidade": ld.get("cidade_uf") or "", "contato": ld.get("contato") or "",
                     "status_auto": st_auto, "status_email": st_mail,
                     "coluna": pd.coluna_de(ld.get("status") or "", st_auto) if ld else "",
                     "canais": {"email": st_mail == "sent", "email_fila": st_mail == "pending",
                                "whatsapp": bool(st_auto),
                                "demo": True,  # o site existir É a demo
                                "handoff": st_auto == "handoff_jp",
                                "fechado": (ld.get("status") or "").strip().lower() == "fechado"}})
    return fora


def custos() -> list[dict]:
    """Volume consumido por insumo. Vira R$ só onde há preço unitário configurado;
    o resto sai marcado, não zerado."""
    vol: dict[str, int] = {}
    try:
        with _db_leads() as l:
            vol["resend"] = l.execute(
                "SELECT COUNT(*) FROM emails WHERE status='sent'").fetchone()[0]
            vol["cnpja"] = l.execute("SELECT COUNT(*) FROM leads_cnpja").fetchone()[0]
            vol["places"] = l.execute("SELECT COALESCE(SUM(n),0) FROM places_uso").fetchone()[0]
    except sqlite3.Error:
        pass
    try:
        with _db_noemi() as c:
            vol["groq_llm"] = c.execute("SELECT COUNT(*) FROM sites_gerados").fetchone()[0]
            vol["higgsfield"] = c.execute(
                "SELECT COUNT(*) FROM jobs WHERE produto LIKE '%video%'").fetchone()[0]
    except sqlite3.Error:
        pass
    fora = []
    for k, cfg in CUSTOS.items():
        n = vol.get(k, 0)
        fora.append({"insumo": k, "rotulo": cfg["rotulo"], "volume": n,
                     "custo": round(n * cfg["unit"], 2) if cfg["unit"] is not None else None,
                     "nota": cfg["nota"]})
    return fora


def resumo() -> dict:
    """Painel da aba: conversão real, meta por tier, custo por venda."""
    sites = sites_com_lead()
    ganhos = [s for s in sites if s["canais"]["fechado"]]
    mes = _mes_atual()
    por_tier = {}
    for t in ("T1", "T2", "T3", "T4"):
        vend = sum(1 for s in ganhos if s["tier"] == t and (s["criado_em"] or "").startswith(mes))
        por_tier[t] = {"vendidos_mes": vend, "meta": META_MES,
                       "sites": sum(1 for s in sites if s["tier"] == t),
                       "pct": round(100 * vend / META_MES)}
    cs = custos()
    medido = sum(c["custo"] for c in cs if c["custo"] is not None)
    nao_medido = [c["rotulo"] for c in cs if c["custo"] is None and c["volume"]]
    return {
        "sites": len(sites), "com_lead": sum(1 for s in sites if s["prospect_id"]),
        "sem_lead": sum(1 for s in sites if not s["prospect_id"]),
        "clientes_pagantes": len(ganhos),
        "conversao": round(100 * len(ganhos) / max(1, len(sites)), 1),
        "funil": dict(Counter(s["coluna"] for s in sites if s["coluna"])),
        "por_tier": por_tier, "mes": mes,
        "custos": cs, "custo_medido": round(medido, 2),
        "custo_por_venda": round(medido / len(ganhos), 2) if ganhos else None,
        "nao_instrumentado": nao_medido,
    }


if __name__ == "__main__":  # self-check offline (bancos temporários, sem rede)
    import os
    import tempfile
    d = tempfile.mkdtemp(suffix="_op")
    os.environ["NOEMI_DATA_DIR"] = d
    os.environ["LEADS_DB"] = str(Path(d) / "leads.db")

    assert _norm("Clínica Aurêa Ltda.") == _norm("clinica aurea"), _norm("Clínica Aurêa Ltda.")
    assert _norm("Bar do Zé  ME") == "bar do ze"

    ln = sqlite3.connect(os.environ["LEADS_DB"])
    ln.execute("CREATE TABLE tracker_prospects (id INTEGER PRIMARY KEY, empresa TEXT, cnpj TEXT,"
               " segmento TEXT, cidade_uf TEXT, contato TEXT, cargo TEXT, telefone TEXT,"
               " tier TEXT, sinal TEXT, status TEXT, proxima_acao TEXT, data_proxima_acao TEXT,"
               " criado_em TEXT, atualizado_em TEXT, razao_social TEXT, notas TEXT)")
    ln.executemany("INSERT INTO tracker_prospects (id,empresa,tier,status,telefone,cnpj)"
                   " VALUES (?,?,?,?,?,?)",
                   [(1, "Clínica Aurêa Ltda.", "T3", "Fechado", "5514991110000", "11111111000100"),
                    (2, "Bar do Zé", "T1", "A contatar", "5514992220000", "22222222000100"),
                    (3, "Repetido", "T2", "A contatar", "5514993330000", ""),
                    (4, "REPETIDO ME", "T2", "A contatar", "5514994440000", "")])
    ln.execute("CREATE TABLE emails (id INTEGER PRIMARY KEY, lead_id INT, to_addr TEXT,"
               " subject TEXT, body TEXT, status TEXT, message_id TEXT, erro TEXT,"
               " criado_em TEXT, enviado_em TEXT)")
    ln.executemany("INSERT INTO emails (lead_id,to_addr,status) VALUES (?,?,?)",
                   [("11111111000100", "a@a.com", "sent"),      # enviado de verdade
                    ("22222222000100", "b@b.com", "pending")])  # só na fila
    ln.execute("CREATE TABLE leads_cnpja (cnpj TEXT)")
    ln.execute("CREATE TABLE places_uso (dia TEXT, sku TEXT, n INT)")
    ln.execute("INSERT INTO places_uso VALUES ('2026-08-01','text_search',7)")
    ln.commit(); ln.close()

    import criacao
    with criacao._db_noemi() as c:
        c.execute("CREATE TABLE IF NOT EXISTS sites_gerados (id INTEGER PRIMARY KEY,"
                  " cliente TEXT, segmento TEXT, slug TEXT, url TEXT, criado_em TEXT)")
        hoje = datetime.now(timezone.utc).strftime("%Y-%m-%dT00:00:00")
        c.executemany("INSERT INTO sites_gerados (cliente,segmento,slug,url,criado_em)"
                      " VALUES (?,?,?,?,?)",
                      [("clinica aurea", "clínica", "a", "u/a", hoje),      # casa com id 1
                       ("Bar do Zé", "bar", "b", "u/b", hoje),              # casa com id 2
                       ("Repetido", "x", "c", "u/c", hoje),                 # AMBÍGUO (3 e 4)
                       ("Ninguém", "x", "d", "u/d", hoje),                  # sem lead
                       ("Bar do Zé", "bar", "b", "u/b", hoje)])             # REGERADO: slug repetido
        c.execute("CREATE TABLE IF NOT EXISTS jobs (id INTEGER PRIMARY KEY, produto TEXT)")

    v = vincular()
    # vincula por LINHA (3: aurea + os 2 'Bar do Zé'); o ambíguo fica de fora de propósito
    assert v["ligados"] == 3 and v["ambiguos"] == 1, v   # ambíguo NÃO liga: erraria calado
    assert vincular()["ligados"] == 0, "2ª passada não deve religar nada (idempotente)"

    s = sites_com_lead()
    por = {x["slug"]: x for x in s}
    assert por["a"]["tier"] == "T3" and por["a"]["canais"]["fechado"] is True, por["a"]
    assert por["a"]["coluna"] == "Ganho", por["a"]["coluna"]
    assert por["b"]["canais"]["fechado"] is False and por["b"]["coluna"] == "Prospecção"
    # 'pending' NÃO é 'enviado' — o indicador de canal não pode mentir pro JP
    assert por["a"]["canais"]["email"] is True and por["a"]["canais"]["email_fila"] is False
    assert por["b"]["canais"]["email"] is False and por["b"]["canais"]["email_fila"] is True
    assert por["c"]["prospect_id"] is None and por["c"]["empresa"] == "Repetido"  # cai no nome do site
    assert por["d"]["tier"] == "" and por["d"]["coluna"] == ""

    r = resumo()
    # 5 linhas, 4 slugs: o site regerado conta UMA vez (senão a conversão desinfla)
    assert r["sites"] == 4 and r["com_lead"] == 2 and r["sem_lead"] == 2, r
    assert len(s) == 4 and len({x["slug"] for x in s}) == 4, [x["slug"] for x in s]
    assert r["clientes_pagantes"] == 1 and r["conversao"] == 25.0, r
    assert r["por_tier"]["T3"]["vendidos_mes"] == 1 and r["por_tier"]["T3"]["meta"] == META_MES
    assert r["por_tier"]["T1"]["vendidos_mes"] == 0, r["por_tier"]["T1"]
    # custo: o que não tem preço aparece marcado, NÃO some nem vira zero
    assert any(c["custo"] is None and c["volume"] > 0 for c in r["custos"]), r["custos"]
    assert "Google Places" in r["nao_instrumentado"], r["nao_instrumentado"]
    print(f"operacao OK — {r['sites']} sites, {r['com_lead']} ligados a lead "
          f"({r['sem_lead']} órfãos), conversão {r['conversao']}%, "
          f"{len(r['nao_instrumentado'])} insumo(s) sem preço configurado")
