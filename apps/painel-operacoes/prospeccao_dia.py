"""Lista de prospecção DO DIA — quem ligar agora, em que ordem, falando o quê.

Fonte: tracker_prospects (leads.db) MENOS quem já tem contato no prospeccao_log
(match pelos últimos 8 dígitos, mesma chave do tracker). Ordena por tier (T1 primeiro:
é a meta maior e o gancho é o mais simples) e devolve tudo pronto pra ligar.

REGRA DO GANCHO (decisão firmada do JP): honesto SEMPRE. Nunca "fez uma reserva",
nunca contato prévio forjado. E uma distinção que evita queimar lead:

  - `gancho`  = o que o JP FALA. Verdade verificável e NÃO ofensiva.
  - `achado`  = contexto interno (inclui coisa que ofende se dita na cara, tipo
                "reviews reclamam de demora"). Serve pra sustentar a conversa se o
                dono perguntar "como assim?", não pra abrir a ligação.

ponytail: função pura (recebe filtro, devolve lista). Sem classe, sem cache.
"""
from __future__ import annotations

import os
import re
import sqlite3
from pathlib import Path

# Abordagem por tier — o QUE vender e COM que ângulo (cadência T3/T4 já decidida).
TIERS: dict[str, dict] = {
    "T1": {"rotulo": "T1 — sem site / landing fraca", "meta": 50,
           "abordagem": "Mostrar demo pronta no ar. Gancho: não aparece na busca.",
           "oferta": "Landing que aparece no Google e puxa no WhatsApp"},
    "T2": {"rotulo": "T2 — institucional 1 página", "meta": 15,
           "abordagem": "Site institucional simples, autoridade + contato fácil.",
           "oferta": "Site institucional de 1 página"},
    "T3": {"rotulo": "T3 — já tem site", "meta": 20,
           "abordagem": "Tem site mas não é achado/não converte. Vender SEO+AEO.",
           "oferta": "SEO + AEO (aparecer no Google E nas respostas de IA)"},
    "T4": {"rotulo": "T4 — site + Noemi em reunião", "meta": 15,
           "abordagem": "Reunião: demo + Noemi atendendo ao vivo.",
           "oferta": "Site + Noemi (atendimento 24h no WhatsApp)"},
}

# Achados que NÃO podem virar frase de abertura (ofendem o dono na cara).
_SENSIVEL = ("reclam", "demora", "nota baixa", "mal avaliad", "reviews ruins", "insatisf")


def _db() -> sqlite3.Connection:
    p = Path(os.environ.get("LEADS_DB", str(Path(__file__).resolve().parents[2] / "data" / "leads.db")))
    c = sqlite3.connect(p, timeout=10)
    c.row_factory = sqlite3.Row
    return c


def _tel8(t: str) -> str:
    return re.sub(r"\D", "", str(t or ""))[-8:]


def _wa(tel: str) -> str:
    """wa.me com DDI 55. Fixo (8 dígitos sem 9) não tem WhatsApp — devolve ''."""
    d = re.sub(r"\D", "", str(tel or ""))
    d = d[2:] if d.startswith("55") and len(d) > 11 else d
    if len(d) != 11 or d[2] != "9":  # celular BR = DDD + 9 + 8 dígitos
        return ""
    return "55" + d


def gancho(tier: str, segmento: str, cidade: str, achado: str) -> str:
    """A frase de abertura. Honesta, específica e nunca ofensiva."""
    seg = (segmento or "seu negócio").strip().lower()
    onde = f" em {cidade}" if cidade else ""
    a = (achado or "").lower()
    # achado sensível não abre conversa — cai no gancho padrão do tier
    limpo = "" if any(s in a for s in _SENSIVEL) else a
    if tier == "T1":
        if "sem site" in limpo or not limpo:
            return (f"vi que vocês não têm site — quando alguém busca \"{seg}{onde}\" no Google, "
                    f"vocês não aparecem, e quem aparece leva o cliente")
        if "whatsapp" in limpo:
            return ("vi que não tem botão de WhatsApp — quem quer falar com vocês tem que "
                    "procurar o número, e boa parte desiste no caminho")
        return f"vi que vocês não aparecem quando busco \"{seg}{onde}\" no Google"
    if tier == "T2":
        return (f"vi que vocês não têm uma página que explique o serviço — quem pesquisa "
                f"\"{seg}{onde}\" não acha nada oficial de vocês pra confiar")
    if tier == "T3":
        return (f"vocês têm site, mas testei: buscando \"{seg}{onde}\" ele não aparece na "
                f"primeira página, e o ChatGPT não cita vocês quando peço recomendação")
    if tier == "T4":
        return (f"vocês têm site, mas o atendimento depende de alguém estar disponível — "
                f"queria te mostrar o site novo + uma IA que responde no WhatsApp 24h")
    return f"vi que vocês não aparecem quando busco \"{seg}{onde}\""


def lista_do_dia(tier: str = "", limite: int = 200, incluir_contatados: bool = False) -> dict:
    """Fila de hoje: quem ainda não foi contatado, T1 primeiro, pronta pra ligar."""
    with _db() as c:
        try:
            ja = {_tel8(r["telefone"]) for r in c.execute("SELECT telefone FROM prospeccao_log")}
        except sqlite3.Error:
            ja = set()
        rows = [dict(r) for r in c.execute(
            "SELECT id,empresa,segmento,cidade_uf,telefone,tier,sinal,notas,status "
            "FROM tracker_prospects")]
    ordem = {"T1": 0, "T2": 1, "T3": 2, "T4": 3}
    fora: list[dict] = []
    for r in rows:
        t8 = _tel8(r["telefone"])
        contatado = bool(t8 and t8 in ja)
        if contatado and not incluir_contatados:
            continue
        tr = (r["tier"] or "").strip().upper() or "T1"
        if tier and tr != tier.upper():
            continue
        achado = " · ".join(x for x in ((r["sinal"] or "").strip(), (r["notas"] or "").strip()) if x)
        cidade = (r["cidade_uf"] or "").strip()
        wa = _wa(r["telefone"])
        fora.append({
            "id": r["id"], "empresa": (r["empresa"] or "").strip(),
            "segmento": (r["segmento"] or "").strip(), "cidade": cidade,
            "telefone": (r["telefone"] or "").strip(), "wa": wa,
            "tem_whatsapp": bool(wa), "tier": tr,
            "achado": achado, "sensivel": any(s in achado.lower() for s in _SENSIVEL),
            "gancho": gancho(tr, r["segmento"] or "", cidade, achado),
            "status": (r["status"] or "").strip(), "contatado": contatado,
        })
    fora.sort(key=lambda x: (ordem.get(x["tier"], 9), not x["tem_whatsapp"], x["empresa"].lower()))
    por_tier = {t: sum(1 for x in fora if x["tier"] == t) for t in TIERS}
    nt = notas_todas()
    for x in fora:
        x["nota"] = nt.get(x["id"], {"ligacao": "", "reacao_demo": ""})
    return {
        "leads": fora[:limite], "total": len(fora), "por_tier": por_tier,
        "sem_whatsapp": sum(1 for x in fora if not x["tem_whatsapp"]),
        "tiers": {t: {**v, "pendentes": por_tier.get(t, 0)} for t, v in TIERS.items()},
    }


def csv_lista(tiers: str = "T3,T4", limite: int = 500) -> str:
    """CSV da fila pra ligar (UTF-8 BOM p/ abrir certo no Excel PT-BR).

    Default T3/T4: são os tiers que o JP liga PESSOALMENTE (T3 = já tem site, vende
    SEO/AEO; T4 = reunião com demo + Noemi). Leva o gancho e o achado prontos — o
    achado sensível vai marcado, pra não ser dito na cara."""
    import csv
    import io
    alvos = {t.strip().upper() for t in (tiers or "").split(",") if t.strip()}
    # limite ALTO de propósito: lista_do_dia corta ANTES daqui e ordena T1 primeiro —
    # com o corte padrão, T3/T4 (o fim da fila) nunca chegariam ao filtro. Trunca só
    # DEPOIS de filtrar por tier.
    dados = lista_do_dia(limite=10**7)
    buf = io.StringIO()
    buf.write("﻿")  # BOM: sem isto o Excel PT-BR come os acentos
    w = csv.writer(buf, delimiter=";")  # ; = separador que o Excel PT-BR espera
    w.writerow(["tier", "empresa", "segmento", "cidade", "telefone", "tem_whatsapp",
                "link_whatsapp", "o_que_falar", "achado", "achado_sensivel", "status"])
    escolhidos = [x for x in dados["leads"] if not alvos or x["tier"] in alvos][:limite]
    for x in escolhidos:
        w.writerow([x["tier"], x["empresa"], x["segmento"], x["cidade"], x["telefone"],
                    "sim" if x["tem_whatsapp"] else "NAO (so fixo)",
                    f"https://wa.me/{x['wa']}" if x["wa"] else "",
                    x["gancho"], x["achado"],
                    "SIM - nao falar na cara" if x["sensivel"] else "",
                    x["status"]])
    return buf.getvalue()


# ─────────────────── anotações da ligação (CRM leve) ───────────────────
def _tabela_notas(c) -> None:
    c.execute("""CREATE TABLE IF NOT EXISTS prospeccao_notas (
        prospect_id INTEGER PRIMARY KEY, ligacao TEXT, reacao_demo TEXT, atualizado_em TEXT)""")
    c.commit()


def nota_salvar(prospect_id: int, ligacao: str = "", reacao_demo: str = "") -> dict:
    """Anotação por lead: como foi a ligação e como reagiu à demo. UPSERT — o JP
    escreve na hora, sem trocar de tela. Tabela PRÓPRIA (não usa tracker.notas) porque
    `notas` alimenta o autofill do site: nota de ligação lá dentro viraria copy."""
    from datetime import datetime, timezone
    if not prospect_id:
        return {"ok": False, "erro": "prospect_id obrigatório"}
    with _db() as c:
        _tabela_notas(c)
        c.execute("INSERT INTO prospeccao_notas (prospect_id,ligacao,reacao_demo,atualizado_em) "
                  "VALUES (?,?,?,?) ON CONFLICT(prospect_id) DO UPDATE SET "
                  "ligacao=excluded.ligacao, reacao_demo=excluded.reacao_demo, "
                  "atualizado_em=excluded.atualizado_em",
                  (int(prospect_id), (ligacao or "").strip()[:800],
                   (reacao_demo or "").strip()[:800],
                   datetime.now(timezone.utc).isoformat()))
        c.commit()
    return {"ok": True, "prospect_id": prospect_id}


def notas_todas() -> dict:
    with _db() as c:
        _tabela_notas(c)
        return {r["prospect_id"]: {"ligacao": r["ligacao"] or "", "reacao_demo": r["reacao_demo"] or ""}
                for r in c.execute("SELECT * FROM prospeccao_notas")}


if __name__ == "__main__":  # self-check
    import tempfile
    os.environ["LEADS_DB"] = tempfile.mktemp(suffix="_prosp.db")
    con = sqlite3.connect(os.environ["LEADS_DB"])
    con.execute("CREATE TABLE tracker_prospects (id INTEGER PRIMARY KEY, empresa,cnpj,segmento,"
                "cidade_uf,contato,cargo,telefone,tier,sinal,status,proxima_acao,data_proxima_acao,"
                "criado_em,atualizado_em,razao_social,notas)")
    con.execute("CREATE TABLE prospeccao_log (id INTEGER PRIMARY KEY, empresa,telefone,canal,"
                "resultado,objecao,o_que_falei,proximo_passo,criado_em)")
    dados = [(1,"Academia A","","academia","Marília","","","(14) 99999-1111","T1","sem site"),
             (2,"Clinica B","","clínica","Bauru","","","(14) 98888-2222","T3","reviews reclamam de demora"),
             (3,"Loja C","","loja","Lins","","","(14) 3333-4444","T1","sem site"),      # FIXO
             (4,"Ja Falei","","x","Assis","","","(14) 97777-5555","T1","sem site")]
    for d in dados:
        con.execute("INSERT INTO tracker_prospects (id,empresa,cnpj,segmento,cidade_uf,contato,cargo,"
                    "telefone,tier,sinal) VALUES (?,?,?,?,?,?,?,?,?,?)", d)
    con.execute("INSERT INTO prospeccao_log (empresa,telefone) VALUES ('Ja Falei','14977775555')")
    con.commit(); con.close()

    r = lista_do_dia()
    nomes = [x["empresa"] for x in r["leads"]]
    assert "Ja Falei" not in nomes, "quem já foi contatado não pode voltar na fila"
    assert nomes[0].startswith("Academia"), nomes  # T1 primeiro, com WhatsApp
    assert r["leads"][0]["tem_whatsapp"] and r["leads"][0]["wa"] == "5514999991111"
    fixo = [x for x in r["leads"] if x["empresa"] == "Loja C"][0]
    assert not fixo["tem_whatsapp"] and fixo["wa"] == "", "fixo não tem WhatsApp"
    t1 = [x["empresa"] for x in r["leads"] if x["tier"] == "T1"]
    assert t1[-1] == "Loja C", f"sem WhatsApp desce DENTRO do tier: {t1}"
    assert r["leads"][-1]["tier"] == "T3", "tier manda na ordem global (T1 antes de T3)"
    # achado SENSÍVEL nunca vira frase de abertura
    b = [x for x in r["leads"] if x["empresa"] == "Clinica B"][0]
    assert b["sensivel"] and "reclam" not in b["gancho"].lower(), b["gancho"]
    assert "não aparece" in b["gancho"] or "ChatGPT" in b["gancho"], b["gancho"]
    # gancho honesto: nunca inventa contato prévio
    for x in r["leads"]:
        g = x["gancho"].lower()
        assert "reserva" not in g and "conversamos" not in g and "nosso contato" not in g, g
    assert lista_do_dia(tier="T3")["total"] == 1
    assert r["por_tier"]["T1"] == 2 and r["sem_whatsapp"] == 1
    # CSV T3/T4: BOM pro Excel, só os tiers pedidos, gancho e achado vão junto
    # anotação por lead: upsert e volta na lista
    assert nota_salvar(0)["ok"] is False
    assert nota_salvar(1, "não atendeu", "—")["ok"]
    assert nota_salvar(1, "atendeu, gostou", "achou a demo boa")["ok"]
    n = notas_todas()[1]
    assert n["ligacao"] == "atendeu, gostou" and "demo boa" in n["reacao_demo"], n
    assert lista_do_dia()["leads"][0].get("nota") is not None
    c = csv_lista("T3,T4")
    assert c.startswith("﻿") and "o_que_falar" in c
    linhas = [ln for ln in c.splitlines() if ln.strip()]
    assert len(linhas) == 2, linhas          # cabeçalho + só a Clinica B (T3)
    assert "Clinica B" in c and "Academia A" not in c, "T1 não pode vazar no CSV de T3/T4"
    assert "nao falar na cara" in c          # achado sensível vai MARCADO
    assert len([ln for ln in csv_lista("T1").splitlines() if ln.strip()]) == 3  # 2 T1 + header
    # REGRESSÃO: com fila grande, o corte de `limite` acontecia ANTES do filtro de tier
    # e como T1 vem primeiro, T3/T4 (o fim da fila) sumiam do CSV. Enche de T1 e confere
    # que o T3 continua saindo.
    con2 = sqlite3.connect(os.environ["LEADS_DB"])
    con2.executemany("INSERT INTO tracker_prospects (empresa,segmento,cidade_uf,telefone,tier,sinal) "
                     "VALUES (?,?,?,?,?,?)",
                     [(f"Enche {i}", "x", "Bauru", f"(14) 9{i:04d}-{i:04d}", "T1", "sem site")
                      for i in range(1, 300)])
    con2.commit(); con2.close()
    c2 = csv_lista("T3,T4")
    assert "Clinica B" in c2, "T3 sumiu do CSV quando a fila de T1 cresceu (bug do corte antes do filtro)"
    print(f"prospeccao_dia OK — {r['total']} na fila, T1 primeiro, contatado sai, "
          f"fixo marcado, achado sensível não abre conversa")
