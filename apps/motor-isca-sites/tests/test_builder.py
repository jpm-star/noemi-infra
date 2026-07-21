"""Frontend de teste do Site Builder — dirige o pipeline real (template/local)."""
import glob
import os

import pytest
from fastapi.testclient import TestClient

pytest.importorskip("app.pipeline", reason="repo motor-site ausente")  # ponte externa

from builder_web import app


def test_form_carrega():
    with TestClient(app) as c:
        r = c.get("/")
        assert r.status_code == 200 and "Site Builder" in r.text


def test_gera_e_publica_site_real():
    with TestClient(app) as c:
        r = c.post("/gerar", data={
            "nome": "Contábil Teste", "nicho": "contabilidade",
            "whatsapp": "5566999998888", "diferenciais": "20 anos\nAtendimento em 1h",
            "publico": "pequenas empresas", "cor": "#1d4ed8"})
        assert r.status_code == 200
        assert "Publicado" in r.text and "go.noemi.digital" in r.text
        # HTML real gerado no disco
        idx = glob.glob(os.path.join(os.environ["SITE_OUT_DIR"], "*", "index.html"))
        assert idx, "nenhum index.html publicado"
        assert "Contábil Teste" in open(idx[0], encoding="utf-8").read()


def test_health():
    with TestClient(app) as c:
        corpo = c.get("/health").json()
        assert corpo["gerador"] == "template" and corpo["deploy"] == "local"
