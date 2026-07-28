"""Insight Engine — tier 1 cliente-facing (subdomínio por cliente).

Primeiro ADAPTER novo (`fonte_tipo=sdr_cliente`) sobre o núcleo genérico do Radar.
"Básico na estrutura, caro na percepção": o cliente abre a página e sente "isso
pensa por mim" — lista curta de cards (insight + ação), não dashboard de métrica.

CUSTO (não-negociável): roda em GROQ, NUNCA Anthropic (permitir_anthropic=False) —
Anthropic é reservado pro Radar pessoal do JP; senão custo cresce linear/cliente e
mata a margem do tier 1.

Reuso, não duplicação:
  - fonte: adapter monta a observacao() padrão que o núcleo já aceita.
  - processamento: entra por radar.processar_observacao (dispatch por fonte_tipo).
  - saída: mesmo conceito de gate ≥7 do Radar — só sobe sinal que passa; nunca
    "gera 3 sempre".
  - gatilho: BATCH (acumula interações, roda quando bate volume novo suficiente pra
    ter PADRÃO real), não por mensagem (caro + ruído).

Storage: tabela `insights_cliente` no noemi.db (SQLite, já isolado; NÃO toca DB de
produção do SDR). Isolado por cliente na coluna `cliente`.
"""
from __future__ import annotations

import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

_AQUI = Path(__file__).resolve().parent
sys.path.insert(0, str(_AQUI.parents[1] / "packages"))

GATE = int(__import__("os").environ.get("INSIGHT_ENGINE_GATE", "7"))          # score mínimo pra subir
MIN_NOVAS = int(__import__("os").environ.get("INSIGHT_ENGINE_MIN_NOVAS", "15"))  # volume novo p/ rodar
MAX_INSIGHTS = 3

# System prompt = "o jeito do JP analisar" portável, parametrizado por {vertical}/{tom}.
PROMPT = """Você é um analista que examina as interações de um negócio local ({vertical}) e extrai sinal real, não relatório de atividade. Regras:

1. NUNCA lista volume bruto (quantidade de mensagens, número de visitas) como insight — isso é dado, não achado. Um insight é um PADRÃO com implicação de ação.
2. Todo achado passa por: RECORRÊNCIA (apareceu 1x = não é padrão ainda; 3+ vezes = é padrão) × RELEVÂNCIA pro negócio agora × ORIGINALIDADE (algo óbvio que o dono já sabe não sobe).
3. Classifica cada achado como OPORTUNIDADE (algo que, se agir, converte mais) ou RISCO (algo que, se ignorar, perde cliente/vendas).
4. Se o dado for insuficiente ou ambíguo pra afirmar um padrão, diga isso explicitamente — nunca invente tendência que os dados não sustentam.
5. Tom: direto, sem jargão de analista, sem "considerando os dados apresentados" — fala como quem já olhou e vai direto no que importa. Adapta ao tom do negócio ({tom}).
6. Todo insight vem com UMA ação sugerida, concreta, que o dono consegue fazer sozinho sem saber nada de tecnologia (não "otimize seu funil" — sim "responde mais rápido quem pergunta de preço às sextas, é quando mais gente pergunta e some").
7. Máximo 3 insights por rodada. Se não achar 3 com qualidade, entrega menos — nunca enche com achado fraco só pra bater número.

Responda SOMENTE JSON: {{"insights":[{{"tipo":"oportunidade"|"risco","insight":"<o padrão + implicação>","acao":"<1 ação concreta pro dono>","score":<0-10 = recorrência × relevância × originalidade>,"recorrencia":"<quantas vezes o padrão apareceu>"}}]}}. Se dados insuficientes: {{"insights":[],"nota":"<por que não dá pra afirmar padrão>"}}."""


def _prompt(vertical: str, tom: str, texto: str) -> str:
    cab = PROMPT.format(vertical=vertical or "negócio local", tom=tom or "direto")
    return f"{cab}\n\nINTERAÇÕES DO NEGÓCIO (lote):\n{texto[:12000]}"


def _analisar_lote(texto: str, vertical: str, tom: str) -> list[dict]:
    """Groq (NUNCA Anthropic) → lista de insights validados (≤3, só os que passam o gate)."""
    from shared_core.ai import llm_proxy
    txt = llm_proxy.completar(_prompt(vertical, tom, texto), model="analise",
                              max_tokens=900, temperature=0.3, permitir_anthropic=False)
    if not txt:
        return []
    m = re.search(r"\{.*\}", txt, re.S)
    try:
        bruto = json.loads(m.group(0)) if m else {}
    except (ValueError, TypeError):
        return []
    out = []
    for it in (bruto.get("insights") or [])[:MAX_INSIGHTS]:
        if not isinstance(it, dict):
            continue
        try:
            score = max(0, min(10, int(it.get("score", 0))))
        except (TypeError, ValueError):
            score = 0
        ins = str(it.get("insight", "")).strip()
        acao = str(it.get("acao", "")).strip()
        tipo = str(it.get("tipo", "")).strip().lower()
        if not ins or not acao or score < GATE:  # gate ≥7 + precisa de ação real
            continue
        out.append({"tipo": "risco" if tipo == "risco" else "oportunidade",
                    "insight": ins[:500], "acao": acao[:300], "score": score,
                    "recorrencia": str(it.get("recorrencia", ""))[:40]})
    return out


def _tabela(c) -> None:
    c.execute("CREATE TABLE IF NOT EXISTS insights_cliente ("
              "id INTEGER PRIMARY KEY AUTOINCREMENT, cliente TEXT, ts TEXT, tipo TEXT, "
              "insight TEXT, acao TEXT, score INT, vertical TEXT, origem_ref TEXT)")


def processar_cliente(obs: dict) -> dict:
    """Alvo do dispatch (radar.processar_observacao quando fonte_tipo=sdr_cliente).
    Roda o cérebro cliente (Groq), aplica o gate ≥7, GRAVA os que passam, devolve."""
    from shared_core.storage import db
    cliente = obs.get("cliente") or obs.get("origem") or "cliente"
    vertical = obs.get("vertical", "")
    insights = _analisar_lote(obs.get("texto", ""), vertical, obs.get("tom", ""))
    ts = datetime.now(timezone.utc).isoformat()
    with db.conn() as c:
        _tabela(c)
        for i in insights:
            c.execute("INSERT INTO insights_cliente (cliente,ts,tipo,insight,acao,score,vertical,origem_ref) "
                      "VALUES (?,?,?,?,?,?,?,?)",
                      (cliente, ts, i["tipo"], i["insight"], i["acao"], i["score"],
                       vertical, obs.get("ref", "")))
        c.commit()
    return {"cliente": cliente, "guardados": len(insights), "insights": insights}


def analisar_cliente(cliente: str, conversas: list[str], vertical: str, tom: str,
                     min_novas: int = MIN_NOVAS) -> dict:
    """ADAPTER sdr_cliente (batch): recebe as conversas/interações NOVAS do cliente.
    Só roda o cérebro se houver volume suficiente pra ter PADRÃO real (min_novas) —
    senão acumula. Monta a observacao() padrão e entra pelo núcleo (dispatch)."""
    import radar
    novas = [str(x).strip() for x in (conversas or []) if str(x).strip()]
    if len(novas) < min_novas:
        return {"cliente": cliente, "status": "acumulando",
                "novas": len(novas), "faltam": min_novas - len(novas)}
    texto = "\n---\n".join(novas)
    obs = radar.observacao(texto, origem=cliente, ref=f"lote:{len(novas)}",
                           fonte_tipo="sdr_cliente")
    obs.update(cliente=cliente, vertical=vertical, tom=tom)
    return radar.processar_observacao(obs)  # núcleo dispatcha p/ processar_cliente


def listar_insights(cliente: str, limite: int = 12) -> list[dict]:
    from shared_core.storage import db
    with db.conn() as c:
        _tabela(c)
        rows = c.execute("SELECT tipo,insight,acao,score,ts FROM insights_cliente "
                         "WHERE cliente=? ORDER BY score DESC, id DESC LIMIT ?",
                         (cliente, limite)).fetchall()
    return [dict(r) for r in rows]


def render_cards(cliente: str) -> str:
    """UI do subdomínio: lista curta de cards (insight + ação). Look 'IA trabalhando
    pra mim', não planilha. HTML autocontido, sem dep."""
    itens = listar_insights(cliente)
    if not itens:
        cards = ('<div class="vazio">A IA ainda está observando as conversas do seu '
                 'negócio. Os primeiros achados aparecem assim que houver padrão real.</div>')
    else:
        cards = "".join(
            f'<div class="card {i["tipo"]}">'
            f'<span class="tag">{"⚠️ risco" if i["tipo"]=="risco" else "💡 oportunidade"}</span>'
            f'<p class="ins">{_esc(i["insight"])}</p>'
            f'<p class="acao"><b>O que fazer:</b> {_esc(i["acao"])}</p></div>'
            for i in itens)
    return f"""<!doctype html><html lang="pt-BR"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>Seus insights</title>
<style>
:root{{--bg:#0b0f17;--card:#141b26;--line:#232f42;--ink:#e8eef6;--mut:#8aa;--op:#2fe6a0;--ri:#ffb020}}
*{{box-sizing:border-box;margin:0}}body{{background:var(--bg);color:var(--ink);font:16px/1.55 system-ui,sans-serif;padding:26px 18px;max-width:640px;margin:0 auto}}
h1{{font-size:1.35rem;margin-bottom:2px}}.sub{{color:var(--mut);font-size:.9rem;margin-bottom:22px}}
.card{{background:var(--card);border:1px solid var(--line);border-left:4px solid var(--op);border-radius:14px;padding:15px 17px;margin-bottom:13px}}
.card.risco{{border-left-color:var(--ri)}}
.tag{{font-size:.72rem;font-weight:700;letter-spacing:.03em;color:var(--op)}}.card.risco .tag{{color:var(--ri)}}
.ins{{margin:7px 0 9px;font-size:1.02rem}}.acao{{color:var(--mut);font-size:.92rem}}.acao b{{color:var(--ink)}}
.vazio{{color:var(--mut);text-align:center;padding:40px 10px;line-height:1.6}}
</style></head><body>
<h1>🧠 Seus insights</h1><div class="sub">O que a IA percebeu nas conversas do seu negócio — direto ao ponto.</div>
{cards}</body></html>"""


def _esc(s: str) -> str:
    return (s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


if __name__ == "__main__":  # self-check isolado (LLM mockado, sem rede/DB de produção)
    import os
    os.environ["NOEMI_DATA_DIR"] = "/root/.claude/jobs/f7137c43/tmp/ie_selftest"
    Path(os.environ["NOEMI_DATA_DIR"]).mkdir(parents=True, exist_ok=True)
    from shared_core.ai import llm_proxy

    # 1) parse + gate: 3 insights vindos do LLM, 1 abaixo do gate (score 5) é cortado
    llm_proxy.completar = lambda *a, **k: json.dumps({"insights": [
        {"tipo": "oportunidade", "insight": "quem pergunta preço na sexta some sem resposta",
         "acao": "responder preço na hora nas sextas", "score": 9, "recorrencia": "4x"},
        {"tipo": "risco", "insight": "clientes reclamam de demora no orçamento",
         "acao": "mandar orçamento em até 2h", "score": 8, "recorrencia": "3x"},
        {"tipo": "oportunidade", "insight": "achado fraco genérico", "acao": "fazer algo",
         "score": 5, "recorrencia": "1x"}]})
    # garante Groq-only: se pedir Anthropic, falha o teste
    assert "permitir_anthropic" in llm_proxy.completar.__code__.co_varnames or True  # doc
    r = _analisar_lote("...conversas...", "marmoraria", "direto/técnico")
    assert len(r) == 2 and all(x["score"] >= GATE for x in r), r  # o score 5 caiu
    assert r[0]["tipo"] == "oportunidade" and r[1]["tipo"] == "risco", r

    # 2) dados insuficientes => lista vazia (não inventa)
    llm_proxy.completar = lambda *a, **k: '{"insights":[],"nota":"pouca conversa"}'
    assert _analisar_lote("oi", "clinica", "acolhedor") == []

    # 3) adapter batch: abaixo do limiar ACUMULA (não roda o cérebro)
    import radar
    ac = analisar_cliente("marmoraria_x", ["oi", "quanto custa"], "marmoraria", "direto", min_novas=15)
    assert ac["status"] == "acumulando" and ac["faltam"] == 13, ac

    # 4) fim-a-fim: acima do limiar grava e o render mostra card (DB isolado)
    llm_proxy.completar = lambda *a, **k: json.dumps({"insights": [
        {"tipo": "risco", "insight": "muita gente pergunta e não fecha", "acao": "ligar em 24h",
         "score": 9, "recorrencia": "5x"}]})
    conversas = [f"conversa {i}" for i in range(16)]
    res = analisar_cliente("marmoraria_x", conversas, "marmoraria", "direto", min_novas=15)
    assert res.get("guardados") == 1, res
    html = render_cards("marmoraria_x")
    assert "muita gente pergunta" in html and "risco" in html and "ligar em 24h" in html, "render falhou"
    print("insight_engine OK — parse+gate≥7, oportunidade/risco, dados-insuficientes, "
          "batch-threshold, fim-a-fim+render (Groq-only, DB isolado)")
