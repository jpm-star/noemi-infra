"""TRIAGEM DE INTAKE — porteiro do briefing, sem LLM e sem rede.

Duas coisas, e só duas:
1. FORMATO do contato (WhatsApp BR + e-mail) — normaliza ou devolve erro em português.
   Motivo de existir: o QA pós-geração (criacao.py `telefone_falso`) já barra número de
   mentira DEPOIS de gastar a chamada de LLM e renderizar o site. Aqui barra ANTES.
2. DONO do lead por round-robin determinístico — sem contador, sem tabela de estado:
   o dono sai de uma função pura da chave do lead, então backfill e lead novo usam
   exatamente o mesmo caminho e rodar duas vezes não remexe em nada.

Nada aqui está plugado no fluxo /obs/criar ainda. Ponto de entrada pro integrador:
`triar(briefing, lead_id=...)`.

CLI:
  python3 intake.py --check                  # self-check offline (sem rede, sem banco real)
  python3 intake.py --backfill               # ensaio: mostra quem receberia dono
  python3 intake.py --backfill --aplicar     # grava
"""
from __future__ import annotations

import hashlib
import os
import re
import sqlite3
import sys
from pathlib import Path

# DDDs que existem no Brasil. É constante e barata, e pega o erro mais comum do
# formulário (dígito trocado no DDD) que uma checagem de comprimento deixa passar.
_DDD = frozenset("""11 12 13 14 15 16 17 18 19 21 22 24 27 28 31 32 33 34 35 37 38
41 42 43 44 45 46 47 48 49 51 53 54 55 61 62 63 64 65 66 67 68 69 71 73 74 75 77 79
81 82 83 84 85 86 87 88 89 91 92 93 94 95 96 97 98 99""".split())

# Regex de e-mail: mesmo padrão já usado em apps/motor-leads/enriquecimento.py:19,
# aqui com fullmatch (lá é varredura de HTML, aqui é validação de campo).
_EMAIL = re.compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}")
_EMAIL_FAKE = ("exemplo", "example", "seuemail", "seu-email", "teste@teste",
               "email@email", "nao-responda", "noreply")

DONOS_PADRAO = ("jp",)


class ErroIntake(ValueError):
    """Erro de formato com mensagem pronta pra mostrar no painel."""


# ---------------------------------------------------------------- contato

def normalizar_whatsapp(valor: str) -> str:
    """'(14) 9 9874-5847', '+55 14 99874-5847', '14 3234-5678' -> '5514998745847'.
    Devolve DDI+DDD+número só com dígitos. Levanta ErroIntake com o motivo."""
    bruto = str(valor or "").strip()
    if not bruto:
        raise ErroIntake("WhatsApp vazio.")
    d = re.sub(r"\D", "", bruto)
    if d.startswith("55") and len(d) in (12, 13):
        d = d[2:]
    # prefixo de operadora (011 9...): só tira o zero se o que sobra é DDD de verdade,
    # senão "(00) 9..." vira "09" e o erro aponta pro DDD errado.
    if d.startswith("0") and len(d) in (11, 12) and d[1:3] in _DDD:
        d = d[1:]
    if len(d) not in (10, 11):
        raise ErroIntake(
            f"WhatsApp com {len(d)} dígitos ({bruto}). Esperado DDD + número: "
            "10 dígitos (fixo) ou 11 (celular).")
    if d[:2] not in _DDD:
        raise ErroIntake(f"DDD {d[:2]} não existe no Brasil ({bruto}).")
    if len(d) == 11:
        if d[2] != "9":
            raise ErroIntake(
                f"Número de 11 dígitos precisa começar com 9 depois do DDD ({bruto}).")
    elif d[2] in "6789":
        d = d[:2] + "9" + d[2:]      # celular antigo sem o 9º dígito
    elif d[2] not in "2345":
        raise ErroIntake(f"Número não parece telefone brasileiro válido ({bruto}).")
    # ponytail: fixo (10 dígitos) passa — é formato válido, e o campo também serve de
    # telefone de contato. Fixo NÃO tem WhatsApp (ver prospeccao_dia._wa); se o motor
    # for montar link wa.me, quem chama decide com len(retorno) == 13.
    from criacao import telefone_falso   # mesmo detector do QA pós-geração
    if telefone_falso(d):
        raise ErroIntake(f"WhatsApp com cara de placeholder ({bruto}). Coloque o real.")
    return "55" + d


def normalizar_email(valor: str) -> str:
    """Devolve o e-mail em minúsculas ou levanta ErroIntake."""
    e = str(valor or "").strip().lower()
    if not e:
        raise ErroIntake("E-mail vazio.")
    if not _EMAIL.fullmatch(e) or ".." in e:
        raise ErroIntake(f"E-mail inválido ({valor}).")
    if any(f in e for f in _EMAIL_FAKE):
        raise ErroIntake(f"E-mail de exemplo ({valor}). Coloque o real.")
    return e


# ---------------------------------------------------------------- dono

def donos() -> tuple[str, ...]:
    """Lista de donos. Hoje o painel é single-user, então o padrão é ('jp',) e o
    round-robin é inerte — mas a distribuição já é a certa quando entrar o segundo."""
    csv = os.environ.get("LEADS_DONOS", "")
    return tuple(x.strip() for x in csv.split(",") if x.strip()) or DONOS_PADRAO


def dono_de(chave, lista: tuple[str, ...] | None = None) -> str:
    """Round-robin sem estado: o dono é função pura da chave do lead.
    Chave numérica (id do prospect) -> módulo direto, distribuição exata.
    Chave textual (CNPJ formatado, nome) -> md5 truncado, distribuição uniforme."""
    lista = lista or donos()
    s = str(chave or "").strip()
    if not s:
        raise ErroIntake("Sem chave pra atribuir dono (id, cnpj ou nome).")
    n = int(s) if s.isdigit() else int(hashlib.md5(s.encode()).hexdigest()[:12], 16)
    return lista[n % len(lista)]


# ---------------------------------------------------------------- entrada

def triar(briefing: dict, lead_id: int = 0, exigir_email: bool = False) -> dict:
    """PONTO DE ENTRADA. Valida contato e resolve dono num passo só.

    -> {"ok": bool, "erros": {campo: msg}, "whatsapp": str, "email": str, "dono": str}
    Não levanta: devolve os erros pro painel mostrar campo a campo."""
    erros: dict[str, str] = {}
    out = {"whatsapp": "", "email": "", "dono": ""}

    try:
        out["whatsapp"] = normalizar_whatsapp(briefing.get("whatsapp"))
    except ErroIntake as e:
        erros["whatsapp"] = str(e)

    email = (briefing.get("email") or "").strip()
    if email or exigir_email:
        try:
            out["email"] = normalizar_email(email)
        except ErroIntake as e:
            erros["email"] = str(e)

    chave = (lead_id or briefing.get("lead_id") or briefing.get("cnpj")
             or briefing.get("nome_empresa") or briefing.get("nome") or "")
    try:
        out["dono"] = dono_de(chave)
    except ErroIntake as e:
        erros["dono"] = str(e)

    return {"ok": not erros, "erros": erros, **out}


# ---------------------------------------------------------------- backfill

def _db(caminho: str = "") -> sqlite3.Connection:
    p = Path(caminho or os.environ.get(
        "LEADS_DB", str(Path(__file__).resolve().parents[2] / "data" / "leads.db")))
    c = sqlite3.connect(p, timeout=10)
    c.row_factory = sqlite3.Row
    return c


def backfill(aplicar: bool = False, caminho: str = "") -> dict:
    """Atribui dono a quem está sem. Idempotente: só toca linha com dono vazio, e o
    dono é determinístico, então rodar de novo não reatribui nem embaralha.
    Sem --aplicar não escreve NADA no banco (nem o ALTER da coluna)."""
    lista = donos()
    with _db(caminho) as c:
        if not c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND "
                         "name='tracker_prospects'").fetchone():
            raise ErroIntake(f"tracker_prospects não existe em {caminho or 'LEADS_DB'}.")
        col = "dono" in [r[1] for r in c.execute("PRAGMA table_info(tracker_prospects)")]
        if aplicar and not col:   # ALTER idempotente, padrão do operacao._garante_ponte
            c.execute("ALTER TABLE tracker_prospects ADD COLUMN dono TEXT DEFAULT ''")
            col = True
        onde = "WHERE dono IS NULL OR dono=''" if col else ""
        alvos = [r["id"] for r in c.execute(
            f"SELECT id FROM tracker_prospects {onde} ORDER BY id")]
        por_dono: dict[str, int] = {}
        for i in alvos:
            d = dono_de(i, lista)
            por_dono[d] = por_dono.get(d, 0) + 1
            if aplicar:
                c.execute("UPDATE tracker_prospects SET dono=? WHERE id=?", (d, i))
        total = c.execute("SELECT COUNT(*) FROM tracker_prospects").fetchone()[0]
        if aplicar:
            c.commit()
    return {"total": total, "sem_dono": len(alvos), "aplicado": aplicar,
            "por_dono": dict(sorted(por_dono.items()))}


# ---------------------------------------------------------------- check

def _check() -> None:
    import tempfile

    tel_ok = {
        "(14) 99874-5847": "5514998745847",
        "+55 14 99874-5847": "5514998745847",
        "5514998745847": "5514998745847",
        "14998745847": "5514998745847",
        "1498745847": "5514998745847",       # celular antigo, ganha o 9º dígito
        "011 99874-5847": "5511998745847",   # prefixo de operadora
        "14 3234-5678": "551432345678",      # fixo fica com 10 dígitos + DDI
        " 55 (16) 98836-4226 ": "5516988364226",
    }
    for entrada, esperado in tel_ok.items():
        assert normalizar_whatsapp(entrada) == esperado, (entrada, esperado)

    tel_ruim = ("", "abc", "123", "9999-8888", "14 9987-45847999",
                "(00) 99874-5847", "5500998745847", "(14) 89874-5847",
                "5514000000000", "5566999998888", "5514991110009")
    for t in tel_ruim:
        try:
            v = normalizar_whatsapp(t)
        except ErroIntake:
            continue
        raise AssertionError(f"passou telefone ruim: {t!r} -> {v}")

    for e in ("jp@noemi.digital", " JP@Noemi.Digital ", "a.b+c@sub.dominio.com.br"):
        assert normalizar_email(e) == e.strip().lower(), e
    for e in ("", "jp@", "@noemi.digital", "jp noemi.digital", "jp@noemi",
              "jp@@noemi.digital", "a..b@x.com", "contato@exemplo.com", "teste@teste.com"):
        try:
            v = normalizar_email(e)
        except ErroIntake:
            continue
        raise AssertionError(f"passou e-mail ruim: {e!r} -> {v}")

    # round-robin: ids consecutivos distribuem exato; chaves textuais, quase exato
    tres = ("ana", "bruno", "carla")
    cont: dict[str, int] = {}
    for i in range(1, 301):
        cont[dono_de(i, tres)] = cont.get(dono_de(i, tres), 0) + 1
    assert set(cont) == set(tres) and set(cont.values()) == {100}, cont
    cont = {}
    for i in range(600):
        d = dono_de(f"empresa-{i} ltda", tres)
        cont[d] = cont.get(d, 0) + 1
    assert set(cont) == set(tres) and all(160 <= v <= 240 for v in cont.values()), cont
    assert dono_de(42, tres) == dono_de(42, tres) == dono_de("42", tres)   # estável
    assert dono_de("Clínica X", tres) == dono_de("Clínica X", tres)

    # triar: entrada do integrador
    r = triar({"whatsapp": "(14) 99874-5847", "email": "jp@noemi.digital"}, lead_id=7)
    assert r["ok"] and r["whatsapp"] == "5514998745847" and r["dono"] == donos()[0], r
    r = triar({"whatsapp": "123", "email": "xx"}, lead_id=7)
    assert not r["ok"] and set(r["erros"]) == {"whatsapp", "email"}, r
    r = triar({"whatsapp": "1499874-5847", "nome_empresa": "Clínica X"})
    assert r["ok"] and r["dono"], r          # sem lead_id, chave cai no nome
    r = triar({"whatsapp": "(14) 99874-5847"})   # sem chave nenhuma: dono é erro
    assert not r["ok"] and set(r["erros"]) == {"dono"}, r
    assert triar({"whatsapp": "(14) 99874-5847"}, exigir_email=True)["erros"].get("email")

    # backfill em banco temporário — NUNCA no leads.db real
    tmp = Path(tempfile.mkdtemp(suffix="_intake")) / "leads.db"
    with sqlite3.connect(tmp) as c:
        c.execute("CREATE TABLE tracker_prospects (id INTEGER PRIMARY KEY, empresa TEXT)")
        c.executemany("INSERT INTO tracker_prospects (id,empresa) VALUES (?,?)",
                      [(i, f"emp {i}") for i in range(1, 31)])
        c.commit()
    os.environ["LEADS_DONOS"] = "ana,bruno,carla"
    r1 = backfill(aplicar=True, caminho=str(tmp))
    assert r1["total"] == 30 and r1["sem_dono"] == 30, r1
    assert set(r1["por_dono"].values()) == {10}, r1
    r2 = backfill(aplicar=True, caminho=str(tmp))
    assert r2["sem_dono"] == 0 and r2["por_dono"] == {}, r2      # idempotente
    with sqlite3.connect(tmp) as c:
        antes = dict(c.execute("SELECT id,dono FROM tracker_prospects"))
        c.execute("UPDATE tracker_prospects SET dono='zeca' WHERE id=5")
        c.execute("UPDATE tracker_prospects SET dono='' WHERE id=6")
        c.commit()
    r3 = backfill(aplicar=True, caminho=str(tmp))
    assert r3["sem_dono"] == 1, r3                                # só o id=6 voltou
    with sqlite3.connect(tmp) as c:
        depois = dict(c.execute("SELECT id,dono FROM tracker_prospects"))
    assert depois[5] == "zeca", depois[5]                         # dono manual preservado
    assert depois[6] == antes[6], (depois[6], antes[6])           # reatribuição estável
    assert {i: d for i, d in depois.items() if i != 5} == \
           {i: d for i, d in antes.items() if i != 5}
    del os.environ["LEADS_DONOS"]

    # ensaio não grava — nem linha nem coluna
    with sqlite3.connect(tmp) as c:
        c.execute("UPDATE tracker_prospects SET dono=''")
        c.commit()
    assert backfill(aplicar=False, caminho=str(tmp))["sem_dono"] == 30
    with sqlite3.connect(tmp) as c:
        assert c.execute("SELECT COUNT(*) FROM tracker_prospects WHERE dono<>''"
                         ).fetchone()[0] == 0
    virgem = Path(tempfile.mkdtemp(suffix="_intake2")) / "leads.db"
    with sqlite3.connect(virgem) as c:
        c.execute("CREATE TABLE tracker_prospects (id INTEGER PRIMARY KEY, empresa TEXT)")
        c.execute("INSERT INTO tracker_prospects (id,empresa) VALUES (1,'x')"); c.commit()
    assert backfill(aplicar=False, caminho=str(virgem))["sem_dono"] == 1
    with sqlite3.connect(virgem) as c:   # o ensaio NÃO criou a coluna
        assert "dono" not in [r[1] for r in c.execute("PRAGMA table_info(tracker_prospects)")]
    try:
        backfill(caminho=str(Path(virgem).parent / "vazio.db"))
        raise AssertionError("banco sem a tabela devia dar erro claro")
    except ErroIntake:
        pass

    print("intake OK — telefone, e-mail, round-robin e backfill idempotente")


if __name__ == "__main__":
    if "--check" in sys.argv:
        _check()
    elif "--backfill" in sys.argv:
        print(backfill(aplicar="--aplicar" in sys.argv))
    else:
        print(__doc__)
