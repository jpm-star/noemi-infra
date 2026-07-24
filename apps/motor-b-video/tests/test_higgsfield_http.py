"""Caminho HTTP direto (sem loop Anthropic): parsing SSE + fluxo import→gen→poll
com o transporte MCP mockado (nenhuma rede)."""
import json
from shared_core.ai.providers import higgsfield_http as hh


def test_sse_parse_e_job_id():
    sse = 'event: message\ndata: {"result":{"content":[{"type":"text","text":"ok"}]}}\n'
    assert hh._sse_json(sse)["result"]["content"][0]["text"] == "ok"
    assert hh._job_id({"results": [{"id": "j1"}]}) == "j1"
    assert hh._job_id({}) is None


def test_prompt_mantem_guardrail():
    p = hh._prompt({"prompt": "órbita suave"})
    assert "órbita suave" in p and "NÃO invente" in p


def test_fluxo_completo_mockado(monkeypatch):
    # sequência de respostas do MCP: import → generate → status(completo)
    respostas = iter([
        {"media_id": "m1", "_text": '{"media_id":"m1"}'},
        {"results": [{"id": "job42"}], "_text": "..."},
        {"status": "completed", "_text": "Job job42 — completed\nhttps://x/v.mp4"},
    ])
    monkeypatch.setattr(hh, "_token_atual", lambda: "tok")
    monkeypatch.setattr(hh, "_rpc", lambda name, args, tok: next(respostas))

    class _R:
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def read(self): return b"\x00\x00\x00\x18ftypmp42rest"  # bytes[4:8]==ftyp
    monkeypatch.setattr(hh.urllib.request, "urlopen", lambda u, timeout=0: _R())

    out = hh.generate({"id": "a1"}, {"imagem_url": "https://x/a1.jpg", "aspect_ratio": "9:16"})
    assert out["mime"] == "video/mp4"
    assert out["meta"]["orquestrador"] == "http_direto"
    assert out["meta"]["job_id"] == "job42"
    assert out["bytes"][4:8] == b"ftyp"


def test_sem_imagem_falha(monkeypatch):
    monkeypatch.setattr(hh, "_token_atual", lambda: "tok")
    try:
        hh.generate({"id": "a1"}, {})
        assert False
    except RuntimeError as e:
        assert "imagem_url" in str(e)
