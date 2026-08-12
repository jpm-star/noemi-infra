"""Agregador do painel de observabilidade (read-only) — funções puras.

Junta 4 fontes REAIS, sem escrever nada: health dos serviços, /spend/logs do
LiteLLM, tabela jobs (SQLite) e obs.jsonl. Cada fonte é best-effort: se uma cair,
o widget dela vira 'offline' e o resto do painel segue. VPS via /proc (stdlib,
sem psutil). Nenhuma ação de escrita/admin.
"""
from __future__ import annotations

import json
import os
import sqlite3
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

_AQUI = Path(__file__).resolve().parent
_DB = os.environ.get("NOEMI_DB", str(_AQUI.parents[1] / "data" / "noemi.db"))
_OBS = os.environ.get("NOEMI_OBS", str(_AQUI.parents[1] / "data" / "obs.jsonl"))
_LITELLM = os.environ.get("LITELLM_URL", "http://127.0.0.1:4000")
_MK = os.environ.get("LITELLM_MASTER_KEY", "")

# serviços monitorados: (nome, url de health, chave de "ok")
_MOTORES = [
    ("LiteLLM", f"{_LITELLM}/health/liveliness", 8),
    ("Motor Vídeo", os.environ.get("MOTORB_URL", "http://127.0.0.1:8010") + "/health", 8),
    ("Motor Site", os.environ.get("STUDIO_URL", "http://127.0.0.1:8020") + "/studio/health", 8),
    # Motor Arbitragem: o default era :8040, com a nota "sem serviço no ar hoje, override
    # a URL quando subir". Subiu — o container `motor-arbitragem` está de pé há 2 semanas
    # (healthy) publicando em 127.0.0.1:8082, e :8082/health responde 200. O override
    # nunca veio, e o painel passou 2 semanas mostrando 'down' de um serviço saudável.
    # Corrigido no DEFAULT de propósito: depender de env que ninguém setou foi a falha.
    ("Motor Arbitragem", os.environ.get("GARIMPO_URL", "http://127.0.0.1:8082") + "/health", 8),
    ("Noemi SDR", os.environ.get("SDR_URL", "http://127.0.0.1:8007") + "/docs", 8),
    ("Ollama", os.environ.get("OLLAMA_URL", "http://127.0.0.1:11434") + "/api/tags", 8),
]


def _get(url: str, timeout: float = 2.5, headers: dict | None = None) -> tuple[int, bytes]:
    req = urllib.request.Request(url, headers=headers or {})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read()
    except Exception:
        return 0, b""


def _pct(parte: float, total: float) -> float:
    return round(100 * parte / total, 1) if total else 0.0


# -- 1) status dos motores -------------------------------------------------
def _checar_motor(nome_url) -> dict:
    nome, url, _ = nome_url
    t0 = time.monotonic()
    code, _b = _get(url)
    ms = round((time.monotonic() - t0) * 1000)
    up = code == 200
    return {"nome": nome, "status": "up" if up else "down",
            "ping_ms": ms if up else None, "badge": "verde" if up else "vermelho"}


def motores() -> list[dict]:
    # PARALELO: os 7 health-checks + WhatsApp rodam juntos (antes eram sequenciais,
    # e 1 serviço down custava o timeout inteiro no loop → era o P95 do painel).
    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=8) as ex:
        saida = list(ex.map(_checar_motor, _MOTORES))
    saida.append(_whatsapp())  # instância(s) do WhatsApp (Evolution)
    return saida


def _whatsapp() -> dict:
    """Estado do WhatsApp via Evolution (nº de instâncias 'open'). up se ≥1 conectada.
    Precisa EVOLUTION_URL + EVOLUTION_APIKEY (global) no env do painel; senão 'down'."""
    url = os.environ.get("EVOLUTION_URL", "").rstrip("/")
    key = os.environ.get("EVOLUTION_APIKEY", "")
    base = {"nome": "WhatsApp", "ping_ms": None, "badge": "vermelho", "status": "down"}
    if not url or not key:
        return {**base, "detalhe": "Evolution não configurada no painel"}
    code, body = _get(f"{url}/instance/fetchInstances", timeout=6, headers={"apikey": key})
    if code != 200:
        return {**base, "detalhe": f"Evolution HTTP {code}"}
    try:
        d = json.loads(body)
        insts = d if isinstance(d, list) else [d]
        estados = [(i.get("instance", i)) for i in insts]
        abertas = [e for e in estados
                   if (e.get("connectionStatus") or e.get("state") or e.get("status")) == "open"]
    except (ValueError, AttributeError):
        return {**base, "detalhe": "resposta ilegível"}
    up = len(abertas) >= 1
    return {"nome": "WhatsApp", "status": "up" if up else "down",
            "ping_ms": len(abertas) if up else None, "badge": "verde" if up else "vermelho",
            "detalhe": f"{len(abertas)}/{len(estados)} conectada(s)"}


# -- 2/3/4) LiteLLM: chamadas, custo, latência, cache, ranking --------------
def _spend_logs(limite: int = 300) -> list[dict]:
    code, body = _get(f"{_LITELLM}/spend/logs", headers={"Authorization": f"Bearer {_MK}"})
    if code != 200:
        return []
    try:
        d = json.loads(body)
        return d if isinstance(d, list) else []
    except ValueError:
        return []


def _percentil(vals: list[float], p: float) -> float:
    if not vals:
        return 0.0
    s = sorted(vals)
    k = min(len(s) - 1, int(round(p / 100 * (len(s) - 1))))
    return round(s[k], 1)


def _dentro(ts: str, desde_epoch: float) -> bool:
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00")).timestamp() >= desde_epoch
    except (ValueError, AttributeError):
        return False


def llm() -> dict:
    logs = _spend_logs()
    if not logs:
        return {"online": False, "recentes": [], "custo": {}, "latencia": {},
                "por_modelo": [], "cache": {}, "total": 0}
    agora = time.time()
    dia, semana, mes = agora - 86400, agora - 7 * 86400, agora - 30 * 86400
    durs, hits, por_modelo, custo = [], 0, {}, {"hoje": 0.0, "semana": 0.0, "mes": 0.0}
    recentes = []
    for x in logs:
        ts = x.get("startTime") or ""
        gasto = float(x.get("spend") or 0)
        dur = float(x.get("request_duration_ms") or 0)
        if dur:
            durs.append(dur)
        if x.get("cache_hit") in (True, "True", "true"):
            hits += 1
        if _dentro(ts, mes):
            custo["mes"] += gasto
        if _dentro(ts, semana):
            custo["semana"] += gasto
        if _dentro(ts, dia):
            custo["hoje"] += gasto
        m = x.get("model") or x.get("model_group") or "?"
        pm = por_modelo.setdefault(m, {"model": m, "n": 0, "custo": 0.0, "dur": [], "erros": 0})
        pm["n"] += 1
        pm["custo"] += gasto
        if dur:
            pm["dur"].append(dur)
        if (x.get("status") or "success") not in ("success", None):
            pm["erros"] += 1
    for x in logs[:12]:
        recentes.append({
            "model": x.get("model"), "provider": x.get("custom_llm_provider"),
            "dur_ms": round(float(x.get("request_duration_ms") or 0)),
            "tokens": x.get("total_tokens"), "spend": round(float(x.get("spend") or 0), 6),
            "cache": bool(x.get("cache_hit") in (True, "True", "true")),
            "status": x.get("status") or "success", "ts": (x.get("startTime") or "")[11:19],
        })
    ranking = sorted(({"model": p["model"], "n": p["n"], "custo": round(p["custo"], 5),
                       "dur_medio": round(sum(p["dur"]) / len(p["dur"])) if p["dur"] else 0,
                       "sucesso": _pct(p["n"] - p["erros"], p["n"])}
                      for p in por_modelo.values()), key=lambda r: -r["n"])
    return {
        "online": True, "total": len(logs), "recentes": recentes,
        "custo": {k: round(v, 5) for k, v in custo.items()},
        "latencia": {"media": round(sum(durs) / len(durs)) if durs else 0,
                     "p95": _percentil(durs, 95), "p99": _percentil(durs, 99)},
        "por_modelo": ranking,
        "cache": {"hit_rate": _pct(hits, len(logs)), "hits": hits},
    }


# -- 5/7) fila + jobs ativos + erros (SQLite) ------------------------------
def _conn():
    c = sqlite3.connect(f"file:{_DB}?mode=ro", uri=True, timeout=2)
    c.row_factory = sqlite3.Row
    return c


_ESTADOS = ["queued", "uploading", "processing", "completed", "failed", "cancelled", "retry"]
_ATIVOS = ("queued", "uploading", "processing", "retry")


def fila() -> dict:
    try:
        with _conn() as c:
            cont = {e: 0 for e in _ESTADOS}
            for r in c.execute("SELECT estado, COUNT(*) n FROM jobs GROUP BY estado"):
                cont[r["estado"]] = r["n"]
            ativos = [dict(r) for r in c.execute(
                "SELECT id, produto, estado, tentativas, duracao_s, atualizado_em FROM jobs "
                "WHERE estado IN ('queued','uploading','processing','retry') "
                "ORDER BY atualizado_em DESC LIMIT 15")]
    except sqlite3.Error:
        return {"online": False, "contagem": {}, "ativos": []}
    for a in ativos:
        a["id"] = a["id"][:8]
    return {"online": True, "contagem": cont, "ativos": ativos,
            "em_andamento": sum(cont[e] for e in _ATIVOS)}


def _bucket(msg: str) -> str:
    m = (msg or "").lower()
    if "timeout" in m or "timed out" in m:
        return "timeout"
    if "429" in m or "rate limit" in m or "quota" in m:
        return "rate limit"
    if "json" in m or "ilegivel" in m or "malformed" in m or "expecting" in m:
        return "JSON inválido"
    if "connection" in m or "refused" in m or "offline" in m or "urlopen" in m:
        return "serviço offline"
    return "outros"


def erros() -> dict:
    grupos: dict[str, int] = {}
    recentes: list[dict] = []
    # jobs falhados
    try:
        with _conn() as c:
            for r in c.execute("SELECT id, erro, atualizado_em FROM jobs "
                               "WHERE estado='failed' AND erro IS NOT NULL "
                               "ORDER BY atualizado_em DESC LIMIT 30"):
                b = _bucket(r["erro"])
                grupos[b] = grupos.get(b, 0) + 1
                if len(recentes) < 12:
                    recentes.append({"fonte": "job " + r["id"][:8], "tipo": b,
                                     "motivo": (r["erro"] or "")[:160], "ts": (r["atualizado_em"] or "")[11:19]})
    except sqlite3.Error:
        pass
    # falhas do obs.jsonl (spans ok=false) — só as últimas 24h (tira ruído histórico)
    corte = time.time() - 86400
    for linha in _tail_obs(400):
        if linha.get("ok") is False and _dentro(linha.get("ts") or "", corte):
            msg = linha.get("erro") or linha.get("motivo") or linha.get("nivel") or "falha"
            b = _bucket(str(msg))
            grupos[b] = grupos.get(b, 0) + 1
            if len(recentes) < 20:
                recentes.append({"fonte": linha.get("span", "?"), "tipo": b,
                                 "motivo": str(msg)[:160], "ts": (linha.get("ts") or "")[11:19]})
    return {"agrupados": grupos, "recentes": recentes[:15]}


# -- 6) fallback Groq→Anthropic→Ollama (obs.jsonl fonte) -------------------
def _tail_obs(n: int) -> list[dict]:
    try:
        with open(_OBS, "rb") as f:
            linhas = f.read().splitlines()[-n:]
    except OSError:
        return []
    out = []
    for l in linhas:
        try:
            out.append(json.loads(l))
        except ValueError:
            continue
    return out


def fallback_hist() -> dict:
    # cascata real: proxy (cloud Groq/Anthropic) → ollama-fallback → regras; mock =
    # sem LLM (determinístico). Reflete o que a classificação de fato usou.
    cont = {"proxy": 0, "ollama-fallback": 0, "regras": 0, "mock": 0, "outros": 0}
    for l in _tail_obs(500):
        if l.get("span") == "motor_b.classificacao" and l.get("fonte"):
            f = l["fonte"]
            if f in cont:
                k = f
            elif "ollama" in f:
                k = "ollama-fallback"
            elif "regras" in f or "fallback" in f:
                k = "regras"
            else:
                k = "outros"
            cont[k] += 1
    return cont


# -- VPS (/proc, stdlib) ----------------------------------------------------
_cpu_prev = {"t": 0.0, "idle": 0.0, "total": 0.0}


def _cpu_pct() -> float:
    try:
        with open("/proc/stat") as f:
            campos = [float(x) for x in f.readline().split()[1:]]
        idle, total = campos[3] + campos[4], sum(campos)
        di, dt = idle - _cpu_prev["idle"], total - _cpu_prev["total"]
        _cpu_prev.update(idle=idle, total=total)
        return round(100 * (1 - di / dt), 1) if dt > 0 else 0.0
    except (OSError, IndexError, ZeroDivisionError):
        return 0.0


def vps() -> dict:
    d = {}
    try:
        mem = {}
        with open("/proc/meminfo") as f:
            for ln in f:
                k, v, *_ = ln.split()
                mem[k.rstrip(":")] = float(v)
        total, disp = mem.get("MemTotal", 0), mem.get("MemAvailable", 0)
        d["ram_pct"] = _pct(total - disp, total)
        d["ram_gb"] = round(total / 1048576, 1)
    except OSError:
        d["ram_pct"] = 0
    try:
        st = os.statvfs("/")
        d["disco_pct"] = _pct(st.f_blocks - st.f_bavail, st.f_blocks)
    except OSError:
        d["disco_pct"] = 0
    try:
        with open("/proc/loadavg") as f:
            d["load1"] = float(f.read().split()[0])
        d["cpus"] = os.cpu_count() or 1
    except OSError:
        d["load1"], d["cpus"] = 0, 1
    d["cpu_pct"] = _cpu_pct()
    try:
        d["obs_kb"] = round(os.path.getsize(_OBS) / 1024, 1)
        d["db_mb"] = round(os.path.getsize(_DB) / 1048576, 1)
    except OSError:
        pass
    return d


# -- financeiro: receita (manual) x custo (medido) x lucro por projeto -------
# Receita vem de data/receita.json (registrada pelo painel/à mão) — acende no
# instante da 1ª venda. Custo é MEDIDO: créditos Higgsfield dos jobs + gasto IA
# do LiteLLM. Câmbio/crédito por env (calibra sem mexer no código — o valor
# real do crédito só o extrato da Higgsfield dá; default é ESTIMADO, marcado).
_RECEITA = _AQUI.parents[1] / "data" / "receita.json"


def _receitas() -> list[dict]:
    try:
        d = json.loads(_RECEITA.read_text("utf-8"))
        return d.get("vendas", d) if isinstance(d, (dict, list)) else []
    except (OSError, ValueError):
        return []


def _creditos_video() -> dict:
    """Créditos Higgsfield gastos em jobs completed (total e últimos 30d) + nº de
    vídeos entregues no mês (pra custo médio por vídeo)."""
    corte = (datetime.now(timezone.utc).timestamp() - 30 * 86400)
    tot = mes = 0.0
    n_mes = 0
    try:
        with _conn() as c:
            for r in c.execute("SELECT custo_creditos, atualizado_em FROM jobs "
                               "WHERE estado='completed' AND custo_creditos IS NOT NULL"):
                v = float(r["custo_creditos"] or 0)
                tot += v
                if _dentro(r["atualizado_em"] or "", corte):
                    mes += v
                    n_mes += 1
    except sqlite3.Error:
        pass
    return {"total": round(tot, 1), "mes": round(mes, 1), "n_mes": n_mes}


def _projeto_canon(nome: str) -> str:
    """Nome da venda → projeto canônico (pra casar receita com os 4 projetos)."""
    n = nome.lower()
    if any(k in n for k in ("sdr", "noemi", "whats", "papai")):
        return "Noemi SDR"
    if any(k in n for k in ("site", "studio", "landing")):
        return "Motor Site"
    if any(k in n for k in ("motor b", "video", "vídeo", "reels")):
        return "Motor B"
    if any(k in n for k in ("arbitr", "garimpo", "china")):
        return "Motor Arbitragem"
    return nome.strip()[:40] or "—"


def financeiro() -> dict:
    usd_brl = float(os.environ.get("USD_BRL", "5.40"))
    cred_brl = float(os.environ.get("HIGGS_CREDITO_BRL", "0.26"))  # real: R$263/1015
    meta_mes = float(os.environ.get("META_RECEITA_MES", "6000"))  # 5 clientes x 1200
    llm_custo = llm().get("custo", {})
    ia_mes = round(float(llm_custo.get("mes", 0)) * usd_brl, 2)
    cred = _creditos_video()
    video_mes = round(cred["mes"] * cred_brl, 2)
    vendas = [v for v in _receitas() if isinstance(v, dict)]
    def _val(v):
        return float(v.get("valor_brl") or v.get("valor") or 0)
    receita_total = round(sum(_val(v) for v in vendas), 2)
    mrr = round(sum(_val(v) for v in vendas if v.get("recorrente")), 2)  # receita recorrente
    custo_total = round(ia_mes + video_mes, 2)
    lucro = round(receita_total - custo_total, 2)
    custo_medio_video = round(video_mes / cred["n_mes"], 2) if cred["n_mes"] else None
    # por projeto: SEMPRE lista os 4 projetos canônicos (mesmo com receita 0),
    # casando a venda pelo nome. Custo de vídeo → Motor B; Groq do SDR é free-tier
    # (~R$0, não metrado); IA compartilhada (LiteLLM) fica em linha própria.
    CANON = ("Noemi SDR", "Motor Site", "Motor B", "Motor Arbitragem")
    por_proj: dict[str, dict] = {p: {"projeto": p, "receita": 0.0, "custo": 0.0} for p in CANON}
    for v in vendas:
        p = _projeto_canon(str(v.get("projeto") or ""))
        por_proj.setdefault(p, {"projeto": p, "receita": 0.0, "custo": 0.0})
        por_proj[p]["receita"] += float(v.get("valor_brl") or v.get("valor") or 0)
    por_proj["Motor B"]["custo"] += video_mes  # créditos Higgsfield medidos
    por_proj.setdefault("IA (compartilhado)", {"projeto": "IA (compartilhado)", "receita": 0.0, "custo": 0.0})
    por_proj["IA (compartilhado)"]["custo"] += ia_mes  # spend LiteLLM (não separa por projeto)
    linhas = [{**r, "receita": round(r["receita"], 2), "custo": round(r["custo"], 2),
               "lucro": round(r["receita"] - r["custo"], 2)} for r in por_proj.values()]
    return {
        "receita_total": receita_total, "custo_total": custo_total, "lucro": lucro,
        "margem_pct": round(lucro / receita_total * 100, 1) if receita_total else None,
        "n_vendas": len(vendas), "mrr": mrr,
        "meta_mes": meta_mes, "meta_pct": round(receita_total / meta_mes * 100, 1) if meta_mes else None,
        "custo": {"ia_brl": ia_mes, "video_brl": video_mes},
        "custo_medio_video": custo_medio_video, "n_videos_mes": cred["n_mes"],
        "creditos_video": cred, "cambio": {"usd_brl": usd_brl, "credito_brl": cred_brl},
        "por_projeto": sorted(linhas, key=lambda x: -x["receita"]),
        "obs": "custo do crédito é REAL (R$263/1015); janela = 30d",
    }


# -- captação de leads (motor-leads → data/leads.db): contador vs meta 1000 ------
_LEADS_DB = _AQUI.parents[1] / "data" / "leads.db"
_LEADS_META = int(os.environ.get("LEADS_META", "1000"))


# preços Places (ESTIMATIVA — confirmar no billing; env sobrescreve). Details puxa
# `reviews` → SKU Atmosphere, o mais caro. Free tier por-SKU/mês (o $200 acabou 03/2025).
_PLACES_USD = {"text_search": float(os.environ.get("PLACES_USD_TEXT", "0.032")),
               "place_details": float(os.environ.get("PLACES_USD_DETAILS", "0.025"))}
_USD_BRL = float(os.environ.get("USD_BRL", "5.40"))
_PLACES_FREE = int(os.environ.get("PLACES_FREE_SKU", "5000"))  # grátis/SKU/mês (Pro)


def _custo_places(c) -> dict:
    """Gasto REAL do grid a partir das chamadas contadas (places_uso). Aplica o
    grátis por-SKU do mês → só cobra o excedente. {} se a tabela não existe ainda."""
    from datetime import date
    try:
        hoje = date.today().isoformat()
        mes = hoje[:7]
        por_sku = dict(c.execute("SELECT sku, SUM(n) FROM places_uso WHERE dia LIKE ? GROUP BY sku",
                                 (mes + "%",)).fetchall())
        hoje_n = c.execute("SELECT COALESCE(SUM(n),0) FROM places_uso WHERE dia=?", (hoje,)).fetchone()[0]
    except sqlite3.Error:
        return {}
    custo = 0.0
    for sku, n in por_sku.items():
        cobravel = max(0, (n or 0) - _PLACES_FREE)  # grátis mensal por SKU
        custo += cobravel * _PLACES_USD.get(sku, 0.0) * _USD_BRL
    return {"chamadas_hoje": hoje_n, "chamadas_mes": sum(v or 0 for v in por_sku.values()),
            "custo_mes_brl": round(custo, 2), "sob_gratis": custo == 0.0}


def leads_captacao() -> dict:
    """Contador de leads coletados vs meta + gasto Places real. Read-only, best-effort."""
    if not _LEADS_DB.exists():
        return {"total": 0, "fila": 0, "com_email": 0, "meta": _LEADS_META,
                "pct": 0.0, "cidades": 0, "taxa_email_pct": 0.0}
    try:
        c = sqlite3.connect(f"file:{_LEADS_DB}?mode=ro", uri=True, timeout=2)
        tot = c.execute("SELECT COUNT(DISTINCT COALESCE(NULLIF(telefone,''),place_id)) FROM leads_clinicas").fetchone()[0]
        fila = c.execute("SELECT COUNT(*) FROM leads_clinicas WHERE passa_corte=1").fetchone()[0]
        email = c.execute("SELECT COUNT(*) FROM leads_clinicas WHERE email IS NOT NULL AND email!=''").fetchone()[0]
        cid = c.execute("SELECT COUNT(DISTINCT cidade_origem) FROM leads_clinicas").fetchone()[0]
        custo = _custo_places(c)
        c.close()
    except sqlite3.Error:
        return {"total": 0, "fila": 0, "com_email": 0, "meta": _LEADS_META, "pct": 0.0,
                "cidades": 0, "taxa_email_pct": 0.0}
    return {"total": tot, "fila": fila, "com_email": email, "meta": _LEADS_META,
            "pct": round(100 * tot / _LEADS_META, 1) if _LEADS_META else 0.0,
            "cidades": cid, "taxa_email_pct": round(100 * email / tot, 1) if tot else 0.0,
            "places": custo}


def leads_csv() -> str:
    """CSV dos leads (colunas do time) pro botão de export. Dedup por telefone."""
    import csv
    import io
    import re
    if not _LEADS_DB.exists():
        return "nome,telefone,cidade,tier,site,email,endereco,avaliacao,multi_unidade,observacoes\n"
    c = sqlite3.connect(f"file:{_LEADS_DB}?mode=ro", uri=True, timeout=3)
    c.row_factory = sqlite3.Row
    rows = c.execute("SELECT * FROM leads_clinicas ORDER BY score_final DESC").fetchall()
    c.close()
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["nome", "telefone", "cidade", "tier", "site", "email", "endereco",
                "avaliacao", "multi_unidade", "observacoes"])
    vistos = set()
    for r in rows:
        tel = re.sub(r"\D", "", r["telefone"] or "")
        if tel and tel in vistos:
            continue
        if tel:
            vistos.add(tel)
        w.writerow([r["nome"], r["telefone"], r["cidade_origem"], r["tier_sugerido"],
                    r["website"], r["email"] or "", r["endereco"], r["rating"],
                    bool((r["n_unidades"] or 1) >= 2), r["motivo_da_dor"]])
    return buf.getvalue()


def snapshot() -> dict:
    """Tudo de uma vez pro painel. Read-only, best-effort por fonte."""
    return {"ts": datetime.now(timezone.utc).isoformat(), "motores": motores(),
            "llm": llm(), "fila": fila(), "erros": erros(),
            "fallback": fallback_hist(), "vps": vps(), "financeiro": financeiro(),
            "leads": leads_captacao()}
