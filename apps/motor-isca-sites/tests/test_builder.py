"""Site Studio de produção — auth + geração + histórico (rotas sob /studio)."""
import glob
import os

import pytest
from fastapi.testclient import TestClient

pytest.importorskip("app.pipeline", reason="repo motor-site ausente")  # ponte externa

from builder_web import app

CRED = {"usuario": "joaop", "senha": "senha-teste"}


def _logar(c: TestClient):
    r = c.post("/studio/login", data=CRED, follow_redirects=False)
    assert r.status_code == 303  # cookie fica no jar do client


def test_sem_login_bloqueia():
    with TestClient(app) as c:
        r = c.get("/studio", follow_redirects=False)
        assert r.status_code == 303 and r.headers["location"] == "/studio/login"
        g = c.post("/studio/gerar", data={"nome": "X", "nicho": "y", "whatsapp": "55"},
                   follow_redirects=False)
        assert g.status_code == 303  # gerar também protegido


def test_senha_errada_401():
    with TestClient(app) as c:
        r = c.post("/studio/login", data={"usuario": "joaop", "senha": "errada"},
                   follow_redirects=False)
        assert r.status_code == 401


def test_login_geracao_e_historico():
    with TestClient(app) as c:
        _logar(c)
        assert c.get("/studio").status_code == 200  # autenticado pelo cookie
        g = c.post("/studio/gerar", data={
            "nome": "Studio Teste", "nicho": "contabilidade",
            "whatsapp": "5566999998888", "diferenciais": "20 anos"})
        assert g.status_code == 200 and "Publicado" in g.text and "go.noemi.digital" in g.text
        # site real no disco + histórico na tela
        assert glob.glob(os.path.join(os.environ["SITE_OUT_DIR"], "*", "index.html"))
        assert "Studio Teste" in c.get("/studio").text


def test_logout_desloga():
    with TestClient(app) as c:
        _logar(c)
        assert c.get("/studio", follow_redirects=False).status_code == 200
        c.get("/studio/logout", follow_redirects=False)
        assert c.get("/studio", follow_redirects=False).status_code == 303  # deslogado


def test_health_publico():
    with TestClient(app) as c:
        assert c.get("/studio/health").json()["ok"] is True
