"""Agente de self-análise cross-projeto (v0) — DADO pra alavanca, não feature de painel.

Lê os logs de RESULTADO REAL de dois projetos:
  - prospecção Noemi (proslog: approach/objeção/o que falei/resultado/hora)
  - Radar (video_analises: padrões de concorrente/conteúdo que o JP guardou)
extrai o PADRÃO DE CONVERSÃO com o LLM (Groq, não espera Anthropic) e escreve
parâmetros de TUNING de volta em data/tuning_prospeccao.json — que o prospector
(cartucho/mensagem) e o motor de arbitragem consomem. Roda por timer/on-demand.

Não é fine-tuning: é contexto/parâmetro derivado de dado real (CLAUDE.md ok).
Com pouco dado, devolve honestamente "colete mais" em vez de inventar padrão.
"""
from __future__ import annotations

import json
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

_AQUI = Path(__file__).resolve().parent
_LEADS_DB = _AQUI.parents[1] / "data" / "leads.db"
_NOEMI_DB = _AQUI.parents[1] / "data" / "noemi.db"
_TUNING = _AQUI.parents[1] / "data" / "tuning_prospeccao.json"
_MIN_APPROACHES = 8  # abaixo disso não há sinal estatístico — não inventa padrão


def _ro(p: Path) -> sqlite3.Connection | None:
    if not p.exists():
        return None
    c = sqlite3.connect(f"file:{p}?mode=ro", uri=True, timeout=3)
    c.row_factory = sqlite3.Row
    return c


def coletar_dados() -> dict:
    """Resumo estruturado dos 2 projetos (proslog + radar). Read-only, best-effort."""
    prosp, radar = [], []
    c = _ro(_LEADS_DB)
    if c:
        try:
            prosp = [dict(r) for r in c.execute(
                "SELECT empresa,resultado,objecao,o_que_falei,substr(criado_em,12,5) hora "
                "FROM prospeccao_log ORDER BY id DESC LIMIT 200")]
        except sqlite3.Error:
            pass
        c.close()
    c = _ro(_NOEMI_DB)
    if c:
        try:
            radar = [dict(r) for r in c.execute(
                "SELECT origem,categoria,score,substr(insight,1,160) insight "
                "FROM video_analises WHERE score>=4 ORDER BY id DESC LIMIT 30")]
        except sqlite3.Error:
            pass
        c.close()
    return {"prospeccao": prosp, "radar": radar}


def _stats_prospeccao(prosp: list[dict]) -> dict:
    """Métricas determinísticas (TIER 0, sem LLM): taxa por resultado, objeções, horas."""
    from collections import Counter
    res = Counter(p.get("resultado") for p in prosp)
    obj = Counter((p.get("objecao") or "").strip().lower() for p in prosp if (p.get("objecao") or "").strip())
    hora = Counter((p.get("hora") or "")[:2] for p in prosp if p.get("hora"))
    total = len(prosp)
    fechou = res.get("fechou", 0) + res.get("agendou", 0)
    return {"total": total, "por_resultado": dict(res),
            "taxa_conversao_pct": round(100 * fechou / total, 1) if total else 0.0,
            "objecoes_top": [o for o, _ in obj.most_common(5)],
            "melhores_horas": [h + "h" for h, _ in hora.most_common(3)]}


def analisar(dados: dict, *, completar=None) -> dict:
    """Padrão de conversão + tuning via LLM (Groq). Degrada pro determinístico se
    o LLM cair. `completar` injetável (teste)."""
    stats = _stats_prospeccao(dados.get("prospeccao", []))
    base = {"gerado_em": datetime.now(timezone.utc).isoformat(), "stats": stats,
            "n_radar": len(dados.get("radar", []))}
    if stats["total"] < _MIN_APPROACHES:
        return {**base, "status": "dados_insuficientes",
                "faltam": _MIN_APPROACHES - stats["total"],
                "tuning": {}, "nota": f"colete +{_MIN_APPROACHES - stats['total']} approaches no /obs"}
    if completar is None:
        from shared_core.ai import llm_proxy
        completar = lambda p: llm_proxy.completar(p, model="analise", max_tokens=700, temperature=0.3)
    prompt = (
        "Você é o analista de conversão do JP (vende Noemi, SDR no WhatsApp). Dados REAIS "
        "de prospecção e padrões de concorrentes (Radar). Extraia o que CONVERTE e escreva "
        "parâmetros de tuning pro prospector. Responda SOMENTE JSON: "
        '"padrao_conversao" (2-3 frases do que funciona), '
        '"angulo_vencedor" (1 frase — o gancho de abertura que mais converte), '
        '"rebuttals" (objeto objeção→resposta curta pras objeções mais comuns), '
        '"melhores_horas" (lista), "para_arbitragem" (1 frase de insight reaproveitável).\n\n'
        f"PROSPECÇÃO (stats): {json.dumps(stats, ensure_ascii=False)}\n"
        f"APPROACHES: {json.dumps(dados['prospeccao'][:40], ensure_ascii=False)[:4000]}\n"
        f"RADAR (concorrentes): {json.dumps(dados['radar'][:15], ensure_ascii=False)[:2000]}")
    txt = completar(prompt)
    m = re.search(r"\{.*\}", txt or "", re.S)
    tuning = {}
    if m:
        try:
            tuning = json.loads(m.group(0))
        except (ValueError, TypeError):
            tuning = {}
    if not tuning:  # LLM fora → tuning determinístico (rebuttals vazios, mas stats reais)
        return {**base, "status": "deterministico",
                "tuning": {"angulo_vencedor": "", "rebuttals": {},
                           "melhores_horas": stats["melhores_horas"], "para_arbitragem": ""}}
    tuning.setdefault("melhores_horas", stats["melhores_horas"])
    return {**base, "status": "ok", "tuning": tuning}


def rodar() -> dict:
    """Coleta → analisa → GRAVA o tuning (o prospector lê data/tuning_prospeccao.json)."""
    res = analisar(coletar_dados())
    _TUNING.parent.mkdir(parents=True, exist_ok=True)
    _TUNING.write_text(json.dumps(res, ensure_ascii=False, indent=2), "utf-8")
    return res


if __name__ == "__main__":
    import sys
    if "--selftest" in sys.argv:  # stats + degradação (sem rede)
        prosp = [{"resultado": "fechou", "objecao": "", "o_que_falei": "roi", "hora": "10:20"},
                 {"resultado": "recusou", "objecao": "achou caro", "o_que_falei": "x", "hora": "15:00"},
                 {"resultado": "agendou", "objecao": "", "o_que_falei": "demo", "hora": "10:40"}] * 3
        st = _stats_prospeccao(prosp)
        assert st["total"] == 9 and st["taxa_conversao_pct"] > 0 and "10h" in st["melhores_horas"], st
        # < MIN → dados insuficientes
        r = analisar({"prospeccao": prosp[:3], "radar": []})
        assert r["status"] == "dados_insuficientes", r
        # >= MIN, LLM devolve JSON válido
        r = analisar({"prospeccao": prosp, "radar": []},
                     completar=lambda p: '{"angulo_vencedor":"foco no ROI","rebuttals":{"achou caro":"mostro o custo/agendamento"}}')
        assert r["status"] == "ok" and r["tuning"]["angulo_vencedor"] == "foco no ROI", r
        print("autotune OK — stats reais, dados_insuficientes, tuning do LLM")
    else:
        print(json.dumps(rodar(), ensure_ascii=False))
