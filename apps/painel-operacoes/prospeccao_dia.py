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


def normalizar_celular(tel: str) -> str:
    """Telefone → celular BR de 11 dígitos (DDD + 9 + 8), ou "" se não for celular.

    O NONO DÍGITO (2026-08-06). A base da CNPJá — 37.070 leads, TODOS com nome e CNPJ —
    guarda telefone com 10 dígitos (DDD + 8), o formato anterior a 2016. A regra antiga
    aqui exigia 11 dígitos e devolvia "" pra todos eles: 26.885 celulares perfeitamente
    válidos apareciam como "sem WhatsApp", e a base útil parecia ter 1.512 leads em vez
    de 28 mil. O funil inteiro foi dimensionado por cima desse erro de leitura.

    A recuperação é a própria regra da portabilidade: quando o número virou 11 dígitos,
    o 9 foi inserido na frente dos 8 e o prefixo antigo (6-9) foi preservado. Então
    DDD + [6-9]XXXXXXX vira DDD + 9 + [6-9]XXXXXXX. Prefixo 2-5 era e continua FIXO.

    CANDIDATO, NÃO CONFIRMAÇÃO: isto diz "este número tem forma de celular", não "este
    número tem WhatsApp". Quem confirma é o portão da Evolution antes do envio — e ele
    continua sendo obrigatório."""
    d = re.sub(r"\D", "", str(tel or ""))
    if d.startswith("55") and len(d) > 11:
        d = d[2:]
    if len(d) == 11:
        return d if d[2] == "9" else ""          # já normalizado (ou fixo mal formatado)
    if len(d) == 10 and d[2] in "6789":          # formato pré-2016: recupera o 9
        return d[:2] + "9" + d[2:]
    return ""                                     # fixo, incompleto ou lixo


def _wa(tel: str) -> str:
    """wa.me com DDI 55. "" quando o número não tem forma de celular."""
    return "55" + c if (c := normalizar_celular(tel)) else ""


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
        # `demo_url` é coluna ADITIVA (criada pelo Studio). Banco antigo não tem, então
        # a query se adapta em vez de quebrar — o painel não pode morrer por uma coluna.
        _cols = {r[1] for r in c.execute("PRAGMA table_info(tracker_prospects)")}
        _extra = ",demo_url" if "demo_url" in _cols else ""
        rows = [dict(r) for r in c.execute(
            "SELECT id,empresa,segmento,cidade_uf,telefone,tier,sinal,notas,status,cnpj,"
            f"razao_social{_extra} FROM tracker_prospects")]
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
            "cnpj": (r["cnpj"] or "").strip(), "razao_social": (r["razao_social"] or "").strip(),
            # ciclo fechado: demo gerada pelo Studio volta pro card, sem copiar e colar.
            # `.keys()` porque a coluna é aditiva — banco antigo não tem e não pode quebrar.
            "demo_url": (r["demo_url"] or "").strip() if "demo_url" in r.keys() else "",
        })
    fora.sort(key=lambda x: (ordem.get(x["tier"], 9), not x["tem_whatsapp"], x["empresa"].lower()))
    por_tier = {t: sum(1 for x in fora if x["tier"] == t) for t in TIERS}
    # DECISOR na ficha (QSA da CNPJá): ligar sabendo o nome muda a conversa —
    # "posso falar com o responsável?" vs "o Wagner está?". Quem DECIDE vem primeiro.
    dec: dict[int, list[dict]] = {}
    try:
        with _db() as c:
            for r in c.execute("SELECT prospect_id,nome,cargo,poder_decisao FROM tracker_socios "
                               "WHERE prospect_id IS NOT NULL "
                               "ORDER BY CASE WHEN poder_decisao='decide' THEN 0 ELSE 1 END, id"):
                dec.setdefault(r["prospect_id"], []).append(
                    {"nome": r["nome"] or "", "cargo": r["cargo"] or "",
                     "decide": (r["poder_decisao"] or "") == "decide"})
    except sqlite3.Error:
        dec = {}
    nt = notas_todas()
    sdr = _estado_sdr()
    mails = _emails_enviados()
    for x in fora:
        x["nota"] = nt.get(x["id"], {"ligacao": "", "reacao_demo": ""})
        x["status_auto"] = sdr.get(_tel8(x["telefone"]), "")
        x["coluna"] = coluna_de(x.get("status", ""), x["status_auto"])
        # indicadores de canal, visíveis no card sem abrir nada
        x["email_enviado"] = bool((x.get("email") or "").lower() in mails)
        x["wpp"] = ("enviado" if x["status_auto"] in ("enviado", "respondeu", "demo_enviada",
                                                      "handoff_jp") else
                    ("sem número" if not x["tem_whatsapp"] else "na fila"))
        x["socios"] = dec.get(x["id"], [])
        x["decisor"] = x["socios"][0]["nome"] if x["socios"] else ""
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
    w.writerow(["tier", "empresa", "decisor", "cargo_decisor", "segmento", "cidade", "telefone",
                "tem_whatsapp", "link_whatsapp", "o_que_falar", "achado", "achado_sensivel", "status"])
    escolhidos = [x for x in dados["leads"] if not alvos or x["tier"] in alvos][:limite]
    for x in escolhidos:
        _s0 = (x.get("socios") or [{}])[0]
        w.writerow([x["tier"], x["empresa"], _s0.get("nome", ""), _s0.get("cargo", ""),
                    x["segmento"], x["cidade"], x["telefone"],
                    "sim" if x["tem_whatsapp"] else "NAO (so fixo)",
                    f"https://wa.me/{x['wa']}" if x["wa"] else "",
                    x["gancho"], x["achado"],
                    "SIM - nao falar na cara" if x["sensivel"] else "",
                    x["status"]])
    return buf.getvalue()


# ── funil: DUAS fontes de verdade, cada uma com seu dono ─────────────────────
# tracker_prospects.status = o funil que o JP move na mão (A contatar → Fechado).
# prospects.status (sdr-motor) = o estado da AUTOMAÇÃO (enviado/respondeu/demo_enviada/
# handoff_jp/arquivado). Não são concorrentes: a automação empurra, o JP confirma.
# O kanban mostra a coluna derivada dos dois — a automação adianta a coluna, o JP
# corrige arrastando.
COLUNAS = ("Prospecção", "Qualificação", "Demo Agendada", "Proposta", "Ganho")
# status manual (tracker) -> coluna. É o que vence quando o JP move o card.
_COL_MANUAL = {"a contatar": "Prospecção", "contato inicial": "Qualificação",
               "em conversa": "Qualificação", "proposta enviada": "Proposta",
               "fechado": "Ganho", "perdido": "Perdido"}
# status da automação (sdr) -> coluna, quando o manual ainda está no início
_COL_AUTO = {"respondeu": "Qualificação", "demo_enviada": "Demo Agendada",
             "handoff_jp": "Demo Agendada", "arquivado": "Perdido"}
# botão da UI -> status MANUAL gravado (nenhum status novo é inventado)
ACOES = {"qualificar": "Em conversa", "demo_agendada": "Proposta enviada",
         "nao_respondeu": "A contatar", "sem_interesse": "Perdido",
         "ganho": "Fechado"}


def coluna_de(status_manual: str, status_auto: str) -> str:
    """Coluna do kanban. Manual vence; a automação só adianta quem ainda não foi mexido."""
    m = (status_manual or "").strip().lower()
    col = _COL_MANUAL.get(m, "Prospecção")
    if col == "Prospecção":  # ainda não mexido na mão: deixa a automação adiantar
        return _COL_AUTO.get((status_auto or "").strip().lower(), col)
    return col


def _estado_sdr() -> dict[str, str]:
    """{tel8 -> status da automação} lido do sdr-motor (Postgres, banco separado).
    Falha => {} e o card mostra só o status manual (degrada, não quebra)."""
    fora: dict[str, str] = {}
    try:
        import subprocess
        out = subprocess.run(
            ["docker", "exec", os.environ.get("PG_CONTAINER", "evolution_postgres"),
             "psql", "-U", os.environ.get("PG_USER", "evolution"),
             "-d", os.environ.get("PG_DB", "sdr_motor_papai"),
             "-tAc", "SELECT telefone||'|'||status FROM prospects"],
            capture_output=True, text=True, timeout=30)
        for ln in out.stdout.splitlines():
            if "|" in ln:
                tel, _, st = ln.strip().partition("|")
                k = _tel8(tel)
                if k:
                    fora[k] = st
    except Exception:  # noqa: BLE001
        pass
    return fora


def _emails_enviados() -> set[str]:
    """E-mails já enfileirados/enviados — alimenta o indicador de canal no card."""
    try:
        with _db() as c:
            return {str(r[0] or "").lower() for r in c.execute("SELECT to_addr FROM emails")}
    except sqlite3.Error:
        return set()


def status_salvar(prospect_id: int, acao: str) -> dict:
    """Move o lead no funil pela AÇÃO do botão (mapeada em ACOES). Grava no status
    manual do tracker — o campo que o JP controla."""
    novo = ACOES.get((acao or "").strip().lower())
    if not prospect_id or not novo:
        return {"ok": False, "erro": f"ação inválida: {acao!r}"}
    with _db() as c:
        c.execute("UPDATE tracker_prospects SET status=?, atualizado_em=? WHERE id=?",
                  (novo, __import__("datetime").datetime.now(
                      __import__("datetime").timezone.utc).isoformat(), int(prospect_id)))
        c.commit()
    return {"ok": True, "prospect_id": prospect_id, "status": novo,
            "coluna": coluna_de(novo, "")}


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
