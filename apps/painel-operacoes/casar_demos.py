"""Liga cada site gerado ao lead do CRM que ele representa — preenche `demo_url`.

O BURACO QUE ISTO TAPA (medido em 2026-08-16): `tracker_prospects` tem 1.532 leads e
1.532 deles com `demo_url` VAZIA. Havia 74 sites no ar e nenhum apontado por lead nenhum.
Os dois lados existiam há semanas e nunca se tocaram — não é que a abordagem não converta,
é que na hora de abordar não há o que mandar. O funil não morreu no meio: nunca teve elo.

POR QUE PELO <title> E NÃO PELO SLUG: o slug é texto colado ("academia-bellator-assis").
Casar por pedaço de slug faz `red-dragon-gym-presidente-prudente` casar com `CORE
Odontologia Presidente Prudente` — os dois têm "presidente prudente", que é a CIDADE.
Token que aparece em centenas de registros (academia, clínica, o nome da cidade) não
distingue ninguém. O <title> que o motor escreveu é `nicho em cidade | Nome`, então dá o
nome e a cidade SEPARADOS: a cidade vira filtro (derruba o par errado) em vez de virar
evidência (que foi o que criou o falso positivo).

Regra do casamento, conservadora de propósito — um demo mandado pra empresa errada é
pior que demo nenhum:
  · pelo menos UM token distintivo em comum (fora segmento, cidade e sufixo de empresa);
  · a cidade tem que bater; sem cidade nos dois lados, exige DOIS tokens distintivos;
  · empate (dois prospects com o mesmo score) não casa nada — ambiguidade não é palpite.

Rodar:  python casar_demos.py            # dry-run, mostra o que casaria
        python casar_demos.py --aplicar  # grava demo_url nos leads
        python casar_demos.py --check    # autoteste, sem tocar em banco
Idempotente: só grava onde `demo_url` está vazia.
"""
from __future__ import annotations

import os
import re
import sqlite3
import sys
import unicodedata
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]
SITES_DIR = Path(os.environ.get("SITE_OUT_DIR", "/var/www/sites"))
BASE_SITES = os.environ.get("SITE_BASE_URL", "https://p.jpos.com.br")
LEADS_DB = Path(os.environ.get("LEADS_DB", str(RAIZ / "data" / "leads.db")))

# `nicho em cidade | Nome` — o padrão que o motor escreve em todo <title>
_TITULO_RX = re.compile(r"^(?P<nicho>[^|]+?)\s+em\s+(?P<cidade>[^|]+?)\s*\|\s*(?P<nome>.+)$")
_DEMO_RX = re.compile(r"\s*\((?:demo[^)]*|teste[^)]*)\)\s*$", re.I)

# Palavras que NÃO identificam ninguém: ou são o ramo, ou a forma jurídica. Se o casamento
# depender só delas, casou com o ramo, não com a empresa.
_GENERICAS = {
    "academia", "academias", "gym", "fit", "fitness", "studio", "clinica", "clinicas",
    "odontologia", "odontologica", "odonto", "consultorio", "advogados", "advocacia",
    "escritorio", "imobiliaria", "imoveis", "pet", "shop", "petshop", "racoes", "racao",
    "restaurante", "pizzaria", "padaria", "salao", "cabeleireiro", "barbearia", "estetica",
    "centro", "espaco", "casa", "loja", "empresa", "grupo", "servicos", "solucoes",
    "ltda", "eireli", "epp", "mei", "sa", "cia", "com", "unidade", "filial", "matriz",
    # rodada 2: cada uma destas produziu um par errado no dry-run sobre o acervo real
    "dental", "dentaria", "dentario", "associados", "associado", "odontologico",
    "medica", "medico", "veterinaria", "veterinario", "auto", "center", "mecanica",
    "contabil", "contabilidade", "agropecuaria", "oficina",
}


def _norm(s: str) -> str:
    s = unicodedata.normalize("NFD", (s or "").lower())
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    return re.sub(r"[^a-z0-9]+", " ", s).strip()


def _tokens(nome: str, cidade: str = "") -> set[str]:
    """Tokens DISTINTIVOS: tira ramo, forma jurídica e o nome da cidade.

    A cidade sai porque ela é comparada à parte. Deixá-la aqui é o que fazia dois negócios
    da mesma cidade casarem entre si."""
    fora = _GENERICAS | set(_norm(cidade).split())
    return {t for t in _norm(nome).split() if len(t) > 2 and t not in fora}


def _titulo(idx: Path) -> str:
    t = re.search(r"<title[^>]*>(.*?)</title>",
                  idx.read_text(encoding="utf-8", errors="ignore")[:20000], re.S | re.I)
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", t.group(1) if t else "")).strip()


def sites() -> list[dict]:
    """Sites no disco com nome e cidade lidos do <title>. Sem <title> no padrão, fora:
    é site de teste do motor, que não representa cliente nenhum."""
    if not SITES_DIR.exists():
        return []
    out = []
    for d in sorted(SITES_DIR.iterdir()):
        idx = d / "index.html"
        if not d.is_dir() or d.name.startswith("_") or not idx.is_file():
            continue
        m = _TITULO_RX.match(_titulo(idx))
        if not m:
            continue
        nome = _DEMO_RX.sub("", m.group("nome")).strip()
        out.append({"slug": d.name, "nome": nome, "cidade": m.group("cidade").strip(),
                    "nicho": m.group("nicho").strip(), "url": f"{BASE_SITES}/{d.name}/"})
    return out


def _familia(termo: str) -> str:
    """Família do motor pra um ramo ('dentista' -> 'odontologia'). '' se desconhecido.

    Reusa o vocabulário que o motor já usa pra decidir estilo — o CRM grava segmento com
    as MESMAS palavras ('clínica odontológica', 'pet shop'), então os dois lados falam a
    mesma língua sem tabela de-para nova."""
    try:
        import vocabulario
        return vocabulario.segmento_do_nicho(termo or "") or ""
    except Exception:  # noqa: BLE001 — sem vocabulário o filtro só não aperta
        return ""


def _score(site: dict, emp: str, cidade_lead: str, seg_lead: str = "") -> float:
    """Quanto este lead parece ser o dono deste site. 0 = não casa."""
    ts = _tokens(site["nome"], site["cidade"])
    te = _tokens(emp, cidade_lead)
    if not ts or not te:
        return 0.0
    # RAMO DIFERENTE NÃO CASA, por mais parecido que seja o nome. Foi assim que o site de
    # odontologia "vida nova" casou com a VIDA Academia: dois tokens em comum, ramos
    # opostos. Só filtra quando as duas famílias são conhecidas — nicho fora do catálogo
    # não pode derrubar um casamento bom.
    fs, fl = _familia(site.get("nicho", "")), _familia(seg_lead)
    if fs and fl and fs != fl:
        return 0.0
    comum = ts & te
    if not comum:
        return 0.0
    mesma_cidade = bool(_norm(site["cidade"])) and _norm(site["cidade"]) == _norm(cidade_lead)
    # sem confirmação de cidade, um único token em comum é coincidência barata
    if not mesma_cidade and len(comum) < 2:
        return 0.0
    # token longo pesa mais: "bellator" identifica, "vip" não
    return len(comum) + sum(0.5 for t in comum if len(t) >= 7) + (1.0 if mesma_cidade else 0.0)


def casar(leads: list[tuple], lista: list[dict] | None = None) -> tuple[list[dict], list[dict]]:
    """(casados, ambíguos). `leads` = [(id, empresa, cidade_uf, telefone, demo_url, segmento)].

    Empate NÃO casa: dois leads com o mesmo score sobre o mesmo site é ambiguidade real, e
    escolher um dos dois é chutar em cima do telefone de um dono de negócio."""
    casados, ambiguos = [], []
    for s in lista if lista is not None else sites():
        notas = [(_score(s, e, c, g), i, e, c, t, d) for i, e, c, t, d, g in leads]
        notas = sorted([x for x in notas if x[0] > 0], key=lambda x: -x[0])
        if not notas:
            continue
        if len(notas) > 1 and notas[0][0] == notas[1][0]:
            ambiguos.append({**s, "candidatos": [n[2] for n in notas[:3]]})
            continue
        n = notas[0]
        casados.append({**s, "score": n[0], "lead_id": n[1], "empresa": n[2],
                        "cidade_lead": n[3], "telefone": n[4], "demo_atual": n[5]})
    return casados, ambiguos


def aplicar(casados: list[dict], db: Path = LEADS_DB) -> int:
    """Grava `demo_url` só onde está vazia. Não sobrescreve: se alguém já apontou um demo
    à mão, a escolha humana ganha do palpite do matcher."""
    novos = [(c["url"], c["lead_id"]) for c in casados if not (c["demo_atual"] or "").strip()]
    if not novos:
        return 0
    with sqlite3.connect(db) as c:
        c.executemany("UPDATE tracker_prospects SET demo_url=? WHERE id=? AND "
                      "(demo_url IS NULL OR demo_url='')", novos)
        c.commit()
    return len(novos)


def _leads(db: Path = LEADS_DB) -> list[tuple]:
    with sqlite3.connect(db) as c:
        return list(c.execute("SELECT id, empresa, cidade_uf, telefone, demo_url, segmento "
                              "FROM tracker_prospects"))


def _autoteste() -> None:
    """Os falsos positivos reais que o matcher ingênuo produziu, virados em trava."""
    leads = [
        (1, "Academia Bellator", "Assis", "(18) 99636-3839", "", "academia"),
        (2, "CORE Odontologia Presidente Prudente", "Presidente Prudente", "(18) 3928-0955",
         "", "clínica odontológica"),
        (3, "Clínica Odontológica Sorriso Mania", "Sumaré", "(19) 3883-5127", "", "dentista"),
        (4, "Academia Bellator", "Bauru", "(14) 90000-0000", "", "academia"),
        (5, "VIDA Academia", "Bauru", "(14) 3227-7330", "", "academia"),
    ]
    def s(nome, cidade, slug="x", nicho=""):
        return {"slug": slug, "nome": nome, "cidade": cidade, "nicho": nicho, "url": "u"}

    ok, amb = casar(leads, [s("Academia Bellator", "Assis", nicho="academia")])
    assert len(ok) == 1 and ok[0]["lead_id"] == 1, ok
    # ramo diferente não casa nem com dois tokens e a cidade certa (o caso "vida nova")
    ok, _ = casar(leads, [s("Vida Nova", "Bauru", nicho="odontologia")])
    assert ok == [], ok
    # o falso positivo que motivou o módulo: só a CIDADE em comum não casa
    ok, amb = casar(leads, [s("Red Dragon Gym", "Presidente Prudente")])
    assert ok == [] and amb == [], (ok, amb)
    # "clínica" + "sorriso" com cidade diferente: genérica não conta, sobra 1 token
    ok, _ = casar(leads, [s("Clínica Sorriso", "Bauru")])
    assert ok == [], ok
    # mesmo nome em duas cidades: a cidade desempata, não vira ambiguidade
    ok, _ = casar(leads, [s("Academia Bellator", "Bauru")])
    assert len(ok) == 1 and ok[0]["lead_id"] == 4, ok
    # empate real não casa nada
    ok, amb = casar([(1, "Studio Alfa Beta", "Lins", "", "", ""),
                     (2, "Studio Alfa Beta", "Lins", "", "", "")],
                    [s("Studio Alfa Beta", "Lins")])
    assert ok == [] and len(amb) == 1, (ok, amb)
    # demo_url já preenchida à mão não é sobrescrita
    assert [c for c in casar([(1, "Academia Bellator", "Assis", "", "https://ja.tem/", "academia")],
                             [s("Academia Bellator", "Assis")])[0]
            if not c["demo_atual"]] == []
    assert _tokens("Academia Bellator", "Assis") == {"bellator"}
    assert _tokens("Espaço Vip", "Adamantina") == {"vip"}
    print("casar_demos OK — cidade em comum não casa, ramo diferente não casa, genérica "
          "não conta, empate não chuta, cidade desempata homônimo, demo à mão fica")


if __name__ == "__main__":
    if "--check" in sys.argv[1:]:
        _autoteste()
        raise SystemExit(0)
    todos = sites()
    leads = _leads()
    casados, ambiguos = casar(leads, todos)
    pendentes = [c for c in casados if not (c["demo_atual"] or "").strip()]
    print(f"{len(todos)} sites com <title> do motor · {len(leads)} leads no CRM")
    print(f"{len(casados)} casados · {len(pendentes)} sem demo_url ainda · "
          f"{len(ambiguos)} ambíguos (não casam)\n")
    for c in sorted(pendentes, key=lambda x: -x["score"]):
        print(f"  {c['score']:>4.1f}  {c['empresa'][:32]:<32} {c['cidade_lead'][:14]:<14} "
              f"{c['telefone'] or '—':<17} {c['slug']}")
    for a in ambiguos:
        print(f"  ????  {a['nome'][:32]:<32} ambíguo entre: {', '.join(a['candidatos'])}")
    if "--aplicar" in sys.argv[1:]:
        print(f"\ngravados: {aplicar(casados)} demo_url")
    elif pendentes:
        print("\nnada gravado. rode com --aplicar pra valer.")
