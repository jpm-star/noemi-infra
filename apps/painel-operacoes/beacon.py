"""Beacon de tracking do site (Item 5 — pré-req da aba "Site" por cliente).

Registra pageview + clique no CTA num banco ISOLADO (noemi.db, tabela site_trafego).
Sem cookie, sem PII — só evento + origem (referrer) + path + site. Alimenta a aba
"Site" (que depois formata isso por IA, padrão Insight Engine, não dado bruto solto).

Duas travas de honestidade, escritas depois de a análise mentir em produção
(14/08/2026), quando o snippet estava quebrado e a IA leu o bug como se fosse o
negócio do cliente:

  1. Zero clique NUNCA é conversão 0%. Se o site nunca registrou um único `cta`,
     não dá pra saber se ninguém clica ou se ninguém está medindo — `conversao_pct`
     vem None e a análise é proibida de concluir qualquer coisa sobre conversão.
  2. Referrer do próprio domínio é navegação interna, não "tráfego vindo de".
     O snippet marca como "interno" e a análise não trata isso como origem externa.
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


# Domínio de cada site. O snippet novo já marca navegação interna na origem, mas o
# histórico gravado antes disso não tem essa marca — e a análise lê o histórico inteiro.
# Sem isto, a IA sugere "fazer parceria com chinelospedi.com" pro dono do chinelospedi.
_HOSTS = {
    "jpos": ("jpos.com.br", "www.jpos.com.br"),
    "landing": ("landing.jpos.com.br",),
    "pedi": ("chinelospedi.com", "www.chinelospedi.com"),
}


def _origem_curta(ref: str, site: str = "") -> str:
    """Referrer → origem legível (google / instagram / direto / interno / domínio)."""
    r = (ref or "").lower()
    if not r:
        return "direto"
    if r == "interno":  # o snippet já resolveu: referrer do mesmo host
        return "interno"
    from urllib.parse import urlparse as _up
    try:
        if _up(r).netloc in _HOSTS.get(site, ()):  # o próprio site do cliente
            return "interno"
    except ValueError:
        pass
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

    `cta_rastreado` é a diferença entre "ninguém clicou" e "ninguém mediu": False
    enquanto o site nunca registrou um único `cta`. Nesse caso `conversao_pct` é None
    (desconhecida), nunca 0.0 — porque 0.0 é uma afirmação sobre o negócio do cliente
    que o dado não sustenta."""
    from shared_core.storage import db
    vazio = {"visitas": 0, "cliques_cta": 0, "conversao_pct": None, "cta_rastreado": False,
             "origens": {}, "externas": 0}
    try:
        with db.conn() as c:
            _tabela(c)
            views = c.execute("SELECT COUNT(*) FROM site_trafego WHERE site=? AND evento='view'", (site,)).fetchone()[0]
            cta = c.execute("SELECT COUNT(*) FROM site_trafego WHERE site=? AND evento='cta'", (site,)).fetchone()[0]
            origens: dict[str, int] = {}
            for r in c.execute("SELECT origem FROM site_trafego WHERE site=? AND evento='view'", (site,)):
                o = _origem_curta(r[0], site)
                origens[o] = origens.get(o, 0) + 1
    except Exception:  # noqa: BLE001
        return vazio
    top = dict(sorted(origens.items(), key=lambda x: x[1], reverse=True)[:6])
    externas = sum(v for k, v in origens.items() if k not in ("interno", "direto"))
    return {"visitas": views, "cliques_cta": cta, "cta_rastreado": cta > 0,
            "conversao_pct": round(cta / views * 100, 1) if (views and cta) else None,
            "origens": top, "externas": externas}


# Mesma disciplina do insight_engine: achado com implicação de ação de nível-dono.
# Sem isso a análise devolve "revisar a copy pra melhorar a conversão", que é ruído.
_REGRAS = (
    "Você analisa o tráfego do site de um negócio local. Regras DURAS:\n"
    "1. Um achado é um PADRÃO com implicação de ação — nunca volume bruto nem resumo do dado.\n"
    "2. PROIBIDA platitude: 'revisar a copy', 'melhorar a conversão', 'otimizar o funil', "
    "'criar estratégia', 'fazer newsletter'. Se o achado serviria pra qualquer site do mundo, "
    "descarta.\n"
    "3. A ação é de NÍVEL DONO: algo que ele faz hoje com as próprias mãos, sem contratar nem "
    "instalar nada (responder, ligar, mudar horário, avisar, publicar tal coisa). Nunca ação "
    "técnica.\n"
    "4. 'interno' é navegação dentro do próprio site, NÃO tráfego vindo de terceiro — nunca "
    "sugira parceria com o próprio domínio do cliente.\n"
    "5. Se o dado não sustenta um padrão, devolve lista VAZIA. Menos é melhor que inventado.\n"
    "Máximo 2 achados. SOMENTE JSON "
    '{"achados":[{"tipo":"oportunidade|risco","achado":"","acao":""}]}.'
)


# Piso de sinal EXTERNO. Visita interna e visita direta não sustentam achado sobre
# origem: "veio direto" quase sempre quer dizer "o referrer não veio", não uma escolha
# do visitante. Sem este piso o motor foi obrigado a falar sobre 2 visitas externas e
# devolveu platitude ("avaliar a estratégia de marketing"), que é ruído com cara de
# entrega. Abaixo do piso, a resposta honesta é "ainda não dá pra dizer".
MIN_EXTERNAS = 10


def analise(site: str, minimo: int = 20) -> dict:
    """Interpreta o tráfego (padrão Insight Engine: achado, não dado bruto). Groq-only.
    Abaixo de `minimo` visitas → 'acumulando' (não inventa padrão com pouco dado)."""
    r = resumo(site)
    if r["visitas"] < minimo:
        return {**r, "status": "acumulando", "faltam": minimo - r["visitas"], "achados": []}
    if r["externas"] < MIN_EXTERNAS:
        return {**r, "status": "acumulando", "achados": [],
                "faltam_externas": MIN_EXTERNAS - r["externas"],
                "motivo": (f"{r['visitas']} visitas, mas só {r['externas']} vieram de fora do site. "
                           "Origem sem volume externo não sustenta achado.")}
    from shared_core.ai import llm_proxy
    ctx = f"visitas={r['visitas']} · origens={r['origens']}"
    if r["cta_rastreado"]:
        ctx += f" · cliques no CTA={r['cliques_cta']} · conversão={r['conversao_pct']}%"
    else:
        ctx += ("\nATENÇÃO: o clique no CTA ainda NÃO tem histórico neste site (a medição "
                "acabou de entrar no ar). Conversão é DESCONHECIDA, não zero. É PROIBIDO "
                "afirmar ou insinuar que o CTA converte pouco, que falta clique, ou "
                "qualquer coisa sobre conversão. Analise só origem e volume.")
    txt = llm_proxy.completar(f"{_REGRAS}\n\nDADOS:\n{ctx}", model="analise", max_tokens=400,
                              temperature=0.3, permitir_anthropic=False)
    import json
    import re as _re
    m = _re.search(r"\{.*\}", txt or "", _re.S)
    try:
        ach = json.loads(m.group(0)).get("achados", [])[:2] if m else []
    except (ValueError, TypeError):
        ach = []
    if not r["cta_rastreado"]:  # cinto e suspensório: o LLM às vezes ignora a instrução
        ach = [a for a in ach if not _fala_de_conversao(a)]
    return {**r, "status": "ok", "achados": ach}


_PROIBIDAS = ("convers", "cta", "clique", "clicar", "taxa de")


def _fala_de_conversao(achado: dict) -> bool:
    t = f"{achado.get('achado', '')} {achado.get('acao', '')}".lower()
    return any(p in t for p in _PROIBIDAS)


if __name__ == "__main__":  # self-check ISOLADO (banco temp)
    import os
    import tempfile
    os.environ["NOEMI_DATA_DIR"] = tempfile.mkdtemp(suffix="_beacon_selftest")
    assert registrar("jpos", "view", "https://www.google.com/search", "/")
    assert registrar("jpos", "view", "", "/")           # direto
    assert registrar("jpos", "view", "interno", "/sobre")  # navegação dentro do site
    assert registrar("jpos", "xxx") is False            # evento inválido não grava

    # 1) sem NENHUM cta: conversão é desconhecida, NUNCA 0.0
    r = resumo("jpos")
    assert r["visitas"] == 3 and r["cliques_cta"] == 0, r
    assert r["conversao_pct"] is None and r["cta_rastreado"] is False, r
    assert r["origens"].get("google") == 1 and r["origens"].get("direto") == 1, r["origens"]
    assert r["origens"].get("interno") == 1, "referrer do próprio site virou origem externa"
    assert r["externas"] == 1, r  # só o google conta como externa

    # histórico gravado ANTES do snippet marcar "interno" também tem que ser interno
    assert _origem_curta("https://chinelospedi.com/homem", "pedi") == "interno"
    assert _origem_curta("https://chinelospedi.com/homem", "jpos") == "chinelospedi.com"
    assert _origem_curta("https://jpos.com.br/", "jpos") == "interno"

    # 2) com cta: aí sim vira percentual
    assert registrar("jpos", "cta", "https://instagram.com", "/")
    r = resumo("jpos")
    assert r["cta_rastreado"] is True and r["conversao_pct"] == round(1 / 3 * 100, 1), r

    # 3) a trava: sem histórico de cta, achado que fala de conversão é DESCARTADO
    assert _fala_de_conversao({"achado": "Falta de cliques no CTA", "acao": "revisar"}) is True
    assert _fala_de_conversao({"achado": "muita visita do Instagram",
                               "acao": "responder direct no mesmo dia"}) is False
    from shared_core.ai import llm_proxy
    llm_proxy.completar = lambda *a, **k: (
        '{"achados":[{"tipo":"risco","achado":"Falta de cliques no CTA e conversões",'
        '"acao":"revisar a copy"},{"tipo":"oportunidade","achado":"metade vem do Instagram",'
        '"acao":"responder os direct no mesmo dia"}]}')
    for i in range(25):
        registrar("semcta", "view", "https://instagram.com", "/")
    a = analise("semcta")
    assert a["status"] == "ok", a
    assert len(a["achados"]) == 1 and "Instagram" in a["achados"][0]["achado"], a["achados"]

    # 3b) volume alto MAS sem sinal externo => não chama o LLM, não inventa achado
    def _explode(*a, **k):
        raise AssertionError("chamou o LLM sem sinal externo suficiente")
    llm_proxy.completar = _explode
    for i in range(30):
        registrar("sofechado", "view", "interno", "/x")
    b = analise("sofechado")
    assert b["status"] == "acumulando" and b["achados"] == [], b
    assert b["faltam_externas"] == MIN_EXTERNAS and "não sustenta" in b["motivo"], b

    # 4) pouco dado continua acumulando
    registrar("novo", "view", "", "/")
    assert analise("novo")["status"] == "acumulando"

    print("beacon OK — grava view/cta, piso de sinal externo, ignora inválido, 'interno' não é origem externa, "
          "conversão é None sem histórico de cta, achado sobre conversão descartado nesse caso")
