"""Relatório periódico do T1 — o interruptor que faltava.

O contrato do T1 vende "relatório periódico". O motor existia inteiro e nada o
chamava: em 14/08/2026 a tabela `insights_cliente` tinha 0 linhas e não havia timer.
Código presente no repo não é entrega; entrega é execução agendada gravando linha.

Não duplica nada. Só liga as pontas que já estavam prontas:
    beacon.analise(site)  ->  insights_cliente  ->  /insights/{cliente} (render_cards)

Honestidade do dado: `beacon.analise` já segura abaixo de 20 visitas ("acumulando").
Este módulo NUNCA grava nada nesse caso — cliente sem tráfego vê a tela de "ainda
observando", que é verdade, em vez de um achado inventado pra parecer entrega.
"""
from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

_AQUI = Path(__file__).resolve().parent
sys.path.insert(0, str(_AQUI))
sys.path.insert(0, str(_AQUI.parents[1] / "packages"))

MIN_VISITAS = 20  # mesmo piso do beacon.analise; explícito aqui pra não virar mágica


def sites_com_trafego() -> list[str]:
    """Sites que já mandaram evento. Fonte da verdade é o próprio tráfego."""
    from shared_core.storage import db
    with db.conn() as c:
        c.execute("CREATE TABLE IF NOT EXISTS site_trafego (id INTEGER PRIMARY KEY AUTOINCREMENT, "
                  "ts TEXT, site TEXT, evento TEXT, origem TEXT, path TEXT)")
        return [r[0] for r in c.execute(
            "SELECT site FROM site_trafego GROUP BY site ORDER BY COUNT(*) DESC") if r[0]]


def sites_do_relatorio() -> list[str]:
    """Quem entra no relatório: quem tem tráfego MAIS quem foi provisionado.

    Só tráfego não bastava: um T1 recém-instalado tem 0 evento e sumiria da saída
    justamente na semana em que o JP precisa saber se ele já virou indicação."""
    from shared_core.storage import db
    vistos = list(sites_com_trafego())
    tem = set(vistos)
    with db.conn() as c:
        c.execute("CREATE TABLE IF NOT EXISTS sites_gerados (id INTEGER PRIMARY KEY "
                  "AUTOINCREMENT, cliente TEXT NOT NULL, segmento TEXT, slug TEXT NOT NULL, "
                  "url TEXT NOT NULL, criado_em TEXT NOT NULL, prospect_id INTEGER)")
        for (slug,) in c.execute("SELECT DISTINCT slug FROM sites_gerados "
                                 "WHERE slug IS NOT NULL ORDER BY slug"):
            if slug and slug not in tem:
                tem.add(slug)
                vistos.append(slug)
    return vistos


def rodar(site: str) -> dict:
    """Analisa o tráfego de 1 site e grava os achados NOVOS em insights_cliente."""
    import beacon
    import captacao
    import insight_engine
    from shared_core.storage import db

    origem = captacao.de_cliente(site)  # nunca levanta: site sem tag => "desconhecida"
    r = beacon.analise(site, minimo=MIN_VISITAS)
    achados = r.get("achados") or []
    if r.get("status") != "ok" or not achados:
        fora = {"site": site, "origem": origem, "status": r.get("status", "sem-achado"),
                "visitas": r.get("visitas", 0), "novos": 0}
        if r.get("motivo"):  # diz POR QUE não houve entrega, em vez de sumir calado
            fora["motivo"] = r["motivo"]
        return fora

    ts = datetime.now(timezone.utc).isoformat()
    novos = 0
    with db.conn() as c:
        insight_engine._tabela(c)
        for a in achados:
            ins = str(a.get("achado") or a.get("insight") or "").strip()[:500]
            acao = str(a.get("acao", "")).strip()[:300]
            if not ins or not acao:
                continue
            # mesmo achado não vira linha nova a cada rodada
            ja = c.execute("SELECT 1 FROM insights_cliente WHERE cliente=? AND insight=? LIMIT 1",
                           (site, ins)).fetchone()
            if ja:
                continue
            tipo = "risco" if str(a.get("tipo", "")).strip().lower() == "risco" else "oportunidade"
            c.execute("INSERT INTO insights_cliente (cliente,ts,tipo,insight,acao,score,vertical,origem_ref) "
                      "VALUES (?,?,?,?,?,?,?,?)", (site, ts, tipo, ins, acao, 0, "", "beacon"))
            novos += 1
        c.commit()
    return {"site": site, "origem": origem, "status": "ok", "visitas": r.get("visitas", 0),
            "cliques_cta": r.get("cliques_cta", 0), "novos": novos}


def rodar_todos() -> list[dict]:
    return [rodar(s) for s in sites_do_relatorio()]


if __name__ == "__main__":
    import os

    if os.environ.get("RELATORIO_T1_SELFTEST"):  # self-check: DB temp, LLM mockado, sem rede
        import json
        import tempfile
        os.environ["NOEMI_DATA_DIR"] = tempfile.mkdtemp(suffix="_rel_t1")
        import beacon
        import insight_engine
        from shared_core.ai import llm_proxy
        from shared_core.storage import db

        # 1) sem tráfego suficiente => NÃO grava (não inventa entrega)
        for _ in range(5):
            beacon.registrar("cliente_x", "view", "", "/")
        llm_proxy.completar = lambda *a, **k: json.dumps({"achados": [
            {"tipo": "risco", "achado": "nunca deveria aparecer", "acao": "x"}]})
        r = rodar("cliente_x")
        assert r["status"] == "acumulando" and r["novos"] == 0, r
        assert insight_engine.listar_insights("cliente_x") == [], "gravou sem tráfego"

        # 2) com tráfego acima do piso => grava e o cliente enxerga
        for i in range(20):
            beacon.registrar("cliente_x", "view", "https://instagram.com", "/")
        beacon.registrar("cliente_x", "cta", "", "/")
        llm_proxy.completar = lambda *a, **k: json.dumps({"achados": [
            {"tipo": "risco", "achado": "quase ninguém do Instagram clica no WhatsApp",
             "acao": "trocar a primeira frase da página pra falar com quem vem do Instagram"}]})
        r = rodar("cliente_x")
        assert r["status"] == "ok" and r["novos"] == 1, r
        itens = insight_engine.listar_insights("cliente_x")
        assert len(itens) == 1 and itens[0]["tipo"] == "risco", itens
        html = insight_engine.render_cards("cliente_x")
        assert "Instagram" in html and "primeira frase" in html, "não chegou na tela do cliente"

        # 3) rodar de novo NÃO duplica o mesmo achado
        assert rodar("cliente_x")["novos"] == 0, "duplicou"
        assert len(insight_engine.listar_insights("cliente_x")) == 1

        # 4) proveniência gravada (dá pra auditar de onde veio o achado)
        with db.conn() as c:
            assert c.execute("SELECT origem_ref FROM insights_cliente").fetchone()[0] == "beacon"

        # 5) a varredura enxerga o site
        assert "cliente_x" in sites_com_trafego()

        # 6) RETROCOMPAT: cliente sem a tag roda igual e reporta "desconhecida", nunca erro
        import captacao
        assert rodar("cliente_x")["origem"] == captacao.PADRAO, "site sem tag deveria ser desconhecida"

        # 7) cliente PROVISIONADO e marcado aparece no relatório mesmo com ZERO tráfego
        with db.conn() as c:
            c.execute("CREATE TABLE IF NOT EXISTS sites_gerados (id INTEGER PRIMARY KEY "
                      "AUTOINCREMENT, cliente TEXT NOT NULL, segmento TEXT, slug TEXT NOT NULL, "
                      "url TEXT NOT NULL, criado_em TEXT NOT NULL, prospect_id INTEGER)")
            c.execute("INSERT INTO sites_gerados (cliente,segmento,slug,url,criado_em) VALUES "
                      "('Auto Center do Lins','oficina','auto-center-lins','http://x','2026-08-15')")
            c.commit()
        assert captacao.marcar("auto-center-lins", "indicacao_pessoal")["ok"] is True
        assert "auto-center-lins" in sites_do_relatorio(), "T1 recém-instalado sumiu do relatório"
        r = rodar("auto-center-lins")
        assert r["origem"] == "indicacao_pessoal" and r["visitas"] == 0, r
        assert r["status"] == "acumulando" and r["novos"] == 0, r

        # 8) os dois convivem na MESMA saída — é isso que torna a taxa por via calculável
        saida = {x["site"]: x["origem"] for x in rodar_todos()}
        assert saida["auto-center-lins"] == "indicacao_pessoal", saida
        assert saida["cliente_x"] == captacao.PADRAO, saida

        print("relatorio_t1 OK — piso de 20 visitas, grava, chega no render, não duplica, "
              "proveniência=beacon; origem exposta com e sem tag, T1 sem tráfego aparece")
    else:
        for x in rodar_todos():
            print(x)
