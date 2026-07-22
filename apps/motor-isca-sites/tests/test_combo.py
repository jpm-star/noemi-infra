"""Combo Prestador — onboarding ultra-simples (wizard 3 passos, 1 campo por tela)."""
import glob
import json
import os
import tempfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

pytest.importorskip("app.pipeline", reason="repo motor-site ausente")

from builder_web import app

CRED = {"usuario": "joaop", "senha": "senha-teste"}
JARGAO = ("cartucho", "cor de acento", "cor primária", "tier", "briefing", "nicho", "segmento")


@pytest.fixture(autouse=True)
def _meta_tmp(monkeypatch):
    monkeypatch.setenv("SITE_META_DIR", tempfile.mkdtemp(prefix="meta-"))


def _logar(c: TestClient):
    assert c.post("/studio/login", data=CRED, follow_redirects=False).status_code == 303


def test_combo_sem_login_bloqueia():
    with TestClient(app) as c:
        assert c.get("/studio/combo", follow_redirects=False).status_code == 303


def test_combo_uma_pergunta_por_tela_e_sem_jargao():
    with TestClient(app) as c:
        _logar(c)
        # passo 1: só o campo "nome"
        p1 = c.get("/studio/combo").text
        assert "PASSO 1 DE 3" in p1 and "Como chama o seu negócio" in p1
        assert p1.count("<input name=") == 1, "mais de um campo visível na tela"
        # passo 2 e 3 avançam um campo por vez
        p2 = c.post("/studio/combo", data={"passo": "servico", "nome": "Eletricista do João"}).text
        assert "PASSO 2 DE 3" in p2 and "O que você faz" in p2
        p3 = c.post("/studio/combo", data={"passo": "whatsapp", "nome": "Eletricista do João",
                                           "servico": "eletricista"}).text
        assert "PASSO 3 DE 3" in p3 and "WhatsApp" in p3
        # zero jargão em nenhuma das telas
        for tela in (p1, p2, p3):
            baixo = tela.lower()
            for termo in JARGAO:
                assert termo not in baixo, f"jargão vazou: {termo!r}"


def test_combo_final_gera_site_e_noemi_basica():
    with TestClient(app) as c:
        _logar(c)
        r = c.post("/studio/combo", data={
            "passo": "pronto", "nome": "Eletricista do João",
            "servico": "eletricista", "whatsapp": "66999998888"})
        assert r.status_code == 200
        assert "Pronto, Eletricista do João" in r.text and "go.noemi.digital" in r.text
        for termo in JARGAO:
            assert termo not in r.text.lower()

        # site real no disco
        sites = glob.glob(os.path.join(os.environ["SITE_OUT_DIR"], "*", "index.html"))
        assert sites, "site não foi publicado"

        # config da Noemi Básica salva (o cliente nunca a vê nomeada)
        carts = glob.glob(os.path.join(os.environ["SITE_META_DIR"], "*", "cartucho.json"))
        assert carts, "config da Noemi Básica não foi salva"
        cart = json.loads(Path(carts[0]).read_text(encoding="utf-8"))
        assert cart["plano"] == "noemi_basica"
        assert cart["nome_empresa"] == "Eletricista do João"
        assert cart["vertical"] == "eletricista" and cart["whatsapp_dono"] == "66999998888"
        assert "Eletricista do João" in cart["persona"]


def test_combo_dado_faltando_recomeça_sem_quebrar():
    with TestClient(app) as c:
        _logar(c)
        # pula direto pro "pronto" sem preencher → volta pro passo 1, não explode
        r = c.post("/studio/combo", data={"passo": "pronto", "nome": "", "servico": "", "whatsapp": ""})
        assert r.status_code == 200 and "PASSO 1 DE 3" in r.text
