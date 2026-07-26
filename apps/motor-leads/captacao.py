"""Motor de captação de leads (Noemi Digital) — orquestra as 4 camadas.

coleta (Places) → enriquecimento (fetch+regex) → scoring (fórmula) → saída
(banco+CSV+Sheet). ZERO LLM em todas. Rodar por cron semanal.

  python captacao.py --cidades "Lins" --limite 20        # piloto 1 cidade
  python captacao.py --cidades "Araçatuba,Bauru,..." --limite 20
  python captacao.py --demo                               # prova offline (sem key)

Sem GOOGLE_PLACES_API_KEY o modo real não roda (avisa e sai) — dependência sua.
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

_AQUI = Path(__file__).resolve().parent
sys.path.insert(0, str(_AQUI))

import coleta
import enriquecimento
import saida
import scoring


def _enriquecer_paralelo(leads: list[dict], fetch=None) -> list[dict]:
    """Enriquecimento (fetch de site é o gargalo) em PARALELO — throughput pro grid
    (1000 leads sequencial = horas; paralelo = minutos). ThreadPool, I/O-bound."""
    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=int(os.environ.get("LEADS_WORKERS", "12"))) as ex:
        enriquecidos = list(ex.map(lambda l: enriquecimento.enriquecer(l, fetch=fetch), leads))
    return [scoring.pontuar(l) for l in enriquecidos]


def rodar(cidades: list[str], categorias=coleta.CATEGORIAS_PADRAO, *, api_key: str = "",
          limite: int = 20, get=None, fetch=None, bairros: list[str] | None = None) -> dict:
    """Pipeline em GRID (cidade × bairro × categoria) → volume, com dedup por place_id
    entre células, enriquecimento paralelo e HARD-CAP de captação (MAX_LEADS_DIA)."""
    max_dia = int(os.environ.get("MAX_LEADS_DIA", "0"))  # 0 = sem teto
    celulas = [(c, b) for c in cidades for b in (bairros or [""])]
    vistos: set[str] = set()  # dedup cross-célula (place_id) → conta lead NOVO, não repetido
    todos, por_cidade, novos = [], {}, 0
    for cidade, bairro in celulas:
        if max_dia and len(vistos) >= max_dia:
            break  # hard-cap: para de gastar Places ao bater o teto do dia
        leads = coleta.coletar(cidade, categorias, api_key=api_key, limite=limite,
                               get=get, bairro=bairro)
        leads = [l for l in leads if l["place_id"] not in vistos]  # cross-célula dedup
        for l in leads:
            vistos.add(l["place_id"])
        leads = _enriquecer_paralelo(leads, fetch)
        res = saida.gravar(leads)
        novos += res.get("novos", len(leads))
        todos.extend(leads)
        chave = f"{cidade}/{bairro}" if bairro else cidade
        por_cidade[chave] = _resumo(leads)
    return {"total": len(todos), "novos": novos, "celulas": len(por_cidade),
            "por_cidade": por_cidade,
            "na_fila": sum(1 for l in todos if l["passa_corte"]), "leads": todos}


def _resumo(leads: list[dict]) -> dict:
    tiers: dict[str, int] = {}
    for l in leads:
        tiers[l["tier_sugerido"]] = tiers.get(l["tier_sugerido"], 0) + 1
    return {"n": len(leads), "na_fila": sum(1 for l in leads if l["passa_corte"]),
            "tiers": dict(sorted(tiers.items()))}


# -- modo demo: prova a cadeia inteira offline (sem key, sem rede) --------------
def _demo_leads(cidade: str, n: int = 20) -> tuple[list, dict, dict]:
    """Gera n leads sintéticos variados + fetchers fake (canned HTML por perfil)."""
    perfis = [
        ("sem_site", "", 130, 4.6, False),
        ("wix_abandonado", "http://c{i}.wixsite.com", 95, 4.1, True),
        ("moderno_ok", "https://c{i}.com.br", 210, 4.7, False),
        ("site_quebrado", "http://c{i}.com", 88, 4.4, False),
    ]
    html = {
        "wix_abandonado": '<meta name="generator" content="Wix.com"><footer>© 2019 Clínica</footer>',
        "moderno_ok": ('<meta name="viewport" content="width=device-width">'
                       '<a href="https://wa.me/551499999">zap</a>'
                       '<script src="https://embed.tawk.to/x"></script><footer>© 2025</footer>'),
        "site_quebrado": None,  # simula site fora do ar
    }
    resultados, detalhes = [], {}
    for i in range(n):
        perfil, site_tmpl, rev, rat, _ = perfis[i % len(perfis)]
        pid = f"demo{i}"
        nome = "Rede OdontoLins" if i in (2, 6) else f"Clínica {cidade[:3]}{i}"  # 2 = multi-unidade
        resultados.append({"place_id": pid, "name": nome})
        detalhes[pid] = {"name": nome, "website": site_tmpl.format(i=i) if site_tmpl else "",
                         "rating": rat, "user_ratings_total": rev, "perfil": perfil,
                         "reviews": [{"text": "demora demais no atendimento", "time": 9e12}] if perfil == "wix_abandonado" else []}

    def fake_get(url, params):
        if "textsearch" in url:
            return {"results": resultados}
        d = detalhes[params["place_id"]]
        return {"result": {**d, "time": 9e12, "reviews": d.get("reviews", [])}}

    def fake_fetch(url):
        perfil = next((d["perfil"] for d in detalhes.values()
                       if d["website"] == url), "moderno_ok")
        h = html.get(perfil)
        return (None, "", url) if h is None else (200, h, url)
    return fake_get, fake_fetch, detalhes


def _demo() -> int:
    import tempfile
    print("=== MODO DEMO — 20 leads sintéticos por cidade (sem key/rede) ===")
    with tempfile.TemporaryDirectory() as td:
        os.environ["LEADS_DB"] = str(Path(td) / "demo.db")
        os.environ.pop("LEADS_PG_DSN", None)
        for cidade in ("Araçatuba", "Bauru"):
            get, fetch, _ = _demo_leads(cidade, 20)
            res = rodar([cidade], ["clínica médica"], api_key="demo", limite=20,
                        get=get, fetch=fetch)
            r = res["por_cidade"][cidade]
            print(f"\n{cidade}: {r['n']} leads · {r['na_fila']} na fila · tiers {r['tiers']}")
            for l in sorted(res["leads"], key=lambda x: -x["score_final"])[:4]:
                fila = "✓FILA" if l["passa_corte"] else "  ―  "
                print(f"  [{fila}] {l['tier_sugerido']} score={l['score_final']:>5} "
                      f"{l['nome']:<16} — {l['motivo_da_dor']}")
        csvp = saida.exportar_csv(res["leads"], str(Path(td) / "amostra.csv"))
        print(f"\nCSV de amostra: {Path(csvp).read_text().count(chr(10))} linhas geradas")
    return 0


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description="Motor de captação de leads (Noemi)")
    ap.add_argument("--cidades", default="", help="lista separada por vírgula")
    ap.add_argument("--bairros", default="", help="grid: bairros por vírgula (célula = bairro×categoria)")
    ap.add_argument("--limite", type=int, default=20)
    ap.add_argument("--grid", action="store_true", help="usa categorias granulares (volume)")
    ap.add_argument("--demo", action="store_true", help="prova offline sem key")
    args = ap.parse_args(argv)
    if args.demo:
        return _demo()
    api_key = os.environ.get("GOOGLE_PLACES_API_KEY", "").strip()
    if not api_key:
        print("FALTA GOOGLE_PLACES_API_KEY — ative a Places API no Google Cloud Console "
              "e exporte a chave. O modo real não roda sem ela. (rode --demo pra ver a cadeia)")
        return 2
    cidades = [c.strip() for c in args.cidades.split(",") if c.strip()]
    if not cidades:
        print("passe --cidades \"Lins\" (piloto) ou a lista completa")
        return 2
    bairros = [b.strip() for b in args.bairros.split(",") if b.strip()] or None
    cats = coleta.CATEGORIAS_GRID if args.grid else coleta.CATEGORIAS_PADRAO
    res = rodar(cidades, cats, api_key=api_key, limite=args.limite, bairros=bairros)
    saida.sincronizar_sheet(res["leads"])
    csvp = saida.exportar_csv(res["leads"], f"data/leads_{'_'.join(cidades)[:40]}.csv")
    print(f"OK — {res['total']} leads ({res.get('novos', '?')} NOVOS) em {res.get('celulas', 1)} "
          f"células, {res['na_fila']} na fila. CSV: {csvp}")
    for cidade, r in res["por_cidade"].items():
        print(f"  {cidade}: {r['n']} leads · {r['na_fila']} fila · tiers {r['tiers']}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
