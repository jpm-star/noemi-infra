"""Motores (Motor B + arbitragem): o contrato de honestidade, sem rede.

O que precisa ficar travado aqui é UM comportamento: fonte fora nunca pode virar
zero, e token vencido COM refresh nunca pode virar "bloqueado" (o token vence a
cada 24h por design — alarmar nisso seria alarme falso diário).
"""
import importlib.util
import json
import sys
import time
from pathlib import Path

_APP = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_APP))
import motores


def _main():
    """O `main` DESTE app, carregado por caminho.

    `apps/motor-b-video` também tem um `main.py`, e os dois entram no sys.path.
    Rodando a suíte inteira, quem chegasse primeiro ocupava `sys.modules['main']`
    e o outro recebia o app errado — o teste passava sozinho e falhava em conjunto.
    """
    spec = importlib.util.spec_from_file_location("painel_main", _APP / "main.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _token(tmp_path, **campos) -> str:
    p = tmp_path / "higgsfield_token.json"
    p.write_text(json.dumps({"access_token": "x", "client_id": "c", **campos}))
    return str(p)


def test_credencial_valida(tmp_path, monkeypatch):
    monkeypatch.setattr(motores, "_TOKEN_JSON",
                        _token(tmp_path, expires_at=time.time() + 7200, refresh_token="r"))
    assert motores.credencial()["estado"] == "valido"


def test_vencido_com_refresh_nao_e_bloqueio(tmp_path, monkeypatch):
    # o caso do dia a dia: ninguém gerou vídeo desde ontem
    monkeypatch.setattr(motores, "_TOKEN_JSON",
                        _token(tmp_path, expires_at=time.time() - 90000, refresh_token="r"))
    assert motores.credencial()["estado"] == "renovavel"


def test_vencido_sem_refresh_e_bloqueio(tmp_path, monkeypatch):
    monkeypatch.setattr(motores, "_TOKEN_JSON",
                        _token(tmp_path, expires_at=time.time() - 90000))
    assert motores.credencial()["estado"] == "bloqueado"


def test_sem_arquivo_e_ausente(tmp_path, monkeypatch):
    monkeypatch.setattr(motores, "_TOKEN_JSON", str(tmp_path / "nao-existe.json"))
    assert motores.credencial()["estado"] == "ausente"


def test_banco_fora_nao_vira_zero(monkeypatch):
    """`_contagens` devolvendo None (não consegui perguntar) tem que chegar na
    camada como "indisponivel" — nunca como um punhado de zeros."""
    monkeypatch.setattr(motores, "_contagens", lambda *a: None)
    c = motores._compras()
    assert c["estado"] == "indisponivel"
    assert c.get("compradores") is None


def test_cache_nao_repete_consulta(monkeypatch):
    """O TTL existe pra não martelar `docker exec` a cada poll do painel."""
    motores._cache.clear()
    chamadas = []
    v = motores._memo("x", lambda: chamadas.append(1) or {"n": len(chamadas)})
    assert motores._memo("x", lambda: chamadas.append(1)) == v
    assert len(chamadas) == 1


def test_job_id_estranho_nao_vira_url(monkeypatch):
    """`/api/jobs/{id}` monta URL por interpolação: id com barra sairia da rota."""
    from fastapi.testclient import TestClient
    c = TestClient(_main().app)
    # 400 = barrado pela validação; 404/405 = o roteador nem chegou no handler.
    # Qualquer um serve: o que não pode é virar uma chamada montada pro :8010.
    for ruim in ["../../health", "a/b", "id com espaço", ""]:
        r = c.get(f"/api/motor-b/jobs/{ruim}")
        assert r.status_code in (400, 404, 405), f"{ruim!r} passou com {r.status_code}"


def test_upload_recusa_tipo_errado():
    from fastapi.testclient import TestClient
    c = TestClient(_main().app)
    r = c.post("/api/motor-b/upload", files={"file": ("x.exe", b"MZ", "application/x-msdownload")})
    assert r.status_code == 415 and "tipo não aceito" in r.json()["detail"]


def test_banco_vazio_e_diferente_de_banco_fora(monkeypatch):
    """Schema criado e 0 linhas é um FATO ("nunca rodou"), não uma falha de leitura."""
    monkeypatch.setattr(motores, "_contagens", lambda *a: {"ofertas": 0, "cotacoes": 0})
    monkeypatch.setattr(motores, "_json", lambda *a, **k: None)   # serviço fora
    ex = motores._exodia()
    assert ex["estado"] == "schema pronto, sem dado"
    assert ex["total_linhas"] == 0 and ex["tabelas_criadas"] == 2
