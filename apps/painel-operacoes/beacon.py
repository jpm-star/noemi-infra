"""Beacon de tracking do site (Item 5 — pré-req da aba "Site" por cliente).

Registra pageview + clique no CTA num banco ISOLADO (noemi.db, tabela site_trafego).
Sem cookie, sem PII — só evento + origem (referrer) + path + site. Alimenta a aba
"Site" (que depois formata isso por IA, padrão Insight Engine, não dado bruto solto).
"""
from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "packages"))  # repo/packages

_EVENTOS = {"view", "cta"}  # só o que a gente mede de verdade (nada inventado)


def _tabela(c) -> None:
    c.execute("CREATE TABLE IF NOT EXISTS site_trafego (id INTEGER PRIMARY KEY AUTOINCREMENT, "
              "ts TEXT, site TEXT, evento TEXT, origem TEXT, path TEXT)")


def registrar(site: str, evento: str, origem: str = "", path: str = "") -> bool:
    """Grava 1 evento. Best-effort: evento inválido/erro → False, nunca crasha o request."""
    ev = (evento or "").strip().lower()
    if ev not in _EVENTOS:
        return False
    try:
        from shared_core.storage import db
        with db.conn() as c:
            _tabela(c)
            c.execute("INSERT INTO site_trafego (ts,site,evento,origem,path) VALUES (?,?,?,?,?)",
                      (datetime.now(timezone.utc).isoformat(), (site or "?")[:60], ev,
                       (origem or "")[:200], (path or "")[:200]))
            c.commit()
        return True
    except Exception:  # noqa: BLE001 — tracking nunca derruba o site
        return False


def _origem_curta(ref: str) -> str:
    """Referrer → origem legível (google / instagram / direto / domínio)."""
    r = (ref or "").lower()
    if not r:
        return "direto"
    for k in ("google", "instagram", "facebook", "whatsapp", "bing", "youtube", "tiktok", "linkedin"):
        if k in r:
            return k
    from urllib.parse import urlparse
    try:
        return urlparse(ref).netloc or "outro"
    except ValueError:
        return "outro"


def resumo(site: str) -> dict:
    """Dado BRUTO simples pra aba Site: visitas, cliques no CTA, conversão, top origens.
    (A camada de IA que interpreta isso vem depois — aqui é o dado honesto.)"""
    from shared_core.storage import db
    try:
        with db.conn() as c:
            _tabela(c)
            views = c.execute("SELECT COUNT(*) FROM site_trafego WHERE site=? AND evento='view'", (site,)).fetchone()[0]
            cta = c.execute("SELECT COUNT(*) FROM site_trafego WHERE site=? AND evento='cta'", (site,)).fetchone()[0]
            origens: dict[str, int] = {}
            for r in c.execute("SELECT origem FROM site_trafego WHERE site=? AND evento='view'", (site,)):
                o = _origem_curta(r[0])
                origens[o] = origens.get(o, 0) + 1
    except Exception:  # noqa: BLE001
        return {"visitas": 0, "cliques_cta": 0, "conversao_pct": 0.0, "origens": {}}
    top = dict(sorted(origens.items(), key=lambda x: x[1], reverse=True)[:6])
    return {"visitas": views, "cliques_cta": cta,
            "conversao_pct": round(cta / views * 100, 1) if views else 0.0, "origens": top}


def analise(site: str, minimo: int = 20) -> dict:
    """Interpreta o tráfego (padrão Insight Engine: achado, não dado bruto). Groq-only.
    Abaixo de `minimo` visitas → 'acumulando' (não inventa padrão com pouco dado)."""
    r = resumo(site)
    if r["visitas"] < minimo:
        return {**r, "status": "acumulando", "faltam": minimo - r["visitas"], "achados": []}
    from shared_core.ai import llm_proxy
    ctx = (f"visitas={r['visitas']} · cliques no CTA={r['cliques_cta']} · conversão={r['conversao_pct']}% · "
           f"origens={r['origens']}")
    prompt = ("Você analisa o tráfego de uma landing. Dado o resumo, dê no MÁXIMO 2 achados REAIS "
              "(padrão + ação nível-dono), oportunidade ou risco. Ex: conversão baixa vinda do Instagram → "
              "revisar a copy pra esse público. Sem platitude. "
              'SOMENTE JSON {"achados":[{"tipo":"oportunidade|risco","achado":"","acao":""}]}.\n\n' + ctx)
    txt = llm_proxy.completar(prompt, model="analise", max_tokens=400, temperature=0.3, permitir_anthropic=False)
    import json
    import re as _re
    m = _re.search(r"\{.*\}", txt or "", _re.S)
    try:
        ach = json.loads(m.group(0)).get("achados", [])[:2] if m else []
    except (ValueError, TypeError):
        ach = []
    return {**r, "status": "ok", "achados": ach}


if __name__ == "__main__":  # self-check ISOLADO (banco temp)
    import os
    os.environ["NOEMI_DATA_DIR"] = "/root/.claude/jobs/f7137c43/tmp/beacon_selftest"
    import shutil
    shutil.rmtree(os.environ["NOEMI_DATA_DIR"], ignore_errors=True)
    assert registrar("jpos", "view", "https://www.google.com/search", "/")
    assert registrar("jpos", "view", "", "/")  # direto
    assert registrar("jpos", "cta", "https://instagram.com", "/")
    assert registrar("jpos", "xxx") is False  # evento inválido não grava
    r = resumo("jpos")
    assert r["visitas"] == 2 and r["cliques_cta"] == 1 and r["conversao_pct"] == 50.0, r
    assert r["origens"].get("google") == 1 and r["origens"].get("direto") == 1, r["origens"]
    print("beacon OK — grava view/cta, ignora inválido, resumo (visitas/cta/conversão/origens), banco isolado")
