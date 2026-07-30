"""Painel de observabilidade da Noemi OS — FastAPI read-only na :8030.

Serve o snapshot agregado (/api/painel) e a tela única (/painel). Nenhuma rota de
escrita/ação: só leitura e diagnóstico. Mesmo padrão do dashboard do Motor B.
"""
from __future__ import annotations

import re
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
    # stale-while-revalidate: nunca bloqueia no LLM depois da 1ª vez. Cache fresco
    # → devolve; cache velho → devolve o velho JÁ e atualiza em background (mata o
    # "analisando…" travado quando o Groq engasga); sem cache → calcula (1ª vez só).
    fresco = _DIAG_CACHE["dados"] and time.time() - _DIAG_CACHE["ts"] < _DIAG_TTL
    if fresco:
        return _DIAG_CACHE["dados"]
    if _DIAG_CACHE["dados"]:
        if not _DIAG_CACHE.get("atualizando"):
            _DIAG_CACHE["atualizando"] = True
            import threading
            threading.Thread(target=_calcular_diag, daemon=True).start()
        return _DIAG_CACHE["dados"]
    return _calcular_diag()


def _calcular_diag() -> dict:
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
    _DIAG_CACHE.update(ts=time.time(), dados=dados, atualizando=False)
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
# Mensagem curta padrão (impressiona rápido: já mostra um site pronto) + follow-up.
# {empresa} {cidade} {link} são preenchidos por lead. Editável no /obs.
_TPL_ABERTURA = ("Oi, tudo bem? Aqui é a Noemi 👋 Montei um site de demonstração "
                 "pra {empresa} — dá uma olhada rápida: {link}\n\nSe curtir, coloco "
                 "no ar já com atendimento automático no WhatsApp 24h. Posso te mostrar em 1 min?")
_TPL_FOLLOWUP = ("Oi {empresa}! Só pra garantir que chegou 🙂 O site de demonstração "
                 "tá aqui: {link}\n\nTopa eu te mostrar como fica com a Noemi respondendo "
                 "seus clientes 24h (agendamento, dúvida, orçamento)?")
_PROSP_CFG_DEFAULT = {"jitter_min_s": 45, "jitter_max_s": 120, "janela_inicio": "09:00",
                      "janela_fim": "19:00", "pausado": True,
                      "templates": {"padrao": _TPL_ABERTURA, "followup": _TPL_FOLLOWUP,
                                    "clinica": _TPL_ABERTURA.replace("pra {empresa}", "pra clínica {empresa}")}}


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
    # ping de venda: a Noemi te avisa no Telegram quando entra dinheiro (best-effort)
    try:
        from shared_core import notify
        rec = " · recorrente 🔁" if venda["recorrente"] else ""
        notify.telegram(f"🎉 NOVA VENDA — R$ {venda['valor_brl']:.2f}\n"
                        f"{venda['cliente'] or 'cliente'} · {venda['projeto']}{rec}")
    except Exception:
        pass
    return JSONResponse({"ok": True, "venda": venda, "n": len(vendas)})


# -- Histórico JPOS de prospecção: o JP anota approach/objeção/o que falou -------
@app.get("/api/proslog")
def proslog_listar(q: str | None = None) -> JSONResponse:
    import proslog
    return JSONResponse({"log": proslog.listar(q), "resumo": proslog.resumo(),
                         "resultados": list(proslog.RESULTADOS)})


@app.post("/api/proslog")
async def proslog_registrar(req: Request) -> JSONResponse:
    import proslog
    corpo = await req.json()
    return JSONResponse({"ok": True, "entrada": proslog.registrar(corpo)})


# -- Tracker de prospecção: a planilha do JP (prospects + sócios + resumo). ------
# Status manual; "última ligação/canal" derivado do prospeccao_log (preenche só).
@app.get("/api/tracker")
def tracker_dados() -> JSONResponse:
    import tracker
    return JSONResponse({"prospects": tracker.prospects_listar(), "socios": tracker.socios_listar(),
                         "resumo": tracker.resumo(), "status": list(tracker.STATUS),
                         "tiers": list(tracker.TIERS)})


@app.post("/api/tracker/prospect")
async def tracker_prospect_salvar(req: Request) -> JSONResponse:
    import tracker
    return JSONResponse({"ok": True, "prospect": tracker.prospect_salvar(await req.json())})


@app.post("/api/tracker/prospect/deletar")
async def tracker_prospect_deletar(req: Request) -> JSONResponse:
    import tracker
    return JSONResponse(tracker.prospect_deletar(int((await req.json()).get("id") or 0)))


@app.post("/api/tracker/socio")
async def tracker_socio_salvar(req: Request) -> JSONResponse:
    import tracker
    return JSONResponse({"ok": True, "socio": tracker.socio_salvar(await req.json())})


@app.post("/api/tracker/socio/deletar")
async def tracker_socio_deletar(req: Request) -> JSONResponse:
    import tracker
    return JSONResponse(tracker.socio_deletar(int((await req.json()).get("id") or 0)))


@app.post("/api/tracker/importar")
async def tracker_importar(req: Request) -> JSONResponse:
    import tracker
    n = int((await req.json()).get("limite") or 30)
    return JSONResponse(tracker.importar_de_leads(n))


# -- Handoff de contato: quem a IA atende (lista editável, não hardcoded) -------
@app.get("/api/contatos")
def contatos_listar() -> JSONResponse:
    from shared_core import contatos
    conh = contatos.carregar()
    return JSONResponse({"contatos": [{"numero": n, **v} for n, v in conh.items()],
                         "modos": sorted(contatos.MODOS)})


@app.post("/api/contatos")
async def contatos_salvar(req: Request) -> JSONResponse:
    from shared_core import contatos
    corpo = await req.json()
    salvos = contatos.salvar(corpo.get("contatos", []))
    return JSONResponse({"ok": True, "contatos": salvos, "n": len(salvos)})


# -- Verificação de número morto (protege o chip antes do disparo) --------------
@app.post("/api/wa/verificar")
async def wa_verificar(req: Request) -> JSONResponse:
    from shared_core import wa
    corpo = await req.json()
    brutos = corpo.get("numeros")
    if isinstance(brutos, str):  # aceita lista colada (um por linha/vírgula)
        brutos = [x for x in re.split(r"[\n,;]+", brutos) if x.strip()]
    vivos, mortos = wa.filtrar_vivos(brutos or [])
    disponivel = bool(wa.tem_whatsapp(brutos or []))  # {} = checagem indisponível
    return JSONResponse({"vivos": vivos, "mortos": mortos, "n": len(brutos or []),
                         "checagem_disponivel": disponivel})


# -- Radar de Vídeo: análise (yt-dlp→Whisper→insight) com memória persistente ---
@app.post("/api/radar/analisar")
async def radar_analisar(req: Request) -> JSONResponse:
    import asyncio
    import radar
    corpo = await req.json()
    url = str(corpo.get("url") or "").strip()
    origem = str(corpo.get("origem") or "").strip() or None
    instrucao = str(corpo.get("instrucao") or "")  # pedido do JP → responde específico
    forcar = bool(corpo.get("forcar"))  # (6) reanalisar mesmo se já existe
    if not url.startswith("http"):
        return JSONResponse({"ok": False, "erro": "cole um link http(s) válido"}, status_code=400)
    try:  # pipeline pesado (download+STT) roda fora do event loop
        res = await asyncio.to_thread(radar.analisar, url, origem, instrucao, forcar)
        return JSONResponse({"ok": True, "analise": res})
    except Exception as e:  # noqa: BLE001 — vira erro legível, não 500 cru
        return JSONResponse({"ok": False, "erro": str(e)[:300]}, status_code=422)


@app.get("/api/radar/stats")
def radar_stats() -> JSONResponse:
    import radar
    return JSONResponse(radar.stats())


@app.get("/api/radar/status")
def radar_status() -> JSONResponse:
    """Status do radar pro /obs: últimos jobs (ok/falha/motivo) + taxa de sucesso."""
    import radar
    return JSONResponse(radar.status_jobs())


@app.post("/api/radar/deletar")
async def radar_deletar(req: Request) -> JSONResponse:
    import radar
    corpo = await req.json()
    ok = radar.deletar(int(corpo.get("id") or 0))
    return JSONResponse({"ok": ok})


@app.get("/api/radar/analises")
def radar_listar(q: str | None = None) -> JSONResponse:
    import radar
    return JSONResponse({"analises": radar.listar(q)})


@app.get("/api/radar/analise/{aid}")
def radar_obter(aid: int) -> JSONResponse:
    import radar
    a = radar.obter(aid)
    return JSONResponse(a or {"erro": "não encontrada"}, status_code=200 if a else 404)


@app.get("/api/ideias")
def ideias_dados() -> JSONResponse:
    """Caixa de ideias: templates replicáveis colhidos de todas as análises do radar."""
    import radar
    return JSONResponse(radar.harvest_ideias())


@app.get("/api/auto-analise")
def auto_analise_dados() -> JSONResponse:
    """Auto-análise (task 2): retrato atual amarelo/vermelho da própria operação."""
    import insight_engine
    return JSONResponse({"itens": insight_engine.listar_auto()})


@app.post("/api/auto-analise/rodar")
async def auto_analise_rodar() -> JSONResponse:
    """Reanalisa o banco do Radar agora (Groq-only). Substitui o retrato anterior."""
    import asyncio

    import insight_engine
    itens = await asyncio.to_thread(insight_engine.auto_analise)
    return JSONResponse({"itens": itens, "n": len(itens)})


@app.post("/api/beacon")
async def beacon_registrar(req: Request) -> Response:
    """Beacon público do site (Item 5): registra view/cta. Body JSON (sendBeacon).
    204 sempre — tracking nunca falha pro visitante. Rota exposta em jpos.com.br/beacon
    (fora do basic_auth), reescrita pra cá pelo Caddy."""
    import json as _json

    from fastapi import Response as _Resp

    import beacon as _bcn
    try:
        d = _json.loads((await req.body()).decode("utf-8") or "{}")
    except (ValueError, UnicodeDecodeError):
        d = {}
    _bcn.registrar(str(d.get("site", "jpos")), str(d.get("evento", "")),
                   str(d.get("origem", "")), str(d.get("path", "")))
    return _Resp(status_code=204)


@app.get("/api/site/resumo")
def site_resumo(site: str = "jpos") -> JSONResponse:
    """Dado bruto de tráfego pra aba Site (visitas/cta/conversão/origens)."""
    import beacon as _bcn
    return JSONResponse(_bcn.resumo(site))


@app.get("/api/site/analise")
async def site_analise(site: str = "jpos") -> JSONResponse:
    """Tráfego INTERPRETADO por IA (padrão Insight Engine) pra aba Site. Groq-only."""
    import asyncio

    import beacon as _bcn
    return JSONResponse(await asyncio.to_thread(_bcn.analise, site))


_CART_JPOS = "/root/noemi-infra/data/cartucho_jpos.json"
_HTML_JPOS = "/var/www/jpos/index.html"


@app.post("/api/site/editar")
async def site_editar(req: Request) -> JSONResponse:
    """IA nativa (Item 2): comando NL → PROPOSTA de mudança (não aplica; devolve preview)."""
    import asyncio
    import json as _j

    import site_editor
    try:
        d = _j.loads((await req.body()).decode("utf-8") or "{}")
        cart = _j.loads(open(_CART_JPOS, encoding="utf-8").read())
    except (ValueError, OSError):
        return JSONResponse({"suportado": False, "motivo": "cartucho não encontrado / comando inválido"})
    prop = await asyncio.to_thread(site_editor.interpretar, str(d.get("comando", "")), cart)
    return JSONResponse(prop)


@app.post("/api/site/editar/aplicar")
async def site_editar_aplicar(req: Request) -> JSONResponse:
    """Aplica a mudança CONFIRMADA (nunca sem confirmação do front)."""
    import asyncio
    import json as _j

    import site_editor
    d = _j.loads((await req.body()).decode("utf-8") or "{}")
    campo = str(d.get("campo", ""))
    if campo not in site_editor.CAMPOS:
        return JSONResponse({"ok": False, "erro": "campo não editável"})
    r = await asyncio.to_thread(site_editor.aplicar, _CART_JPOS, campo, d.get("valor_novo"), _HTML_JPOS)
    return JSONResponse({"ok": True, **r})


@app.get("/insights/{cliente}", response_class=HTMLResponse)
def insights_cliente(cliente: str) -> str:
    """UI cliente-facing do Insight Engine (task 1). Fora do basic_auth do JP — é a
    página que o subdomínio do cliente aponta. Só leitura (cards já gerados)."""
    import insight_engine
    return insight_engine.render_cards(cliente)


@app.get("/api/leads/export.csv")
def leads_export() -> Response:
    from fastapi.responses import Response as _R
    return _R(content=agg.leads_csv(), media_type="text/csv",
             headers={"Content-Disposition": "attachment; filename=leads_clinicas.csv"})


@app.post("/api/radar/feedback")
async def radar_feedback(req: Request) -> JSONResponse:
    import radar
    corpo = await req.json()
    radar.set_feedback(int(corpo.get("id") or 0), int(corpo.get("valor") or 0))
    return JSONResponse({"ok": True})


@app.get("/api/tuning")
def tuning_dados() -> JSONResponse:
    # aprendizado do agente de self-análise (read-only, pro card do /obs)
    import json
    p = _AQUI.parents[1] / "data" / "tuning_prospeccao.json"
    try:
        return JSONResponse(json.loads(p.read_text("utf-8")))
    except (OSError, ValueError):
        return JSONResponse({"status": "sem_dados", "tuning": {}})


@app.get("/obs/radar", response_class=HTMLResponse)
@app.get("/radar", response_class=HTMLResponse)  # legado (redireciona no front antigo)
def radar_pagina() -> str:
    return (_AQUI / "static" / "radar.html").read_text(encoding="utf-8")


@app.get("/obs/ideias", response_class=HTMLResponse)
def ideias_pagina() -> str:
    return (_AQUI / "static" / "ideias.html").read_text(encoding="utf-8")


# / = QG central (painel de controle); /obs = observação. Mesma HTML, view por JS.
@app.get("/obs", response_class=HTMLResponse)
@app.get("/painel", response_class=HTMLResponse)
@app.get("/", response_class=HTMLResponse)
def painel_pagina() -> str:
    return (_AQUI / "static" / "index.html").read_text(encoding="utf-8")
