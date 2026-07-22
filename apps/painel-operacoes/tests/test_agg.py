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
