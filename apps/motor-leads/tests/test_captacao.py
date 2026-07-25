"""Testes do motor de captação — as 4 camadas + orquestração (tudo offline)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import coleta
import enriquecimento
import saida
import scoring


def test_scoring_tiers():
    assert scoring.pontuar({"total_reviews": 120, "rating": 4.6, "sem_site": True,
                            "atividade_recente": True})["tier_sugerido"] == "T2"
    assert scoring.pontuar({"n_unidades": 3, "total_reviews": 200, "rating": 4.5,
                            "tem_wa_button": True, "tem_chat": True})["tier_sugerido"] == "T4"


def test_corte_de_fila():
    # movimento baixo (reviews<80, sem atividade recente) NÃO entra na fila
    assert not scoring.pontuar({"total_reviews": 10, "rating": 4.9, "sem_site": True})["passa_corte"]
    # site bom sem dor também não entra
    assert not scoring.pontuar({"total_reviews": 200, "rating": 4.8, "site_de_agencia": True,
                                "tem_wa_button": True, "tem_chat": True,
                                "atividade_recente": True})["passa_corte"]


def test_enriquecimento_regex():
    a = enriquecimento.analisar_html(
        '<meta name="generator" content="Wix.com"><footer>© 2019 X</footer>', "http://x.com")
    assert a["site_abandonado"] and a["ano_rodape"] == 2019 and not a["tem_ssl"]
    b = enriquecimento.analisar_html(
        '<meta name="viewport" content="w"><a href="https://wa.me/1">z</a>'
        '<script src="https://embed.tawk.to/x"></script>', "https://y.com")
    assert b["tem_wa_button"] and b["tem_chat"] and b["responsivo"]


def test_coleta_exige_chave():
    import pytest
    with pytest.raises(coleta.FaltaChave):
        coleta.coletar("Lins", api_key="")


def test_pipeline_demo_grava_e_classifica(tmp_path, monkeypatch):
    monkeypatch.setenv("LEADS_DB", str(tmp_path / "t.db"))
    monkeypatch.delenv("LEADS_PG_DSN", raising=False)
    import captacao
    get, fetch, _ = captacao._demo_leads("Lins", 20)
    res = captacao.rodar(["Lins"], ["clínica médica"], api_key="demo", limite=20,
                         get=get, fetch=fetch)
    assert res["total"] == 20 and res["na_fila"] > 0
    assert set(res["por_cidade"]["Lins"]["tiers"]).issubset({"T1", "T2", "T3", "T4"})
    # cidade_origem gravado e status default 'novo'
    conn, _ = saida._conn()
    linhas = conn.execute("SELECT cidade_origem, status FROM leads_clinicas").fetchall()
    conn.close()
    assert linhas and all(l[0] == "Lins" and l[1] == "novo" for l in linhas)
