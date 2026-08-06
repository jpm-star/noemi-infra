#!/usr/bin/env python3
"""DIVERSIFICADOR DE ESQUELETO — o site novo não sai com a cara do concorrente da rua.

Antes de aplicar a receita (ordem das seções), olha os sites JÁ PUBLICADOS do MESMO
segmento na MESMA cidade. Se o topo da página bate com o de um concorrente direto, veta
a receita e escolhe outra do pool (`receitas.pool` = defaults do segmento + referências
aprovadas). Biblioteca esgotada NUNCA trava a geração: mantém a escolha e registra.

Como se sabe o esqueleto de um site publicado: lendo o `index.html` no disco. A tabela
`sites_gerados` não guarda a receita, e o FICHA.md só existe em 5 de 53 sites — mas o
motor monta o corpo na ordem da receita (motor-site/app/providers/template_real.py:556),
então a ordem dos marcadores no HTML É o esqueleto que foi ao ar.

Decisão é consulta a banco + comparação de listas: determinístico, sem LLM.
Self-check offline: `python3 diversificador.py --check`.
"""
from __future__ import annotations

import json
import os
import re
import sqlite3
import unicodedata
from datetime import datetime, timezone
from pathlib import Path

_AQUI = Path(__file__).resolve().parent
LOG = Path(os.environ.get("NOEMI_DATA_DIR", str(_AQUI.parents[1] / "data"))) / "diversificador.log"

# marcador único no HTML publicado -> bloco da receita
_MARCA = {
    "<main>": "sobre",
    'id="servicos"': "catalogo_motion",
    'id="o-que-inclui"': "catalogo",
    'id="antes-depois"': "antesdepois",
    'id="planos"': "preco",
    'id="simular"': "calculadora",
    'id="depoimentos"': "depoimentos",
    'id="faq"': "faq",
    'id="contato-form"': "formulario",
}

# Quantos blocos do topo definem "mesma cara". O visitante compara o que vê antes de
# rolar; divergir só no rodapé não diferencia nada.
TOPO = 3


def _sem_acento(s: str) -> str:
    return unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode()


def _cidade(s: str) -> str:
    """'São José do Rio Preto/SP' e 'sao jose do rio preto' viram a mesma chave."""
    s = _sem_acento(str(s or "")).lower().split("/")[0]
    s = re.sub(r"\s+-\s+[a-z]{2}\s*$", "", s)          # 'Bauru - SP'
    return re.sub(r"[^a-z0-9]+", "-", s).strip("-")


def esqueleto(slug: str, sites_dir: str | Path | None = None) -> list[str]:
    """Ordem das seções de um site publicado, lida do HTML no disco. [] se não der."""
    if sites_dir is None:
        import criacao
        sites_dir = criacao.SITES_DIR
    try:
        html = (Path(sites_dir) / slug / "index.html").read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return []
    return [b for pos, b in sorted((html.find(m), b) for m, b in _MARCA.items()) if pos >= 0]


def _publicados(con: sqlite3.Connection | None = None) -> list[dict]:
    """Sites publicados com segmento e cidade. Dedup por slug (regerar insere linha nova)."""
    import criacao
    import operacao
    c = con or criacao._db_noemi()
    operacao._garante_ponte(c)
    linhas, vistos = [], set()
    for r in c.execute("SELECT cliente,segmento,slug,prospect_id FROM sites_gerados ORDER BY id DESC"):
        d = dict(r)
        if d["slug"] in vistos:
            continue
        vistos.add(d["slug"])
        linhas.append(d)
    # ponytail: NÃO chama operacao.vincular() — é escrita em banco no meio de uma leitura
    # do caminho de geração. Site órfão de lead cai no casamento por slug, abaixo.
    leads = operacao._leads_por_id({x["prospect_id"] for x in linhas if x["prospect_id"]})
    for x in linhas:
        x["cidade"] = (leads.get(x["prospect_id"] or 0) or {}).get("cidade_uf", "")
    return linhas


def concorrentes(nicho: str, cidade: str, *, con: sqlite3.Connection | None = None,
                 sites: list[dict] | None = None, sites_dir: str | Path | None = None,
                 ignorar_slug: str = "") -> list[dict]:
    """Sites publicados do mesmo segmento na mesma cidade, com o esqueleto de cada um."""
    import receitas as _rec
    seg = _rec.segmento_de(nicho)
    cid = _cidade(cidade)
    if not seg or not cid:      # sem segmento ou sem cidade não existe "concorrente direto"
        return []
    fora = []
    for s in (sites if sites is not None else _publicados(con)):
        if s.get("slug") == ignorar_slug or _rec.segmento_de(s.get("segmento") or "") != seg:
            continue
        # cidade vem do lead vinculado; sem vínculo, o slug costuma carregar a cidade
        # (ex: 'academia-red-dragon-gym-presidente-prudente')
        mesma = _cidade(s.get("cidade") or "") == cid or (len(cid) >= 4 and cid in (s.get("slug") or ""))
        if not mesma:
            continue
        ordem = esqueleto(s["slug"], sites_dir)
        if ordem:
            fora.append({"slug": s["slug"], "cliente": s.get("cliente") or "", "ordem": ordem})
    return fora


def _colide(a: list[str], b: list[str]) -> bool:
    return bool(a) and bool(b) and a[:TOPO] == b[:TOPO]


def _dist(a: list[str], b: list[str]) -> int:
    """Quantas posições diferem (sobra de tamanho conta como diferença)."""
    n = min(len(a), len(b))
    return sum(a[i] != b[i] for i in range(n)) + abs(len(a) - len(b))


def _registrar(linha: dict) -> None:
    try:
        LOG.parent.mkdir(parents=True, exist_ok=True)
        with LOG.open("a", encoding="utf-8") as f:
            f.write(json.dumps(linha, ensure_ascii=False) + "\n")
    except OSError:
        pass    # log é auditoria, não pode derrubar geração


def diversificar(nicho: str, cidade: str, receita: dict, *, semente: int = 0,
                 con: sqlite3.Connection | None = None, sites: list[dict] | None = None,
                 sites_dir: str | Path | None = None, registrar: bool = True) -> dict:
    """Recebe a receita já escolhida e devolve a receita A USAR (mesma ou trocada).

    Nunca levanta nem devolve vazio: na dúvida mantém a original. A decisão vai junto,
    na chave `diversificador`, pra cair no FICHA.md e no log de auditoria."""
    ordem = list(receita.get("ordem") or [])
    dec = {"vetada": "", "colidiu_com": [], "escolhida": receita.get("nome", ""),
           "alternativas": 0, "motivo": ""}
    try:
        conc = concorrentes(nicho, cidade, con=con, sites=sites, sites_dir=sites_dir)
        batidos = [c for c in conc if _colide(ordem, c["ordem"])]
        if not conc:
            dec["motivo"] = "nenhum concorrente publicado no segmento+cidade"
        elif not batidos:
            dec["motivo"] = f"sem colisão ({len(conc)} concorrente(s) olhado(s))"
        else:
            import receitas as _rec
            dec["colidiu_com"] = [{"slug": c["slug"], "cliente": c["cliente"]} for c in batidos]
            alt = [r for r in _rec.pool(nicho, con) if r.get("nome") != receita.get("nome")
                   and not any(_colide(_rec._norm_ordem(r.get("ordem")), c["ordem"]) for c in conc)]
            dec["alternativas"] = len(alt)
            if not alt:
                dec["motivo"] = "colidiu mas a biblioteca do segmento esgotou — mantida"
            else:
                # mais distante do concorrente mais parecido; empate = rotação pela semente
                # (lead_id), que é o mesmo critério do sorteio original.
                # ponytail: sem LLM — a ordem é lista de blocos, comparação exata resolve.
                pont = {r["nome"]: min(_dist(_rec._norm_ordem(r.get("ordem")), c["ordem"]) for c in conc)
                        for r in alt}
                melhor = max(pont.values())
                top = sorted([r for r in alt if pont[r["nome"]] == melhor], key=lambda r: r["nome"])
                nova = dict(top[semente % len(top)])
                nova["ordem"] = _rec._norm_ordem(nova.get("ordem")) or _rec.ORDEM_DEFAULT
                dec.update(vetada=receita.get("nome", ""), escolhida=nova["nome"],
                           motivo=f"esqueleto igual ao de {batidos[0]['cliente'] or batidos[0]['slug']}")
                receita = nova
    except Exception as e:      # noqa: BLE001 — diversificar é melhoria; falhar aqui não pode barrar site
        dec["motivo"] = f"erro, receita mantida: {type(e).__name__}: {e}"[:200]
    if registrar:
        _registrar({"em": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                    "nicho": nicho, "cidade": cidade, "semente": semente, **dec})
    return {**receita, "diversificador": dec}


# ─────────────────────────────────── self-check ───────────────────────────────────

def _check() -> None:
    """Offline: sem rede, sem banco de produção. HTML falso em tmp + pool em memória."""
    import tempfile
    import sys
    sys.path.insert(0, str(_AQUI))
    import receitas as _rec

    global LOG
    tmp = Path(tempfile.mkdtemp(prefix="diversificador-check-"))
    LOG = tmp / "diversificador.log"
    sites_dir = tmp / "sites"
    con = sqlite3.connect(":memory:")   # pool sem noemi.db: só as receitas default
    con.row_factory = sqlite3.Row
    _rec._tabela(con)

    inv = {b: m for m, b in _MARCA.items()}

    def publicar(slug: str, ordem: list[str]) -> None:
        d = sites_dir / slug
        d.mkdir(parents=True, exist_ok=True)
        (d / "index.html").write_text("\n".join(inv[b] for b in ordem), encoding="utf-8")

    ac = _rec.RECEITAS["academia"]
    r0, r1 = ac[0], ac[1]                       # experimental-primeiro, prova-primeiro
    publicar("academia-rival-bauru", r0["ordem"])
    assert esqueleto("academia-rival-bauru", sites_dir) == r0["ordem"], "HTML → esqueleto"
    sites = [{"slug": "academia-rival-bauru", "cliente": "Rival Fit",
              "segmento": "academia de musculação", "cidade": "Bauru/SP"}]
    arg = dict(con=con, sites=sites, sites_dir=sites_dir)

    # 1. sem colisão: mesma cidade, esqueleto diferente -> mantém
    a = diversificar("academia", "Bauru", r1, semente=7, **arg)
    assert a["nome"] == r1["nome"] and not a["diversificador"]["vetada"], a["diversificador"]

    # 1b. mesmo esqueleto, OUTRA cidade -> não é concorrente direto, mantém
    b = diversificar("academia", "Marília", r0, semente=7, **arg)
    assert b["nome"] == r0["nome"] and b["diversificador"]["colidiu_com"] == [], b["diversificador"]

    # 2. colisão: troca, e o log conta quem vetou contra quem
    c = diversificar("academia", "bauru", r0, semente=0, **arg)
    d = c["diversificador"]
    assert c["nome"] != r0["nome"], c
    assert d["vetada"] == r0["nome"] and d["colidiu_com"][0]["slug"] == "academia-rival-bauru", d
    assert c["ordem"][:TOPO] != r0["ordem"][:TOPO] and c["ordem"], c
    linhas = [json.loads(x) for x in LOG.read_text(encoding="utf-8").splitlines()]
    assert linhas[-1]["vetada"] == r0["nome"] and linhas[-1]["escolhida"] == c["nome"], linhas[-1]
    assert len(linhas) == 3, "toda decisão é logada, inclusive as que não trocam"

    # 2b. determinístico: mesma entrada, mesma saída
    assert diversificar("academia", "bauru", r0, semente=0, **arg)["nome"] == c["nome"]

    # 3. biblioteca esgotada (todo o pool colide) -> não trava, mantém e registra
    for i, r in enumerate(ac):
        publicar(f"academia-rival-{i}-bauru", r["ordem"])
    todos = [{"slug": f"academia-rival-{i}-bauru", "cliente": f"Rival {i}",
              "segmento": "academia", "cidade": "Bauru/SP"} for i in range(len(ac))]
    e = diversificar("academia", "Bauru", r0, semente=3, con=con, sites=todos, sites_dir=sites_dir)
    assert e["nome"] == r0["nome"] and e["ordem"] == r0["ordem"], e
    assert "esgot" in e["diversificador"]["motivo"], e["diversificador"]

    # 4. nicho sem cidade / segmento desconhecido -> passa reto, sem tocar em disco
    f = diversificar("xyz", "", r0, semente=1, con=con, sites=sites, sites_dir=sites_dir)
    assert f["nome"] == r0["nome"] and f["diversificador"]["colidiu_com"] == [], f

    # 5. receita quebrada não derruba a geração
    g = diversificar("academia", "Bauru", {"nome": "x", "ordem": None}, semente=1, **arg)
    assert g["nome"] == "x", g

    print(f"ok — 1 sem colisão · 1 outra cidade · troca+log · esgotada · sem segmento · receita vazia\nlog: {LOG}")


if __name__ == "__main__":
    import sys
    if "--check" in sys.argv:
        _check()
    else:
        print(__doc__)
