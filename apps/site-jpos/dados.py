"""Os números e a vitrine do jpos.com.br — colhidos, nunca digitados.

Por que existe: o site vendia com adjetivo ("sites que vendem") e zero prova. A prova
existe no disco e no banco há semanas — 74 sites no ar, o tempo real de cada geração,
o vocabulário de 128 nichos que o motor usa pra decidir. Este módulo lê isso e devolve
um JSON. Nenhum número do site é escrito à mão: se cair pra 70 sites, o site diz 70.

Regra: número sem procedência não sai daqui (mesma regra de `motores.py`). Onde a fonte
não existe, o campo vem `None` e a página omite o bloco — nunca inventa zero.
"""
from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

_RAIZ = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_RAIZ / "packages"))
sys.path.insert(0, str(_RAIZ / "apps" / "painel-operacoes"))

SITES_DIR = Path(os.environ.get("SITE_OUT_DIR", "/var/www/sites"))
BASE_SITES = os.environ.get("SITE_BASE_URL", "https://p.jpos.com.br")

# Vitrine: um por nicho, para o visitante ver RANGE e não repetição. O motor faz o
# mesmo com estilos — variedade dentro do nicho, identidade entre nichos.
VITRINE_MAX = 9

# `<nicho> em <cidade> | <Nome>` — o padrão que o motor escreve em TODO <title>.
_TITULO_RX = re.compile(r"^(?P<nicho>[^|]+?)\s+em\s+(?P<cidade>[^|]+?)\s*\|\s*(?P<nome>.+)$")


def _titulo_e_h1(idx: Path) -> tuple[str, str]:
    """Nome do negócio como o SITE se apresenta — não derivado do slug.

    Derivar "Forno de Lenha" de `demo-pizzaria-forno-de-lenha` seria inventar razão
    social. O <title> foi escrito pelo motor a partir do briefing real, então é o
    dado, não um palpite.
    """
    html = idx.read_text(encoding="utf-8", errors="ignore")[:20000]
    t = re.search(r"<title[^>]*>(.*?)</title>", html, re.S | re.I)
    h = re.search(r"<h1[^>]*>(.*?)</h1>", html, re.S | re.I)
    limpa = lambda s: re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", s or "")).strip()
    return limpa(t.group(1) if t else ""), limpa(h.group(1) if h else "")


_DEMO_RX = re.compile(r"\s*\((?:demo[^)]*|teste[^)]*)\)\s*$", re.I)
# "escritório de advocacia" e "advocacia" são o MESMO card de vitrine; "clínica de
# estética" e "clínica odontológica" NÃO são. Só os genéricos de invólucro caem.
_INVOLUCRO_RX = re.compile(r"^(escrit[oó]rio de|loja de|casa de)\s+", re.I)


def _norm_nicho(n: str) -> str:
    import unicodedata
    s = _INVOLUCRO_RX.sub("", (n or "").strip().lower())
    s = "".join(c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn")
    return s.rstrip("s")


def _ficha_do_titulo(titulo: str) -> dict | None:
    """Quebra o <title> em nicho/cidade/nome. `None` se não seguir o padrão do motor.

    Não casar é um FILTRO, não uma perda: quem fica de fora são os sites de teste do
    próprio motor ("Odonto Motion v2"), que nunca tiveram cliente e não provam nada
    pra quem visita.
    """
    m = _TITULO_RX.match(titulo or "")
    if not m:
        return None
    d = {k: v.strip() for k, v in m.groupdict().items()}
    # "(demo catálogo T2)" sai do NOME e vira selo: o card fica limpo sem esconder
    # que aquilo é demonstração — quem visita merece saber qual é qual.
    d["demo"] = bool(_DEMO_RX.search(d["nome"]))
    d["nome"] = _DEMO_RX.sub("", d["nome"]).strip()
    return d


def _fichas() -> list[dict]:
    """Todo site no ar que se apresenta no padrão do motor, com sua ficha."""
    import criacao

    out = []
    for s in criacao.listar_sites():
        if s["status"] != "no ar":
            continue
        idx = SITES_DIR / s["slug"] / "index.html"
        if not idx.exists():
            continue
        titulo, h1 = _titulo_e_h1(idx)
        f = _ficha_do_titulo(titulo)
        if not f:
            continue
        out.append({**f, "slug": s["slug"], "chamada": h1, "kb": s.get("kb", 0),
                    "movimento": bool(s.get("motion")), "video": bool(s.get("video")),
                    "url": f"{BASE_SITES}/{s['slug']}/"})
    return out


def _tempos() -> list[float]:
    """Segundos de cada geração, lidos das FICHA.md que o motor já escrevia."""
    out = []
    for f in SITES_DIR.glob("*/FICHA.md"):
        m = re.search(r"levou ([0-9.]+)s", f.read_text(encoding="utf-8", errors="ignore")[:2000])
        if m and float(m.group(1)) > 0:  # 0.0s = geração que falhou antes de medir
            out.append(float(m.group(1)))
    return sorted(out)


def numeros(fichas: list[dict] | None = None) -> dict:
    import criacao
    import vocabulario as v

    fichas = _fichas() if fichas is None else fichas
    no_ar = [s for s in criacao.listar_sites() if s["status"] == "no ar"]
    t = _tempos()
    return {
        "sites_no_ar": len(no_ar),
        "com_movimento": sum(1 for s in no_ar if s.get("motion")),
        "cidades": len({f["cidade"].lower() for f in fichas}) or None,
        "nichos_entregues": len({f["nicho"].lower() for f in fichas}) or None,
        "nichos_catalogados": sum(len(x) for x in v.NICHOS.values()),
        "familias": len(v.NICHOS),
        "blocos": len(v.ESTRUTURAS_LISTA),
        "mediana_s": round(t[len(t) // 2], 1) if t else None,
        "geracoes_medidas": len(t) or None,
    }


def vitrine(fichas: list[dict] | None = None) -> list[dict]:
    """Sites reais, um por nicho, com o nome e a cidade que cada um usa de verdade."""
    fichas = _fichas() if fichas is None else fichas
    vistos: set[str] = set()
    out: list[dict] = []
    # kb desc: entre dois do mesmo nicho, o mais cheio é o que mostra melhor o motor
    for f in sorted(fichas, key=lambda x: -x["kb"]):
        chave = _norm_nicho(f["nicho"])
        if chave in vistos or len(out) >= VITRINE_MAX:
            continue
        vistos.add(chave)
        out.append(f)
    return out


def vocabulario_motor() -> dict:
    """O que o motor sabe: famílias, nichos e blocos — com o PORQUÊ de cada escolha.

    É o material do preview ao vivo. O visitante digita "pizzaria" e vê a decisão que
    o motor tomaria e a razão dela, na linguagem do próprio motor. Descrever isso em
    copy ("usamos IA") não convence ninguém; mostrar a decisão, convence.
    """
    import estilos
    import vocabulario as v

    fams = {}
    for fam, nichos in v.NICHOS.items():
        p = estilos.PERFIS.get(fam) or {}
        principal = (p.get("principais")
                     or [["minimal", "página limpa deixa o contato achar o olho primeiro"]])[0]
        acentos = p.get("acentos") or []
        fams[fam] = {
            "nichos": sorted(nichos),
            "estilo": principal[0],
            "porque": principal[1],
            "acento": ({"secao": acentos[0]["secao"], "estilo": acentos[0]["estilo"],
                        "porque": acentos[0]["porque"]} if acentos else None),
        }
    blocos: dict[str, list] = {}
    for e in v.ESTRUTURAS_LISTA:
        blocos.setdefault(e["familia"], []).append({"nome": e["nome"], "oque": e["oque"]})
    return {"familias": fams, "blocos": blocos}


def precos() -> dict:
    """Lido de `painel-operacoes/precos.json`, que já é a FONTE ÚNICA de preço da casa.

    O site não guarda preço próprio de propósito: duas tabelas divergem no dia em que
    alguém corrige uma só, e a que fica errada é sempre a que o cliente está lendo.
    """
    import json as _j
    d = _j.loads((_RAIZ / "apps" / "painel-operacoes" / "precos.json").read_text(encoding="utf-8"))
    tiers = [{"id": t["id"], "nome": t["nome"], "setup": t["setup"], "mensal": t.get("mensal"),
              "entrega": t.get("entrega", [])} for t in d["tiers"]]
    return {"moeda": d.get("moeda", "R$"), "tiers": tiers,
            "entrada": min(t["setup"] for t in tiers if t.get("setup")),
            "atualizado_em": d.get("_atualizado_em")}


def tudo() -> dict:
    f = _fichas()
    return {"numeros": numeros(f), "vitrine": vitrine(f), "motor": vocabulario_motor(),
            "precos": precos()}


if __name__ == "__main__":
    if os.environ.get("DADOS_SELFTEST"):
        # o parser é o filtro da vitrine: se ele afrouxar, site de teste entra
        assert _ficha_do_titulo("ótica em Lins | Ótica Visão Lins") == {
            "nicho": "ótica", "cidade": "Lins", "nome": "Ótica Visão Lins", "demo": False}
        assert _ficha_do_titulo("Odonto Motion v2 — odontologia") is None
        d = _ficha_do_titulo("cabeleireiro em Bauru | Trend Salon (demo catálogo EX)")
        assert d["nome"] == "Trend Salon" and d["demo"] is True, d
        assert _norm_nicho("Escritório de Advocacia") == _norm_nicho("advocacia")
        assert _norm_nicho("clínica de estética") != _norm_nicho("clínica odontológica")
        assert _ficha_do_titulo("") is None

        d = tudo()
        n = d["numeros"]
        assert n["sites_no_ar"] > 0, n
        assert n["nichos_catalogados"] > 50, "vocabulário do motor não carregou"
        assert n["mediana_s"] and 1 < n["mediana_s"] < 300, n
        assert 3 <= len(d["vitrine"]) <= VITRINE_MAX, len(d["vitrine"])
        assert all(x["nome"] and x["url"].startswith("http") for x in d["vitrine"])
        # um nicho por card: dois "ótica" na vitrine é repetição, não portfólio
        nichos = [_norm_nicho(x["nicho"]) for x in d["vitrine"]]
        assert len(nichos) == len(set(nichos)), nichos
        # o preview depende de família -> estilo + porquê; sem isso a demo vira lorem
        fam = d["motor"]["familias"]
        assert len(fam) >= 5 and all(f["estilo"] and f["porque"] for f in fam.values())
        assert sum(len(v) for v in d["motor"]["blocos"].values()) > 50
        # preço vem da fonte única; se alguém apagar um tier, o site não inventa outro
        pr = d["precos"]
        assert pr["entrada"] > 0 and len(pr["tiers"]) >= 3, pr
        assert all(t["nome"] and t["setup"] for t in pr["tiers"]), pr
        print(f"dados OK — {n['sites_no_ar']} sites no ar, mediana {n['mediana_s']}s "
              f"({n['geracoes_medidas']} medidas), {len(d['vitrine'])} na vitrine sem nicho "
              f"repetido, {n['nichos_entregues']} nichos entregues em {n['cidades']} cidades, "
              f"{n['nichos_catalogados']} catalogados")
    else:
        print(json.dumps(tudo(), ensure_ascii=False, indent=1))
