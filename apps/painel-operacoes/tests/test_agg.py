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


def test_cpu_primeira_leitura_nao_chuta():
    """1ª leitura não tem intervalo anterior: None, nunca a média-desde-o-boot."""
    agg._cpu_prev.update(t=0.0, idle=0.0, total=0.0, ultimo=None)
    assert agg._cpu_pct() is None


def test_cpu_ignora_janela_curta():
    """Duas leituras coladas: repete a última medição em vez de recalcular sobre
    um dt de milissegundos — a origem do falso '88,8%' no painel."""
    import time
    agg._cpu_prev.update(t=time.time(), idle=1.0, total=2.0, ultimo=17.5)
    assert agg._cpu_pct() == 17.5
