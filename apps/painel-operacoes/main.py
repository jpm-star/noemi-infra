"""Painel de observabilidade da Noemi OS — FastAPI read-only na :8030.

Serve o snapshot agregado (/api/painel) e a tela única (/painel). Nenhuma rota de
escrita/ação: só leitura e diagnóstico. Mesmo padrão do dashboard do Motor B.
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

_AQUI = Path(__file__).resolve().parent
sys.path.insert(0, str(_AQUI))
sys.path.insert(0, str(_AQUI.parents[1] / "packages"))  # shared_core (llm_proxy)

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse

import agg

app = FastAPI(title="Painel Noemi OS")

_DIAG_CACHE: dict = {"ts": 0.0, "dados": None}
_DIAG_TTL = 90  # segundos — não chama o LLM a cada refresh (custo/latência)


def _resumo(snap: dict) -> str:
    """Comprime o snapshot no sinal que importa pro diagnóstico."""
    down = [m["nome"] for m in snap["motores"] if m["status"] != "up"]
    L, F = snap["llm"], snap["fila"]
    linhas = [
        f"Serviços fora: {down or 'nenhum'}.",
        f"Fila: {F.get('em_andamento', 0)} rodando, {F.get('contagem', {}).get('failed', 0)} falharam.",
        f"Falhas agrupadas: {snap['erros']['agrupados'] or 'nenhuma'}.",
        f"Custo hoje: ${L.get('custo', {}).get('hoje', 0)}. Latência P95: {L.get('latencia', {}).get('p95', 0)}ms.",
        f"Cascata de IA (uso): {snap['fallback']}.",
        f"VPS: CPU {snap['vps'].get('cpu_pct')}%, RAM {snap['vps'].get('ram_pct')}%, disco {snap['vps'].get('disco_pct')}%.",
    ]
    return " ".join(linhas)


def _diagnostico() -> dict:
    if _DIAG_CACHE["dados"] and time.time() - _DIAG_CACHE["ts"] < _DIAG_TTL:
        return _DIAG_CACHE["dados"]
    snap = agg.snapshot()
    resumo = _resumo(snap)
    prompt = (
        "Você é o operador sênior da Noemi OS (SO que roda geração de sites, vídeos de "
        "imóvel e arbitragem). Olhe o estado AGORA e dê no máximo 3 dicas curtas, "
        "concretas e acionáveis (o que fazer já), priorizando o que impede vender ou o "
        "que quebrou. Uma dica por linha, começando com '- '. Se está tudo saudável, "
        "responda só '- Operação saudável, nada urgente.'\n\nEstado: " + resumo)
    try:
        from shared_core.ai import llm_proxy
        txt = llm_proxy.completar(prompt, model="analise", max_tokens=220, temperature=0.2)
    except Exception:
        txt = None
    if not txt:  # proxy fora → dica por regra (best-effort, nunca vazio)
        down = [m["nome"] for m in snap["motores"] if m["status"] != "up"]
        txt = ("- " + ", ".join(down) + " fora — reiniciar/checar." if down
               else "- IA indisponível; operação sem alertas críticos pelos números.")
    dicas = [l.strip("- ").strip() for l in txt.splitlines() if l.strip().startswith("-")] or [txt.strip()]
    dados = {"dicas": dicas[:3], "resumo": resumo, "gerado_em": snap["ts"], "fonte": "analise"}
    _DIAG_CACHE.update(ts=time.time(), dados=dados)
    return dados


@app.get("/health")
def health() -> dict:
    return {"ok": True}


@app.get("/api/painel")
def painel_dados() -> JSONResponse:
    return JSONResponse(agg.snapshot())


@app.get("/api/diagnostico")
def diagnostico_dados() -> JSONResponse:
    return JSONResponse(_diagnostico())


# Fila de prospecção: demos de site gerados p/ prospects (status manual do JP).
# Fonte = data/prospeccao.json (escrito pelo lote batch_demos + edição à mão).
_PROSPECCAO = _AQUI.parents[1] / "data" / "prospeccao.json"


@app.get("/api/prospeccao")
def prospeccao_dados() -> JSONResponse:
    import json
    try:
        return JSONResponse(json.loads(_PROSPECCAO.read_text(encoding="utf-8")))
    except (OSError, ValueError):
        return JSONResponse({"prospects": [], "tenant": None})


# Config editável da fila de prospecção (jitter/janela/pausa/templates por nicho).
# Lida pelo enviador de prospecção (sdr-motor) e pela geração de mensagens.
_PROSP_CFG = _AQUI.parents[1] / "data" / "prospeccao_config.json"
_PROSP_CFG_DEFAULT = {"jitter_min_s": 45, "jitter_max_s": 120, "janela_inicio": "09:00",
                      "janela_fim": "19:00", "pausado": True, "templates": {}}


@app.get("/api/prospeccao/config")
def prospeccao_config() -> JSONResponse:
    import json
    try:
        return JSONResponse({**_PROSP_CFG_DEFAULT, **json.loads(_PROSP_CFG.read_text("utf-8"))})
    except (OSError, ValueError):
        return JSONResponse(_PROSP_CFG_DEFAULT)


@app.post("/api/prospeccao/config")
async def prospeccao_config_salvar(req: Request) -> JSONResponse:
    import json
    novo = await req.json()
    # só campos conhecidos, com saneamento leve (nunca confia no corpo cru)
    cfg = dict(_PROSP_CFG_DEFAULT)
    try:
        cfg["jitter_min_s"] = max(5, int(novo.get("jitter_min_s", cfg["jitter_min_s"])))
        cfg["jitter_max_s"] = max(cfg["jitter_min_s"], int(novo.get("jitter_max_s", cfg["jitter_max_s"])))
        cfg["janela_inicio"] = str(novo.get("janela_inicio", cfg["janela_inicio"]))[:5]
        cfg["janela_fim"] = str(novo.get("janela_fim", cfg["janela_fim"]))[:5]
        cfg["pausado"] = bool(novo.get("pausado", cfg["pausado"]))
        t = novo.get("templates", {})
        cfg["templates"] = {str(k)[:40]: str(v)[:800] for k, v in t.items()} if isinstance(t, dict) else {}
    except (TypeError, ValueError) as e:
        return JSONResponse({"ok": False, "erro": str(e)}, status_code=400)
    _PROSP_CFG.parent.mkdir(parents=True, exist_ok=True)
    _PROSP_CFG.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), "utf-8")
    return JSONResponse({"ok": True, "config": cfg})


# Registro de venda: a 1ª receita acende o dashboard financeiro na hora.
# Append saneado em data/receita.json (única rota de escrita fora prospecção).
_RECEITA = _AQUI.parents[1] / "data" / "receita.json"


@app.post("/api/receita")
async def receita_registrar(req: Request) -> JSONResponse:
    import json
    novo = await req.json()
    try:
        valor = float(novo.get("valor_brl") or novo.get("valor") or 0)
    except (TypeError, ValueError):
        return JSONResponse({"ok": False, "erro": "valor inválido"}, status_code=400)
    if valor <= 0:
        return JSONResponse({"ok": False, "erro": "valor deve ser > 0"}, status_code=400)
    venda = {"valor_brl": round(valor, 2),
             "cliente": str(novo.get("cliente") or "")[:120],
             "projeto": str(novo.get("projeto") or "—")[:40],
             "data": str(novo.get("data") or "")[:10],
             "recorrente": bool(novo.get("recorrente", False))}
    try:
        atual = json.loads(_RECEITA.read_text("utf-8"))
        vendas = atual.get("vendas", []) if isinstance(atual, dict) else atual
    except (OSError, ValueError):
        vendas = []
    vendas.append(venda)
    _RECEITA.parent.mkdir(parents=True, exist_ok=True)
    _RECEITA.write_text(json.dumps({"vendas": vendas}, ensure_ascii=False, indent=2), "utf-8")
    return JSONResponse({"ok": True, "venda": venda, "n": len(vendas)})


@app.get("/painel", response_class=HTMLResponse)
@app.get("/", response_class=HTMLResponse)
def painel_pagina() -> str:
    return (_AQUI / "static" / "index.html").read_text(encoding="utf-8")
