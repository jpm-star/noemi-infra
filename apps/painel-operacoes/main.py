"""Painel de observabilidade da Noemi OS — FastAPI read-only na :8030.

Serve o snapshot agregado (/api/painel) e a tela única (/painel). Nenhuma rota de
escrita/ação: só leitura e diagnóstico. Mesmo padrão do dashboard do Motor B.
"""
from __future__ import annotations

import asyncio
import os
import re
import sys
import time
from pathlib import Path

_AQUI = Path(__file__).resolve().parent
sys.path.insert(0, str(_AQUI))
sys.path.insert(0, str(_AQUI.parents[1] / "packages"))  # shared_core (llm_proxy)

from fastapi import FastAPI, File, Form, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response

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
        # CPU pode vir None (1ª leitura / janela curta). "CPU None%" no prompt levaria
        # o LLM a inventar diagnóstico em cima de um valor que não existe.
        f"VPS: CPU {snap['vps'].get('cpu_pct') if snap['vps'].get('cpu_pct') is not None else 'ainda medindo'}"
        f"{'%' if snap['vps'].get('cpu_pct') is not None else ''}, "
        f"RAM {snap['vps'].get('ram_pct')}%, disco {snap['vps'].get('disco_pct')}%, "
        f"load {snap['vps'].get('load1')} em {snap['vps'].get('cpus')} núcleos.",
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


@app.get("/api/motor-b/resumo")
def motor_b_resumo() -> JSONResponse:
    """Motor B (vídeo): serviço, produção, fila e validade da credencial.

    Import lazy porque `motores` fala com serviço externo e com `docker exec` —
    nada disso pode acontecer no import do painel.
    """
    import motores
    return JSONResponse(motores.video())


@app.get("/api/arbitragem/resumo")
def arbitragem_resumo() -> JSONResponse:
    """Arbitragem nas TRÊS camadas, sem somar (ver docstring de `motores`)."""
    import motores
    return JSONResponse(motores.arbitragem())


# --- operação do dia: as oportunidades, com a conta feita ---------------------
# Separado do resumo de propósito: `/resumo` é o estado da INFRAESTRUTURA (o que está
# de pé), isto é o que você viu hoje e vale quanto. Misturar os dois é como o placar
# de "sites gerados" virou orgulho enquanto nenhum lead tinha demo apontada.
@app.get("/api/arbitragem/oportunidades")
def arbitragem_listar(status: str = "") -> JSONResponse:
    import arbitragem_ops
    return JSONResponse(arbitragem_ops.listar(status.strip().lower()))


@app.post("/api/arbitragem/oportunidade")
async def arbitragem_registrar(request: Request) -> JSONResponse:
    import arbitragem_ops
    try:
        corpo = await request.json()
    except ValueError:
        return JSONResponse({"ok": False, "erro": "corpo precisa ser JSON"}, status_code=400)
    r = arbitragem_ops.registrar(corpo)
    return JSONResponse(r, status_code=200 if r.get("ok") else 400)


@app.post("/api/arbitragem/oportunidade/{oid}/status")
async def arbitragem_status(oid: int, request: Request) -> JSONResponse:
    import arbitragem_ops
    try:
        corpo = await request.json()
    except ValueError:
        corpo = {}
    r = arbitragem_ops.mudar_status(oid, (corpo.get("status") or "").strip().lower())
    return JSONResponse(r, status_code=200 if r.get("ok") else 400)


@app.post("/api/arbitragem/simular")
async def arbitragem_simular(request: Request) -> JSONResponse:
    """A conta SEM gravar — é o que se usa com o comprador na linha.

    Devolve os dois modos lado a lado: a mesma oportunidade como revenda (você compra e
    assume frete) e como comissão (você só apresenta). Qual paga mais não é opinião,
    é a conta — e ela muda com o frete."""
    import arbitragem_ops
    try:
        op = await request.json()
    except ValueError:
        return JSONResponse({"erro": "corpo precisa ser JSON"}, status_code=400)
    alvo = float(op.get("margem_alvo_pct") or 30)
    rev = {**op, "modo": "revenda"}
    return JSONResponse({
        "revenda": arbitragem_ops.conta(rev),
        "comissao": arbitragem_ops.conta({**op, "modo": "comissao"}),
        "preco_para_margem": arbitragem_ops.preco_para_margem(rev, alvo),
        "margem_alvo_pct": alvo,
    })


# --- Motor B: repasse das 3 rotas de geração -------------------------------
# O formulário mora nesta página, mas quem gera vídeo é o :8010. Repasse em vez
# de CORS: o navegador fala só com esta origem (que já tem o basic auth do Caddy)
# e o Motor B não precisa aprender a confiar em outro domínio. TRÊS rotas
# nomeadas, nunca um proxy curinga — curinga aqui exporia o :8010 inteiro.
async def _mb(metodo: str, caminho: str, timeout: float = 180, **kw) -> JSONResponse:
    """Uma chamada ao Motor B, com o erro chegando legível do outro lado.

    `r.json()` cru vira 500 sem explicação quando o Motor B responde HTML (proxy
    no meio, 502 do Caddy, traceback do uvicorn). Aqui o corpo não-JSON vira uma
    mensagem que a tela consegue mostrar, preservando o status original.
    """
    import httpx
    import motores
    try:
        async with httpx.AsyncClient(timeout=timeout) as c:
            r = await c.request(metodo, f"{motores._MOTOR_B}{caminho}", **kw)
    except httpx.TimeoutException:
        return JSONResponse({"detail": "Motor B demorou demais para responder."}, status_code=504)
    except httpx.HTTPError as e:
        return JSONResponse({"detail": f"Motor B fora do ar ({type(e).__name__})."}, status_code=502)
    try:
        return JSONResponse(r.json(), status_code=r.status_code)
    except ValueError:
        return JSONResponse({"detail": f"Motor B respondeu {r.status_code} em formato inesperado."},
                            status_code=r.status_code if r.status_code >= 400 else 502)


@app.post("/api/motor-b/upload")
async def motor_b_upload(file: UploadFile = File(...), owner: str = Form("cliente")) -> JSONResponse:
    """Repassa uma mídia. Tipo e tamanho são checados aqui só pra não gastar banda
    à toa; o Motor B continua sendo a autoridade e pode recusar de novo."""
    if not (file.content_type or "").startswith(("image/", "video/")):
        return JSONResponse({"detail": f"tipo não aceito: {file.content_type or 'desconhecido'} "
                                       "(mande imagem ou vídeo)"}, status_code=415)
    dados = await file.read()
    limite = int(os.environ.get("MAX_UPLOAD_MB", "25")) * 1024 * 1024
    if len(dados) > limite:
        return JSONResponse({"detail": f"{file.filename} tem {len(dados)/1048576:.1f} MB e o "
                                       f"limite é {limite//1048576} MB"}, status_code=413)
    if not dados:
        return JSONResponse({"detail": f"{file.filename} está vazio"}, status_code=400)
    return await _mb("POST", "/api/upload",
                     files={"file": (file.filename, dados, file.content_type)},
                     data={"owner": owner})


@app.post("/api/motor-b/jobs")
async def motor_b_criar_job(request: Request) -> JSONResponse:
    try:
        corpo = await request.json()
    except ValueError:
        return JSONResponse({"detail": "corpo precisa ser JSON"}, status_code=400)
    return await _mb("POST", "/api/jobs", json=corpo)


@app.get("/api/motor-b/jobs/{job_id}")
async def motor_b_job(job_id: str) -> JSONResponse:
    # id vem da URL: sem esta trava, qualquer caminho colado aqui vira parte da
    # URL montada pro :8010 (`../../algo`). Job id é hex, ponto.
    if not re.fullmatch(r"[A-Za-z0-9._-]{1,80}", job_id):
        return JSONResponse({"detail": "id de job inválido"}, status_code=400)
    return await _mb("GET", f"/api/jobs/{job_id}", timeout=30)


@app.get("/api/pedi/resumo")
def pedi_resumo() -> JSONResponse:
    """Loja Pé Di: tráfego + catálogo + o que impede a loja de vender."""
    import pedi
    return JSONResponse(pedi.resumo())


@app.post("/api/pedi/midia")
async def pedi_midia(slug: str = Form(...), tipo: str = Form("top"),
                     file: UploadFile = File(...)) -> JSONResponse:
    """Sobe foto ou vídeo de uma estampa e aponta o catálogo pra ela.

    NÃO publica: subir e publicar são ações separadas de propósito, porque
    publicar é o que o cliente vê. Sobe tudo, confere, aí publica.
    """
    import pedi_midia
    dados = await file.read()
    if not dados:
        return JSONResponse({"detail": "arquivo vazio"}, status_code=400)
    ct = (file.content_type or "").lower()
    try:
        if ct.startswith("video/") or tipo == "video":
            caminhos = await asyncio.to_thread(pedi_midia.salvar_video, slug, dados)
            await asyncio.to_thread(pedi_midia.apontar_video, slug, caminhos)
        elif ct.startswith("image/"):
            caminhos = await asyncio.to_thread(pedi_midia.salvar_foto, slug, tipo, dados)
            await asyncio.to_thread(pedi_midia.apontar_foto, slug, tipo, caminhos)
        else:
            return JSONResponse({"detail": f"mande imagem ou vídeo (veio {ct or 'tipo desconhecido'})"},
                                status_code=415)
    except pedi_midia.ErroMidia as e:
        return JSONResponse({"detail": str(e)}, status_code=400)
    return JSONResponse({"ok": True, "slug": slug, "tipo": tipo, "caminhos": caminhos})


@app.get("/api/precos")
def precos_listar(cliente: bool = False) -> JSONResponse:
    """Preço de tiers e upsells. `?cliente=1` esconde o que é provisório.

    Fonte única (`precos.json`). Qualquer material comercial deve ler DAQUI — foi a
    ausência disso que deixou o T3 sendo vendido com Calendar, uma entrega que o
    produto não fazia.
    """
    import precos
    d = precos.para_cliente() if cliente else precos.tudo()
    if not cliente:
        d["problemas"] = precos.validar()
    return JSONResponse(d)


@app.get("/api/precos/tabela")
def precos_tabela(cliente: bool = False) -> Response:
    """A tabela em markdown, pronta pra colar em proposta/apostila."""
    import precos
    return Response(precos.tabela_markdown(cliente=cliente), media_type="text/markdown; charset=utf-8")


@app.get("/api/precos/catalogo.pdf")
def precos_catalogo_pdf(cliente: bool = True) -> Response:
    """O catálogo em PDF — o papel que o JP deixa na mão do dono.

    wkhtmltopdf já está na máquina (nada de dependência nova). Se ele falhar, devolve
    o HTML: pior caso o operador aperta Ctrl+P e imprime igual, em vez de ficar sem
    material na porta do cliente.
    """
    import logging
    import subprocess

    import precos
    html = precos.catalogo_html(cliente=cliente)
    try:
        pdf = subprocess.run(
            ["wkhtmltopdf", "--quiet", "--print-media-type", "--encoding", "utf-8", "-", "-"],
            input=html.encode(), capture_output=True, timeout=60, check=True).stdout
    except Exception:  # noqa: BLE001 — sem PDF ainda dá pra imprimir o HTML
        logging.getLogger("painel.precos").warning(
            "wkhtmltopdf falhou; devolvendo HTML pra impressão", exc_info=True)
        return Response(html, media_type="text/html; charset=utf-8")
    return Response(pdf, media_type="application/pdf", headers={
        "Content-Disposition": 'inline; filename="jpos-catalogo.pdf"'})


@app.get("/api/pedi/catalogo")
def pedi_catalogo_listar() -> JSONResponse:
    import pedi_catalogo
    return JSONResponse({"estampas": pedi_catalogo.listar(), "publicos": list(pedi_catalogo.PUBLICOS)})


@app.post("/api/pedi/catalogo")
async def pedi_catalogo_salvar(request: Request) -> JSONResponse:
    """Cria ou edita uma estampa. `slug` ausente = criar.

    NÃO publica: editar e publicar são ações separadas, como no upload de mídia —
    o operador ajusta várias coisas e decide quando o cliente vê.
    """
    import pedi_catalogo
    import pedi_midia
    try:
        d = await request.json()
    except ValueError:
        return JSONResponse({"detail": "corpo precisa ser JSON"}, status_code=400)
    try:
        if d.get("slug"):
            r = await asyncio.to_thread(pedi_catalogo.salvar, d["slug"], d)
        else:
            r = await asyncio.to_thread(pedi_catalogo.criar, d.get("nome", ""), d)
    except pedi_midia.ErroMidia as e:
        return JSONResponse({"detail": str(e)}, status_code=400)
    return JSONResponse(r)


@app.delete("/api/pedi/catalogo/{slug}")
async def pedi_catalogo_remover(slug: str) -> JSONResponse:
    """Manda a estampa pra lixeira (reversível) — não apaga."""
    import pedi_catalogo
    import pedi_midia
    try:
        r = await asyncio.to_thread(pedi_catalogo.remover, slug)
    except pedi_midia.ErroMidia as e:
        return JSONResponse({"detail": str(e)}, status_code=400)
    return JSONResponse(r)


@app.post("/api/pedi/publicar")
async def pedi_publicar() -> JSONResponse:
    """Build + porteiro + cópia pro diretório servido. Se o porteiro reprovar,
    nada vai ao ar e a saída dele volta pra tela."""
    import pedi_midia
    r = await asyncio.to_thread(pedi_midia.publicar)
    return JSONResponse(r, status_code=200 if r.get("ok") else 400)


@app.get("/api/pedi/custo")
def pedi_custo_resumo() -> JSONResponse:
    """Curva ABC, custo por par, histórico e config. Base própria (pedi_custo.db)."""
    import pedi_custo
    return JSONResponse(pedi_custo.resumo())


@app.post("/api/pedi/custo/item")
async def pedi_custo_item(req: Request) -> JSONResponse:
    """Cria (sem id) ou edita um componente da curva. A diferença vai pro log."""
    import pedi_custo
    d = await req.json()
    try:
        item = pedi_custo.salvar_item(d.get("id"), str(d.get("nome") or ""),
                                      d.get("base"), d.get("premium"),
                                      str(d.get("grupo") or "direto"), str(d.get("nota") or ""))
    except (TypeError, ValueError) as e:
        return JSONResponse({"erro": str(e)}, status_code=400)
    return JSONResponse({"ok": True, "item": item, "custo": {t: pedi_custo.custo_par(t)
                                                             for t in pedi_custo.TIPOS}})


@app.delete("/api/pedi/custo/item/{id_}")
def pedi_custo_remover(id_: int) -> JSONResponse:
    import pedi_custo
    ok = pedi_custo.remover_item(id_)
    return JSONResponse({"ok": ok}, status_code=200 if ok else 404)


@app.post("/api/pedi/custo/simular")
async def pedi_custo_simular(req: Request) -> JSONResponse:
    """Cotação ao vivo: tipo + quantidade + preço → custo, margem, imposto, veredito."""
    import pedi_custo
    d = await req.json()
    try:
        return JSONResponse(pedi_custo.simular(
            str(d.get("tipo") or "BASE"), d.get("qtd") or 0, d.get("preco") or 0,
            bool(d.get("bandeira")), bool(d.get("saquinho"))))
    except (TypeError, ValueError) as e:
        return JSONResponse({"erro": str(e)}, status_code=400)


@app.get("/api/pedi/toque")
def pedi_toque_fila(todos: int = 0) -> JSONResponse:
    """Fila de primeiro toque com mensagem e link de WhatsApp já montados."""
    import pedi_toque
    return JSONResponse({"fila": pedi_toque.fila(incluir_tocados=bool(todos)),
                         "placar": pedi_toque.placar()})


@app.post("/api/pedi/toque/marcar")
async def pedi_toque_marcar(req: Request) -> JSONResponse:
    """Registra o toque. Sem isso a fila devolve o mesmo lead amanhã."""
    import pedi_toque
    d = await req.json()
    return JSONResponse(pedi_toque.marcar(str(d.get("id") or ""), str(d.get("resultado") or "enviado")))


@app.get("/api/demos/fila")
def demos_fila() -> JSONResponse:
    """Demos prontos pra prospectar: contato, vídeo e mensagem já montada."""
    import pedi_hub
    return JSONResponse({"fila": pedi_hub.fila_demos()})


@app.get("/api/pedi/hub")
def pedi_hub_estado() -> JSONResponse:
    """Saúde + demos publicados + jobs. Uma chamada, a tela inteira."""
    import pedi_hub
    return JSONResponse({"saude": pedi_hub.saude(), "demos": pedi_hub.listar_demos(),
                         "jobs": pedi_hub.jobs()})


@app.post("/api/pedi/hub/sondar")
async def pedi_hub_sondar(req: Request) -> JSONResponse:
    """Consulta o Places ANTES de gerar — barato e evita demo sem foto."""
    import pedi_hub
    d = await req.json()
    try:
        return JSONResponse(await asyncio.to_thread(pedi_hub.sondar, str(d.get("busca") or "")))
    except Exception as e:  # noqa: BLE001
        return JSONResponse({"erro": str(e)}, status_code=400)


@app.post("/api/pedi/hub/gerar")
async def pedi_hub_gerar(req: Request) -> JSONResponse:
    import pedi_hub
    d = await req.json()
    try:
        jid = pedi_hub.job_gerar_demo(str(d.get("nome") or ""), str(d.get("cidade") or ""),
                                      str(d.get("tier") or "T3"), str(d.get("modelo") or "assessoria"))
    except (TypeError, ValueError) as e:
        return JSONResponse({"erro": str(e)}, status_code=400)
    return JSONResponse({"job": jid})


@app.post("/api/pedi/hub/regerar")
async def pedi_hub_regerar(req: Request) -> JSONResponse:
    import pedi_hub
    d = await req.json()
    return JSONResponse({"job": pedi_hub.job_regerar(str(d.get("slug") or ""),
                                                     str(d.get("tier") or ""))})


@app.post("/api/pedi/hub/excluir")
async def pedi_hub_excluir(req: Request) -> JSONResponse:
    import pedi_hub
    d = await req.json()
    try:
        return JSONResponse(await asyncio.to_thread(pedi_hub.excluir_demo, str(d.get("slug") or "")))
    except ValueError as e:
        return JSONResponse({"erro": str(e)}, status_code=400)


@app.post("/api/pedi/hub/captar")
async def pedi_hub_captar(req: Request) -> JSONResponse:
    import pedi_hub
    d = await req.json()
    return JSONResponse({"job": pedi_hub.job_captar(
        str(d.get("segmento") or ""), list(d.get("cidades") or []), int(d.get("alvo") or 10))})


@app.get("/api/pedi/leads.csv")
def pedi_leads_csv() -> Response:
    """Baixa a fila de leads. Fica atrás do login do painel como todo o resto."""
    import os
    p = Path(os.environ.get("PEDI_LEADS_CSV", "/root/jpos-entregaveis/pedi_leads.csv"))
    if not p.exists():
        return JSONResponse({"erro": "sem CSV ainda — capte leads primeiro"}, status_code=404)
    return Response(p.read_bytes(), media_type="text/csv",
                    headers={"Content-Disposition": 'attachment; filename="pedi_leads.csv"'})


@app.get("/api/diagnostico")
def diagnostico_dados() -> JSONResponse:
    return JSONResponse(_diagnostico())


@app.get("/api/qa-visual/sites")
def qa_visual_sites() -> JSONResponse:
    """Slugs auditáveis — o front precisa saber o que pode pedir."""
    import qa_visual
    return JSONResponse({"slugs": qa_visual.slugs_publicados()})


@app.post("/api/qa-visual/auditar")
def qa_visual_auditar(slug: str = Form(...), com_visao: bool = Form(True)) -> JSONResponse:
    """Roda o gate visual num site publicado.

    `qa_visual` era CLI puro — zero import fora dele e dos testes. As sondas
    anti-genérico (hierarquia quebrada, CTA morto, adjetivo sem prova) eram
    inalcançáveis pela web, então quem não abre terminal não tinha gate nenhum.

    Recebe SLUG, não URL: `auditar()` aceita qualquer endereço e abre um Chromium
    de verdade nele. Expor a URL seria SSRF — o painel viraria um proxy pra rede
    interna. O slug é validado contra os publicados antes de virar URL.

    Demora (Chromium + networkidle + 2,5s + LLM da visão). É `def` e não `async def`
    de propósito: o FastAPI joga numa thread e o event loop segue livre.
    """
    import qa_visual
    if slug not in qa_visual.slugs_publicados():
        return JSONResponse({"erro": f"slug não publicado: {slug}"}, status_code=404)
    return JSONResponse(qa_visual.auditar(f"{qa_visual.BASE_URL}/{slug}/", com_visao=com_visao))


@app.get("/api/qa-copy/bloqueios")
def qa_copy_bloqueios(limite: int = 20) -> JSONResponse:
    """O que o QA de copy barrou, e por quê.

    `qa_copy.bloqueios()` existia com ZERO callers fora do self-check do próprio
    arquivo. O portão é fail-closed (2 reprovas não publicam), então o operador via a
    geração falhar sem nenhuma forma de descobrir o motivo pela web — só por terminal.
    Só leitura. Import lazy: `qa_copy` toca SQLite na importação.
    """
    import qa_copy
    return JSONResponse({"bloqueios": qa_copy.bloqueios(limite=max(1, min(200, limite)))})


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


# -- Caixa de Ideias (Fase 0 KOS): busca semântica + dedup sobre video_analises. ----
@app.get("/api/kb/buscar")
def kb_buscar(q: str = "", k: int = 8) -> JSONResponse:
    import kb_busca
    return JSONResponse({"q": q, "resultados": kb_busca.buscar(q, k) if q.strip() else []})


@app.post("/api/kb/indexar")
async def kb_indexar() -> JSONResponse:
    import kb_busca
    return JSONResponse(kb_busca.indexar())


@app.get("/api/kb/duplicados")
def kb_duplicados(threshold: float = 0.95) -> JSONResponse:
    import kb_busca
    return JSONResponse({"pares": kb_busca.duplicados(threshold)})


@app.get("/api/tracker/fila")
def tracker_fila() -> JSONResponse:
    # Aba Prospecção (desenho A): fila do dia AO VIVO — view filtrada, nada se move.
    import tracker
    return JSONResponse({**tracker.fila_prospeccao(100), "status": list(tracker.STATUS)})


@app.post("/api/tracker/enriquecer")
async def tracker_enriquecer(req: Request) -> JSONResponse:
    # DADO um CNPJ → preenche razão social + puxa o QSA (sócios) via BrasilAPI (grátis).
    import tracker, cnpj
    b = await req.json()
    return JSONResponse(tracker.enriquecer_cnpj(int(b.get("id") or 0), str(b.get("cnpj") or ""), cnpj.buscar))


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
@app.post("/api/radar/pdf")
async def radar_pdf(arquivo: UploadFile = File(...), instrucao: str = Form(""),
                    origem: str = Form("pdf")) -> JSONResponse:
    """Sobe um PDF e roda a MESMA pipeline de insight do vídeo/imagem."""
    import asyncio
    import os as _os
    import tempfile as _tmp

    import radar
    if not arquivo.filename:
        return JSONResponse({"ok": False, "erro": "envie um arquivo"}, status_code=422)
    dados = await arquivo.read()
    if not dados:
        return JSONResponse({"ok": False, "erro": "arquivo vazio"}, status_code=422)
    if len(dados) > 40 * 1024 * 1024:
        return JSONResponse({"ok": False, "erro": "PDF acima de 40MB"}, status_code=422)
    tmp = _tmp.mkdtemp(prefix="pdf_")
    caminho = _os.path.join(tmp, _os.path.basename(arquivo.filename)[:80] or "doc.pdf")
    with open(caminho, "wb") as f:
        f.write(dados)
    try:  # extração + visão + LLM: pesado, fora do event loop
        res = await asyncio.to_thread(radar.analisar_pdf, caminho, origem, instrucao)
        return JSONResponse({"ok": True, **res})
    except Exception as e:  # noqa: BLE001
        return JSONResponse({"ok": False, "erro": str(e)[:250]}, status_code=422)
    finally:
        import shutil
        shutil.rmtree(tmp, ignore_errors=True)


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


# -- QG Pessoal: controle de vida/financeiro (Noemi anota → aparece aqui). additive. ----
@app.get("/api/pessoal/listar")
def pessoal_listar(tipo: str | None = None) -> JSONResponse:
    import pessoal
    return JSONResponse({"itens": pessoal.listar(tipo), "saldo": pessoal.saldo_mes()})


@app.post("/api/pessoal/add")
async def pessoal_add(req: Request) -> JSONResponse:
    import pessoal
    d = await req.json()
    try:
        item = pessoal.add(str(d.get("texto") or ""), tipo=str(d.get("tipo") or "nota"),
                           valor=d.get("valor"), categoria=str(d.get("categoria") or ""),
                           origem=str(d.get("origem") or "painel"))
    except ValueError as e:
        return JSONResponse({"ok": False, "erro": str(e)}, status_code=400)
    return JSONResponse({"ok": True, "item": item})


@app.post("/api/pessoal/status")
async def pessoal_status(req: Request) -> JSONResponse:
    import pessoal
    d = await req.json()
    return JSONResponse({"ok": pessoal.set_status(int(d.get("id") or 0), str(d.get("status") or "aberto"))})


@app.post("/api/pessoal/deletar")
async def pessoal_deletar(req: Request) -> JSONResponse:
    import pessoal
    d = await req.json()
    return JSONResponse({"ok": pessoal.deletar(int(d.get("id") or 0))})


# -- Leads-alvo (sem site): fila de WhatsApp/telefone, filtrável. read-only. --------
@app.get("/api/leads-alvo")
def leads_alvo_listar(motivo: str = "", categoria: str = "", cidade: str = "",
                      tier: str = "", q: str = "") -> JSONResponse:
    import leads_alvo
    return JSONResponse({"leads": leads_alvo.listar(motivo, categoria, cidade, tier, q),
                         "resumo": leads_alvo.resumo()})


# -- Criação: interface operacional do motor de sites (fala com montar_site real). --
@app.get("/api/criacao/sites")
def criacao_sites() -> JSONResponse:
    import criacao
    return JSONResponse({"sites": criacao.listar_sites()})


@app.get("/api/captacao/origens")
def captacao_origens() -> JSONResponse:
    """Vocabulário FECHADO, servido da fonte da verdade. A UI monta o select com isto
    em vez de repetir a lista no front — lista repetida é lista que diverge."""
    import captacao
    return JSONResponse({"origens": list(captacao.ORIGENS), "padrao": captacao.PADRAO})


@app.post("/api/captacao/marcar")
async def captacao_marcar(slug: str = Form(...), origem: str = Form(...)) -> JSONResponse:
    """Corrige a origem de um cliente já criado. Toda a validação é do captacao.marcar:
    valor fora do vocabulário, slug vazio e site sem registro são recusados LÁ, não aqui."""
    import captacao
    r = captacao.marcar(slug, origem)
    return JSONResponse(r, status_code=200 if r.get("ok") else 422)


@app.get("/api/criacao/lead")
def criacao_lead(nome: str = "") -> JSONResponse:
    """C1 — autofill: devolve o que a pesquisa já sabe do lead (tracker + leads-alvo)."""
    import criacao
    return JSONResponse(criacao.dados_lead(nome))


@app.get("/api/criacao/referencias")
def criacao_referencias(segmento: str = "") -> JSONResponse:
    """Repositório de aprendizado: referências de ESTRUTURA que o JP subiu."""
    import receitas
    return JSONResponse({"referencias": receitas.referencias_listar(segmento),
                         "segmentos": sorted(receitas.RECEITAS),
                         "receitas": {s: [r["nome"] for r in v] for s, v in receitas.RECEITAS.items()}})


@app.post("/api/criacao/referencia")
async def criacao_referencia_subir(tag: str = Form(""), segmento: str = Form(""),
                                   tipo: str = Form("estrutura"),
                                   imagem: UploadFile | None = File(None)) -> JSONResponse:
    """Input de aprendizado: print de site bom + tag + segmento. A visão (Groq, grátis)
    lê e PROPÕE a receita de estrutura; o JP aprova pra ela entrar no pool do segmento."""
    import asyncio
    import os as _os
    from pathlib import Path as _P

    import receitas
    if not imagem or not imagem.filename:
        return JSONResponse({"ok": False, "erro": "envie uma imagem de referência"}, status_code=422)
    dados = await imagem.read()
    if not dados:
        return JSONResponse({"ok": False, "erro": "imagem vazia"}, status_code=422)
    destino = _P(_os.environ.get("NOEMI_DATA_DIR", str(_AQUI.parents[1] / "data"))) / "referencias"
    destino.mkdir(parents=True, exist_ok=True)
    ext = (imagem.filename.rsplit(".", 1)[-1] or "jpg").lower()[:5]
    nome_arq = f"ref-{int(time.time())}.{ext if ext.isalnum() else 'jpg'}"
    (destino / nome_arq).write_bytes(dados)
    # visão é I/O de rede: fora do event loop
    proposta = await asyncio.to_thread(receitas.ler_referencia, dados, tag)
    r = receitas.referencia_salvar(tag, segmento, nome_arq, proposta, tipo=tipo,
                                   aprovada=bool(proposta.get("ordem")))
    return JSONResponse({"ok": True, "referencia": r,
                         "leu": bool(proposta.get("ordem")),
                         "aviso": "" if proposta.get("ordem") else
                                  "a visão não conseguiu ler a estrutura — guardada, aprove/edite à mão"})


@app.post("/api/criacao/referencia/aprovar")
async def criacao_referencia_aprovar(req: Request) -> JSONResponse:
    import receitas
    c = await req.json()
    return JSONResponse(receitas.referencia_aprovar(int(c.get("id") or 0), bool(c.get("aprovada", True))))


@app.post("/api/criacao/referencias/lote")
async def criacao_referencias_lote(segmento: str = Form(""),
                                   imagens: list[UploadFile] = File([])) -> JSONResponse:
    """Upload em LOTE de referências (até 50). O caminho de 1-por-vez era o gargalo:
    a biblioteca ficou em ZERO por meses porque alimentar custava um print de cada vez.

    A visão roda por arquivo, fora do event loop. Falha em um NÃO derruba o lote —
    subir 50 e perder tudo por causa do 30º é pior que salvar 49."""
    import asyncio
    import os as _os
    import time as _t
    from pathlib import Path as _P

    import receitas
    arqs = [u for u in (imagens or []) if u and u.filename][:50]
    if not arqs:
        return JSONResponse({"ok": False, "erro": "nenhum arquivo"}, status_code=422)
    destino = _P(_os.environ.get("NOEMI_DATA_DIR", str(_AQUI.parents[1] / "data"))) / "referencias"
    destino.mkdir(parents=True, exist_ok=True)
    salvas, falhas = [], []
    for i, up in enumerate(arqs):
        try:
            dados = await up.read()
            if not dados:
                falhas.append({"arquivo": up.filename, "erro": "vazio"})
                continue
            ext = (up.filename.rsplit(".", 1)[-1] or "jpg").lower()[:5]
            nome_arq = f"ref-{int(_t.time())}-{i:02d}.{ext if ext.isalnum() else 'jpg'}"
            (destino / nome_arq).write_bytes(dados)
            receita = await asyncio.to_thread(receitas.ler_referencia, dados, up.filename)
            r = receitas.referencia_salvar(
                tag=up.filename[:60], segmento=segmento, imagem=nome_arq,
                receita=receita or {}, tipo="estrutura",
                aprovada=bool((receita or {}).get("ordem")))
            salvas.append({"arquivo": up.filename, "id": r.get("id"),
                           "ordem": (receita or {}).get("ordem") or []})
        except Exception as e:  # noqa: BLE001 — um arquivo ruim não derruba o lote
            falhas.append({"arquivo": up.filename, "erro": str(e)[:80]})
    return JSONResponse({"ok": True, "salvas": len(salvas), "falhas": len(falhas),
                         "detalhe": salvas[:50], "erros": falhas[:10]})


@app.post("/api/criacao/referencias/scrap")
async def criacao_referencias_scrap(segmento: str = Form(...), url: str = Form(""),
                                    galeria: str = Form(""),
                                    limite: int = Form(12)) -> JSONResponse:
    """Ingestão AUTOMÁTICA por URL/galeria: estrutura sai do HTML, sem print e sem LLM.

    É o que tira a biblioteca do zero sem depender do JP colar imagem."""
    import asyncio

    import referencias_scrap as rs
    if not (url.strip() or galeria.strip()):
        return JSONResponse({"ok": False, "erro": "informe url ou galeria"}, status_code=422)
    if url.strip():
        r = await asyncio.to_thread(rs.de_url, url, segmento, "", True)
    else:
        r = await asyncio.to_thread(rs.de_galeria, galeria, segmento, max(1, min(limite, 40)), True)
    return JSONResponse(r, status_code=200 if r.get("ok") else 422)


@app.post("/api/criacao/referencia/apagar")
async def criacao_referencia_apagar(req: Request) -> JSONResponse:
    import receitas
    return JSONResponse(receitas.referencia_apagar(int((await req.json()).get("id") or 0)))


@app.post("/api/criacao/ingerir")
async def criacao_ingerir(req: Request) -> JSONResponse:
    """INGESTÃO TOTAL: site atual + formulário + CRM num briefing só, com procedência.
    Não gera nada — devolve o material consolidado pro JP conferir antes."""
    import asyncio

    import ingestao
    c = await req.json()
    res = await asyncio.to_thread(  # buscar site é I/O de rede
        ingestao.consolidar, nome=str(c.get("nome") or ""),
        site_url=str(c.get("site_url") or ""), formulario=str(c.get("formulario") or ""),
        fotos=int(c.get("fotos") or 0), videos=int(c.get("videos") or 0),
        usar_crm=bool(c.get("usar_crm", True)))
    return JSONResponse(res)


@app.post("/api/criacao/validar-tier")
async def criacao_validar_tier(req: Request) -> JSONResponse:
    """Diagnóstico ANTES de gerar: o material sustenta o tier escolhido?"""
    import tier_contrato
    c = await req.json()
    material = {k: c.get(k) for k in ("nome", "nicho", "whatsapp", "telefone", "cidade",
                                      "diferenciais", "servicos", "email", "midia")}
    return JSONResponse(tier_contrato.validar(c.get("tier", "T1"), material))


@app.get("/api/studio/lead/{prospect_id}")
def studio_lead(prospect_id: int) -> JSONResponse:
    """Prefill do Studio a partir do card da Prospecção: CRM + QSA + achado, tudo
    marcado como INFERIDO. T3/T4 com site traz o site atual como fonte de ingestão."""
    import criacao
    return JSONResponse(criacao.briefing_do_lead(prospect_id))


@app.post("/api/studio/lead/{prospect_id}/demo")
async def studio_registrar_demo(prospect_id: int, req: Request) -> JSONResponse:
    """Fecha o ciclo: o link da demo volta pro card do lead (sem copiar e colar)."""
    import criacao
    d = await req.json()
    r = criacao.registrar_demo(prospect_id, str(d.get("url") or ""))
    return JSONResponse(r, status_code=200 if r.get("ok") else 422)


@app.get("/api/studio/operacao")
def studio_operacao() -> JSONResponse:
    """STUDIO #4 — o que acontece DEPOIS do site: conversão real, meta por tier,
    canal por cliente e custo (só do que está instrumentado). Lê o mesmo CRM de
    /obs/prospeccao, não duplica dado."""
    import operacao
    return JSONResponse({**operacao.resumo(), "lista": operacao.sites_com_lead()})


@app.get("/api/studio/modelos")
def studio_modelos(nicho: str = "", tier: str = "", nome: str = "",
                   lead_id: int = 0) -> JSONResponse:
    """STUDIO #2 — galeria selecionável (9 morfismos + estruturas do segmento) com o
    que o motor escolheria sozinho marcado. O CSS vem da mesma fonte da geração."""
    import criacao
    return JSONResponse(criacao.modelos(nicho, tier, nome, lead_id))


@app.get("/api/studio/galeria")
def studio_galeria() -> JSONResponse:
    """STUDIO #2 — galeria: sites com o que o preview não mostra (seções, cores) e
    quantos OUTROS sites saíram do mesmo esqueleto."""
    import galeria
    return JSONResponse(galeria.listar())


@app.get("/api/criacao/escopo")
def criacao_escopo(tier: str = "T1") -> JSONResponse:
    """O que o motor executa naquele tier (cumulativo)."""
    import tier_contrato
    return JSONResponse({"tier": tier.upper(), "escopo": tier_contrato.escopo_de(tier)})


@app.get("/api/criacao/estilos")
def criacao_estilos(segmento: str = "") -> JSONResponse:
    """Morfismos aplicáveis (camada de acabamento) + conceitos estruturais do segmento."""
    import estilos
    return JSONResponse({"estilos": estilos.listar(), "conceitos": estilos.conceitos(segmento)})


@app.post("/api/criacao/apagar")
def criacao_apagar(slug: str = Form(...)) -> JSONResponse:
    """C2 — apaga site (pasta + registro). Irreversível; confirmação é na UI."""
    import criacao
    r = criacao.apagar(slug)
    return JSONResponse(r, status_code=200 if r.get("ok") else 422)


@app.post("/api/criacao/limpar-orfaos")
def criacao_limpar_orfaos() -> JSONResponse:
    """C2 — varre o registro e remove linhas cujo site não existe mais em disco."""
    import criacao
    return JSONResponse(criacao.limpar_orfaos())


@app.post("/api/criacao/gerar")
async def criacao_gerar(nome: str = Form(...), nicho: str = Form(...), whatsapp: str = Form(""),
                        diferenciais: str = Form(""), publico: str = Form(""), cor: str = Form(""),
                        copy_livre: str = Form(""), foto: UploadFile | None = File(None),
                        video: UploadFile | None = File(None),
                        fotos: list[UploadFile] = File([]),
                        estilo: str = Form(""), autofill: str = Form(""),
                        lead_id: int = Form(0), tier: str = Form(""),
                        receita_nome: str = Form(""), cidade: str = Form(""),
                        email: str = Form(""),
                        variacao: int = Form(0),
                        origem_captacao: str = Form("")) -> JSONResponse:
    import asyncio
    import functools

    import criacao
    # PROMPT 2: foto/vídeo/copy opcionais (multipart). Sem eles = geração por briefing (fallback).
    f = (await foto.read(), foto.filename) if (foto and foto.filename) else None
    v = (await video.read(), video.filename) if (video and video.filename) else None
    # C3: acervo do cliente (20+ fotos) — OCR vira contexto da copy + galeria no site
    fs = [(await u.read(), u.filename) for u in (fotos or []) if u and u.filename]
    # geração é pesada (LLM + template + deploy) — fora do event loop
    # snapshot do que o autofill preencheu — a ficha compara com o valor final pra
    # saber o que o motor acertou sozinho vs o que o JP teve que corrigir.
    try:
        af = __import__("json").loads(autofill) if autofill else {}
    except ValueError:
        af = {}
    # POR NOME, NUNCA POSICIONAL. Esta chamada já quebrou a geração em produção com
    # "gerar() takes 18 positional arguments but 19 were given" — `variacao` entrou no
    # endpoint e no front, e nunca na assinatura. O TypeError foi o desfecho BOM: com o
    # parâmetro no meio da lista em vez do fim, `cidade` teria virado `receita_nome`
    # em silêncio e o site sairia publicado com os campos trocados.
    res = await asyncio.to_thread(
        functools.partial(
            criacao.gerar, nome=nome, nicho=nicho, whatsapp=whatsapp,
            diferenciais=diferenciais, publico=publico, cor=cor, preset=0,
            foto=f, video=v, copy_livre=copy_livre, fotos=fs, estilo=estilo,
            autofill=af, lead_id=lead_id, tier=tier, receita_nome=receita_nome,
            cidade=cidade, email=email, variacao=variacao,
            origem_captacao=origem_captacao))
    return JSONResponse(res, status_code=200 if res.get("ok") else 422)


# -- Radar Grátis (PÚBLICO, sem auth): upload de vídeo → insight. 15MB, 10/dia. -----
@app.post("/api/radar/publico")
async def radar_publico_analisar(request: Request,
                                 arquivo: UploadFile = File(...), email: str = Form("")) -> JSONResponse:
    import os
    import tempfile

    import radar_publico
    xff = request.headers.get("x-forwarded-for", "")
    ip = (xff.split(",")[0].strip() if xff else (request.client.host if request.client else "")) or "?"
    portao = radar_publico.pode_usar(ip)
    if not portao["ok"]:
        return JSONResponse(portao, status_code=429)
    # lê com teto rígido de 15MB (aborta streaming se exceder — não estoura memória/disco)
    dados = b""
    while True:
        chunk = await arquivo.read(262144)
        if not chunk:
            break
        dados += chunk
        if len(dados) > radar_publico.MAX_BYTES:
            return JSONResponse({"ok": False, "erro": "Vídeo acima de 15MB. Corte um trecho menor e tente de novo."},
                                status_code=413)
    if len(dados) < 1000:
        return JSONResponse({"ok": False, "erro": "Arquivo vazio ou muito pequeno."}, status_code=400)
    suf = (os.path.splitext(arquivo.filename or "video.mp4")[1] or ".mp4")[:6]
    tmp = tempfile.NamedTemporaryFile(prefix="radarpub_", suffix=suf, delete=False)
    try:
        tmp.write(dados)
        tmp.close()
        resultado = radar_publico.analisar(tmp.name)
    except Exception as e:  # noqa: BLE001 — erro honesto pro usuário, nunca 500 cru
        return JSONResponse({"ok": False, "erro": str(e)[:200]}, status_code=200)
    finally:
        try:
            os.unlink(tmp.name)
        except OSError:
            pass
    radar_publico.registrar_uso(email, ip, resultado)
    return JSONResponse({"ok": True, **resultado})


@app.get("/api/radar/publico/leads")
def radar_publico_leads() -> JSONResponse:
    import radar_publico
    return JSONResponse({"leads": radar_publico.leads()})


@app.get("/api/ideias")
def ideias_dados() -> JSONResponse:
    """Caixa de ideias: templates replicáveis colhidos de todas as análises do radar."""
    import radar
    return JSONResponse(radar.harvest_ideias())


@app.get("/api/ideias.csv")
def ideias_csv():
    """Export CSV da caixa de ideias (UTF-8 BOM p/ Excel PT-BR). Herda o basic_auth do
    Caddy como toda rota /api do painel — não é rota pública."""
    from fastapi.responses import Response as _R
    import radar
    return _R(content=radar.harvest_ideias_csv(), media_type="text/csv; charset=utf-8",
              headers={"Content-Disposition": "attachment; filename=caixa_de_ideias.csv"})


@app.get("/api/radar/export.md")
def radar_export_md(piso: int = 0, acionaveis: bool = False) -> Response:
    """Radar em Markdown, pra revisar fora do painel.

    `acionaveis=true` reduz ao que tem score >= 8 E ainda não recebeu feedback — o
    critério está declarado em `radar_export.PISO_ACIONAVEL`, não escondido aqui."""
    import radar_export
    nome = "radar-acionaveis.md" if acionaveis else "radar.md"
    return Response(radar_export.markdown(piso, acionaveis), media_type="text/markdown",
                    headers={"Content-Disposition": f'attachment; filename="{nome}"'})


@app.get("/api/radar/export.json")
def radar_export_json(piso: int = 0) -> Response:
    """Radar cru + a auto-análise, pra reprocessar fora daqui."""
    import json as _j

    import radar_export
    return Response(_j.dumps(radar_export.dados(piso), ensure_ascii=False, indent=1),
                    media_type="application/json",
                    headers={"Content-Disposition": 'attachment; filename="radar.json"'})


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


@app.get("/obs/arbitragem", response_class=HTMLResponse)
def arbitragem_pagina() -> str:
    return (_AQUI / "static" / "arbitragem.html").read_text(encoding="utf-8")


@app.get("/obs/pedi-toque", response_class=HTMLResponse)
def pedi_toque_pagina() -> str:
    """Fila de primeiro toque da Pé Di: lead + mensagem pronta + WhatsApp."""
    return (_AQUI / "static" / "pedi-toque.html").read_text(encoding="utf-8")


@app.get("/obs/pedi", response_class=HTMLResponse)
def pedi_central_pagina() -> str:
    """Central Pé Di: sondar, gerar demo, captar lead — sem sair do painel."""
    return (_AQUI / "static" / "pedi.html").read_text(encoding="utf-8")


@app.get("/obs/pedi-calculadora", response_class=HTMLResponse)
def pedi_calculadora_pagina() -> str:
    """Calculadora da Pé Di: curva ABC + simulador de cotação ao vivo."""
    return (_AQUI / "static" / "pedi-calculadora.html").read_text(encoding="utf-8")


@app.get("/obs/pessoal", response_class=HTMLResponse)
def pessoal_pagina() -> str:
    return (_AQUI / "static" / "pessoal.html").read_text(encoding="utf-8")


@app.get("/obs/leads", response_class=HTMLResponse)
def leads_pagina() -> str:
    return (_AQUI / "static" / "leads.html").read_text(encoding="utf-8")


@app.get("/obs/criar", response_class=HTMLResponse)
def criar_pagina() -> str:
    """INTERFACE ÚNICA (2026-08-05). Fusão de /obs/criacao + /obs/studio: as duas
    chamavam a MESMA API e mantinham duas linguagens visuais (dark vs esmeralda) pro
    mesmo trabalho. Aqui: Criar · Ingestão · Sites gerados · Aprendizado · Operação."""
    return (_AQUI / "static" / "criar.html").read_text(encoding="utf-8")


@app.get("/obs/criar.js")
def criar_js() -> Response:
    return Response((_AQUI / "static" / "criar.js").read_text(encoding="utf-8"),
                    media_type="application/javascript")


# Rotas ANTIGAS: redirecionam em vez de sumir. Link morto em favorito/histórico do JP
# (e o `?lead=` que a Prospecção manda) é o tipo de quebra que só aparece na pior hora.
@app.get("/obs/criacao")
@app.get("/obs/studio")
def _rotas_antigas(request: Request) -> RedirectResponse:
    q = request.url.query
    return RedirectResponse(f"/obs/criar{'?' + q if q else ''}", status_code=307)


@app.get("/obs/prospeccao", response_class=HTMLResponse)
def prospeccao_pagina() -> str:
    """Fila do dia pronta pra ligar: quem, em que ordem, falando o quê."""
    return (_AQUI / "static" / "prospeccao.html").read_text(encoding="utf-8")


@app.get("/obs/campo", response_class=HTMLResponse)
def campo_pagina() -> str:
    """CAMPO — o material de cold call/porta-a-porta do JP e do Lincon (T3/T4).

    Página separada da /obs/prospeccao de propósito: aquela é a fila de TODOS os tiers
    na tela; esta é feita pra IMPRIMIR e levar no carro, com a rota do dia e o script
    completo por lead. São dois usos que pedem layouts opostos."""
    return (_AQUI / "static" / "campo.html").read_text(encoding="utf-8")


@app.get("/api/campo/script")
def campo_script(tier: str = "", limite: int = 200, objecoes: bool = True) -> JSONResponse:
    """Fila T3/T4 em rota geográfica, com abertura de 15s e objeções por segmento."""
    import script_call
    return JSONResponse(script_call.lista(tier=tier, limite=limite, com_objecoes=objecoes))


@app.get("/api/campo/ritmo")
def campo_ritmo() -> JSONResponse:
    """Meta, dias úteis restantes e quanto tem que sair por dia útil."""
    import ritmo
    return JSONResponse(ritmo.painel())


@app.post("/api/campo/fechamento")
async def campo_fechamento(request: Request) -> JSONResponse:
    """Registra o valor fechado de um prospect — é o que tira o widget de 'estimada'.

    Sem este caminho o contador nunca sairia da premissa: alguém precisa dizer quanto
    entrou de verdade, e esse alguém é quem fechou."""
    import sqlite3

    import ritmo
    c = await request.json()
    pid, valor = int(c.get("prospect_id") or 0), float(c.get("valor") or 0)
    if pid <= 0 or valor < 0:
        return JSONResponse({"ok": False, "erro": "prospect_id e valor são obrigatórios"},
                            status_code=400)
    ritmo.garantir_coluna()
    try:
        with ritmo._db() as cx:
            cur = cx.execute("UPDATE tracker_prospects SET valor_fechado=?, status='Fechado' "
                             "WHERE id=?", (valor or None, pid))
            cx.commit()
    except sqlite3.Error as e:
        return JSONResponse({"ok": False, "erro": str(e)}, status_code=500)
    if not cur.rowcount:
        return JSONResponse({"ok": False, "erro": f"prospect {pid} não existe"}, status_code=404)
    return JSONResponse({"ok": True, "prospect_id": pid, "valor": valor,
                         "ritmo": ritmo.painel()})


@app.get("/api/catalogo/crescimento")
def catalogo_crescimento() -> JSONResponse:
    """Quanto o catálogo cresceu com o uso real: nichos vistos fora da lista,
    composições que sobreviveram, e o que está esperando alguém escrever o perfil."""
    import catalogo_vivo
    return JSONResponse(catalogo_vivo.crescimento())


@app.post("/api/catalogo/promover")
async def catalogo_promover(request: Request) -> JSONResponse:
    """Tira o candidato da fila DEPOIS que o perfil foi escrito à mão em estilos.PERFIS.

    Não escreve o perfil: perfil é justificativa comercial por morfismo, texto que uma
    contagem não sabe produzir. Promover automático encheria o vocabulário de entradas
    sem porquê — que é o mesmo que a composição genérica que isto veio resolver.
    """
    import catalogo_vivo
    c = await request.json()
    r = catalogo_vivo.promover(str(c.get("tipo") or "nicho"), str(c.get("chave") or ""))
    return JSONResponse(r, status_code=200 if r.get("ok") else 400)


@app.get("/api/campo/buscar")
def campo_buscar(q: str = "") -> JSONResponse:
    """Acha o prospect pelo nome pra registrar a venda. `q` vazio lista os já fechados.

    Existe porque a fila da /obs/campo é só T3/T4 (68 leads) e o funil tem 1.462 em
    T1/T2 — fechar um T1 na porta e não achar o nome na tela é o caso comum."""
    import venda
    return JSONResponse({"resultados": venda.buscar(q)})


@app.post("/api/campo/venda")
async def campo_venda(request: Request) -> JSONResponse:
    """Registra a venda fechada. Aceita prospect existente OU nome novo (cria na hora).

    Substitui o /api/campo/fechamento, que exigia `prospect_id` e não gravava tier —
    e que nenhuma tela chamava, e por isso o funil ficou com valor_fechado vazio em
    100% das 1.532 linhas."""
    import venda
    c = await request.json()
    r = venda.registrar(prospect_id=int(c.get("prospect_id") or 0),
                        empresa=str(c.get("empresa") or ""),
                        tier=str(c.get("tier") or ""),
                        valor=c.get("valor") or 0,
                        quando=str(c.get("quando") or ""),
                        notas=str(c.get("notas") or ""))
    return JSONResponse(r, status_code=200 if r.get("ok") else 400)


@app.post("/api/campo/venda/desfazer")
async def campo_venda_desfazer(request: Request) -> JSONResponse:
    """Digitou o valor errado ou marcou o cliente errado. Sem isto a correção seria
    no banco na mão — e no campo isso não acontece, o erro só fica lá."""
    import venda
    c = await request.json()
    r = venda.desfazer(int(c.get("prospect_id") or 0))
    return JSONResponse(r, status_code=200 if r.get("ok") else 400)


@app.get("/api/prospeccao/dia")
def prospeccao_dia_listar(tier: str = "", limite: int = 200) -> JSONResponse:
    """Leads ainda sem contato (T1 primeiro), com gancho honesto pronto por tier."""
    import prospeccao_dia
    return JSONResponse(prospeccao_dia.lista_do_dia(tier, limite))


@app.post("/api/prospeccao/nota")
async def prospeccao_nota(req: Request) -> JSONResponse:
    """Anotação do JP por lead: como foi a ligação e a reação à demo."""
    import prospeccao_dia
    c = await req.json()
    return JSONResponse(prospeccao_dia.nota_salvar(
        int(c.get("prospect_id") or 0), c.get("ligacao", ""), c.get("reacao_demo", "")))


@app.post("/api/prospeccao/status")
async def prospeccao_status(req: Request) -> JSONResponse:
    """Move o lead no funil pela AÇÃO do botão/kanban (status que já existem)."""
    import prospeccao_dia
    c = await req.json()
    r = prospeccao_dia.status_salvar(int(c.get("prospect_id") or 0), c.get("acao", ""))
    return JSONResponse(r, status_code=200 if r.get("ok") else 422)


@app.get("/api/prospeccao/dia.csv")
def prospeccao_dia_csv(tiers: str = "T3,T4", limite: int = 500):
    """CSV pra ligar offline. Default T3/T4 — os que o JP liga pessoalmente."""
    from fastapi.responses import Response as _R
    import prospeccao_dia
    nome = tiers.replace(",", "-").lower() or "fila"
    return _R(content=prospeccao_dia.csv_lista(tiers, limite),
              media_type="text/csv; charset=utf-8",
              headers={"Content-Disposition": f'attachment; filename="ligar_{nome}.csv"'})


# Radar Grátis — página PÚBLICA (liberada no Caddy sem basic-auth). Self-serve.
@app.get("/radar-gratis", response_class=HTMLResponse)
def radar_gratis_pagina() -> str:
    return (_AQUI / "static" / "radar-gratis.html").read_text(encoding="utf-8")


# / = QG central (painel de controle); /obs = observação. Mesma HTML, view por JS.
@app.get("/obs", response_class=HTMLResponse)
@app.get("/painel", response_class=HTMLResponse)
@app.get("/", response_class=HTMLResponse)
def painel_pagina() -> HTMLResponse:
    """A tela única.

    `no-cache` não é paranoia: o HTML carrega TODO o JS embutido, então uma cópia
    velha no navegador é um painel velho inteiro — sem asset com hash pra denunciar
    a diferença. Sem este header a resposta sai sem política nenhuma e o navegador
    cacheia por heurística própria; foi assim que um deploy anterior "não apareceu"
    até dar refresh forçado. `no-cache` ainda revalida com ETag, então o custo é um
    304 vazio, não o HTML de novo a cada carga.
    """
    html = (_AQUI / "static" / "index.html").read_text(encoding="utf-8")
    return HTMLResponse(html, headers={"Cache-Control": "no-cache, must-revalidate"})
