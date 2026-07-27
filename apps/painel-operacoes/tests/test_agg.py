"""Painel: agregador read-only — helpers puros + shape do snapshot (sem rede)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import agg


def test_bucket_classifica_erros():
    assert agg._bucket("Read timed out") == "timeout"
    assert agg._bucket("429 rate limit exceeded") == "rate limit"
    assert agg._bucket("Expecting value: line 1 (JSON)") == "JSON inválido"
    assert agg._bucket("Connection refused") == "serviço offline"
    assert agg._bucket("algo estranho") == "outros"


def test_percentil():
    v = [10, 20, 30, 40, 50]
    assert agg._percentil(v, 95) == 50
    assert agg._percentil([], 95) == 0.0


def test_pct():
    assert agg._pct(1, 4) == 25.0
    assert agg._pct(1, 0) == 0.0  # sem divisão por zero


def test_sla_video_estourando_e_lentos(tmp_path, monkeypatch):
    # item 15: fila() sinaliza job passando de 60s AGORA + lentos que já terminaram
    import sqlite3
    from datetime import datetime, timedelta, timezone
    db = tmp_path / "noemi.db"
    now = datetime.now(timezone.utc)
    with sqlite3.connect(db) as c:
        c.execute("CREATE TABLE jobs (id TEXT, produto TEXT, estado TEXT, tentativas INT, "
                  "duracao_s REAL, atualizado_em TEXT)")
        # processing há 2 min → estourando agora
        c.execute("INSERT INTO jobs VALUES (?,?,?,?,?,?)",
                  ("a"*12, "motor-b-video", "processing", 0, None,
                   (now - timedelta(seconds=120)).isoformat()))
        # completed rápido (30s) → não conta
        c.execute("INSERT INTO jobs VALUES (?,?,?,?,?,?)",
                  ("b"*12, "motor-b-video", "completed", 0, 30.0, (now - timedelta(hours=1)).isoformat()))
        # completed lento (90s) nas últimas 24h → lentos_24h
        c.execute("INSERT INTO jobs VALUES (?,?,?,?,?,?)",
                  ("c"*12, "motor-b-video", "completed", 0, 90.0, (now - timedelta(hours=2)).isoformat()))
    monkeypatch.setattr(agg, "_DB", str(db))
    sv = agg.fila()["sla_video"]
    assert sv["limite_s"] == 60
    assert len(sv["estourando_agora"]) == 1 and sv["estourando_agora"][0]["s"] >= 120
    assert sv["lentos_24h"] == 1  # só o de 90s; o de 30s não conta


def test_snapshot_shape_nao_crasha(monkeypatch):
    # fontes indisponíveis não podem derrubar o snapshot (best-effort por fonte)
    monkeypatch.setattr(agg, "_get", lambda *a, **k: (0, b""))       # serviços fora
    monkeypatch.setattr(agg, "_DB", "/nao/existe.db")
    monkeypatch.setattr(agg, "_OBS", "/nao/existe.jsonl")
    s = agg.snapshot()
    assert set(s) >= {"motores", "llm", "fila", "erros", "fallback", "vps"}
    assert all(m["status"] == "down" for m in s["motores"])   # todos down, sem crashar
    assert s["llm"]["online"] is False and s["fila"]["online"] is False
    assert "cpu_pct" in s["vps"]  # VPS (/proc) sempre responde
