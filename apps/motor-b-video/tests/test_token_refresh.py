"""Auto-refresh do token OAuth do Higgsfield (Fase A+): o Motor B renova sozinho
usando o refresh_token, sem esperar a expiração derrubar o modo real."""
import io
import json
import time

from shared_core.ai.providers import higgsfield_video as hv


class _Resp(io.BytesIO):
    def __enter__(self): return self
    def __exit__(self, *a): return False


def _fake_urlopen(payload):
    def _open(req, timeout=0):
        _open.corpo = req.data  # captura o body enviado p/ assertivas
        return _Resp(json.dumps(payload).encode())
    return _open


def test_refresh_quando_cache_vencido(tmp_path, monkeypatch):
    monkeypatch.setenv("NOEMI_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("HIGGSFIELD_CLIENT_ID", "cid123")
    monkeypatch.setenv("HIGGSFIELD_REFRESH_TOKEN", "R1")
    monkeypatch.setenv("HIGGSFIELD_MCP_TOKEN", "ACCESS_VELHO")
    fake = _fake_urlopen({"access_token": "ACCESS_NOVO", "refresh_token": "R2", "expires_in": 3600})
    monkeypatch.setattr(hv.urllib.request, "urlopen", fake)

    tok = hv._token_atual(forcar=True)
    assert tok == "ACCESS_NOVO"
    body = fake.corpo.decode()
    assert "grant_type=refresh_token" in body and "refresh_token=R1" in body
    # persistiu o refresh rotacionado (R2), não o seed
    cache = json.loads((tmp_path / "higgsfield_token.json").read_text())
    assert cache["refresh_token"] == "R2" and cache["access_token"] == "ACCESS_NOVO"


def test_cache_valido_nao_renova(tmp_path, monkeypatch):
    monkeypatch.setenv("NOEMI_DATA_DIR", str(tmp_path))
    (tmp_path / "higgsfield_token.json").write_text(json.dumps({
        "access_token": "AINDA_VALE", "refresh_token": "R9",
        "client_id": "cid", "expires_at": time.time() + 9999}))

    def _boom(*a, **k): raise AssertionError("não deveria bater na rede com cache válido")
    monkeypatch.setattr(hv.urllib.request, "urlopen", _boom)
    assert hv._token_atual() == "AINDA_VALE"


def test_sem_token_nem_refresh_falha(tmp_path, monkeypatch):
    monkeypatch.setenv("NOEMI_DATA_DIR", str(tmp_path))
    for v in ("HIGGSFIELD_MCP_TOKEN", "HIGGSFIELD_REFRESH_TOKEN", "HIGGSFIELD_CLIENT_ID"):
        monkeypatch.delenv(v, raising=False)
    try:
        hv._token_atual()
        assert False, "deveria falhar sem token nem refresh"
    except RuntimeError as e:
        assert "ausente" in str(e)
