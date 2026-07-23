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
    # Motor Arbitragem (Exodia/motor-garimpo): experimental, sem serviço no ar hoje —
    # aparece 'down' honesto até ganhar deploy. Override a URL quando subir.
    ("Motor Arbitragem", os.environ.get("GARIMPO_URL", "http://127.0.0.1:8040") + "/health", 8),
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
def motores() -> list[dict]:
    saida = []
    for nome, url, _ in _MOTORES:
        t0 = time.monotonic()
        code, _b = _get(url)
        ms = round((time.monotonic() - t0) * 1000)
        up = code == 200
        saida.append({"nome": nome, "status": "up" if up else "down",
                      "ping_ms": ms if up else None,
                      "badge": "verde" if up else "vermelho"})
    return saida


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
    # falhas do obs.jsonl (spans ok=false)
    for linha in _tail_obs(400):
        if linha.get("ok") is False:
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


def snapshot() -> dict:
    """Tudo de uma vez pro painel. Read-only, best-effort por fonte."""
    return {"ts": datetime.now(timezone.utc).isoformat(), "motores": motores(),
            "llm": llm(), "fila": fila(), "erros": erros(),
            "fallback": fallback_hist(), "vps": vps()}
