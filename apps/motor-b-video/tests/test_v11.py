"""Motor B v1.1 — classificação, templates, prompt builder, dashboard."""
import time

from fastapi.testclient import TestClient

import jobs
import prompt_builder
import templates
from main import app
from shared_core import storage
from shared_core.ai import classificacao

PNG = bytes.fromhex(
    "89504e470d0a1a0a0000000d494844520000000100000001010300000025db56"
    "ca00000003504c5445000000a77a3dda0000000149444154789c6360000000020001"
    "e221bc330000000049454e44ae426082")


# --- 1. classificação (mock determinística) ---
def test_classificacao_por_padrao_e_tipo():
    assert classificacao.classificar({"descricao": "cobertura de luxo", "preco": "R$ 2.500.000"})["padrao"] == "luxo"
    assert classificacao.classificar({"descricao": "apartamento na planta, lançamento"})["padrao"] == "lancamento"
    assert classificacao.classificar({"descricao": "sala comercial no centro"})["padrao"] == "comercial"
    assert classificacao.classificar({"descricao": "sítio com 5 alqueires"})["padrao"] == "rural"
    assert classificacao.classificar({"descricao": "casa 2 quartos"}) ["tipo"] == "casa"
    econ = classificacao.classificar({"descricao": "apê simples"})
    assert econ["padrao"] == "economico" and econ["cta"] is True and econ["fonte"] == "mock"


# --- 2. templates + escolha automática/manual ---
def test_quatro_templates_e_escolha():
    assert set(templates.TEMPLATES) == {"alto_padrao", "economico", "lancamento", "comercial", "obra"}
    assert templates.escolher_template({"padrao": "luxo"})["id"] == "alto_padrao"
    assert templates.escolher_template({"padrao": "comercial"})["id"] == "comercial"
    # troca manual vence a classificação
    assert templates.escolher_template({"padrao": "luxo"}, manual="economico")["id"] == "economico"
    # manual inválido → volta pro automático
    assert templates.escolher_template({"padrao": "luxo"}, manual="inexistente")["id"] == "alto_padrao"


# --- 3. prompt builder: específico, não genérico ---
def test_prompt_builder_especifico_por_segmento():
    clas = {"padrao": "luxo", "tipo": "casa", "tom": "sofisticado", "cta": False}
    tpl = templates.escolher_template(clas)
    p = prompt_builder.construir_prompt(clas, tpl, {"descricao": "vista para o mar", "duration": 10})
    assert "casa" in p["prompt"] and "golden hour" in p["prompt"] and "vista para o mar" in p["prompt"]
    assert p["duration"] == 10 and p["aspect_ratio"] == "16:9" and p["template_id"] == "alto_padrao"
    # dois padrões diferentes → prompts diferentes (não genérico)
    econ = prompt_builder.construir_prompt({"padrao": "economico", "tipo": "apartamento", "tom": "direto", "cta": True},
                                           templates.escolher_template({"padrao": "economico"}), {})
    assert econ["prompt"] != p["prompt"] and "ação" in econ["prompt"].lower()


# --- 4. dashboard: 4 indicadores + aprovação ---
def _upload(c):
    return c.post("/api/upload", files={"file": ("i.png", PNG, "image/png")}).json()["asset_id"]


def _rodar(c, asset_id, config=None):
    jid = c.post("/api/jobs", json={"asset_id": asset_id, "config": config or {}}).json()["job_id"]
    prazo = time.time() + 30
    while time.time() < prazo:
        if c.get(f"/api/jobs/{jid}").json()["estado"] in ("completed", "failed"):
            break
        time.sleep(0.2)
    return jid


def test_pipeline_v11_classifica_e_dashboard():
    with TestClient(app) as c:
        aid = _upload(c)
        jid = _rodar(c, aid, {"descricao": "cobertura de luxo", "preco": "3000000"})
        job = jobs.obter(jid)
        assert job["estado"] == "completed"
        # classificação + template + prompt construído ficaram no config do job
        assert job["config"]["classificacao"]["padrao"] == "luxo"
        assert job["config"]["template"] == "alto_padrao"
        assert "Vídeo imobiliário" in job["config"]["prompt"]

        m = c.get("/api/dashboard").json()
        assert m["videos_produzidos"] >= 1 and m["tempo_medio_s"] is not None
        assert m["taxa_aprovacao"] is None  # nada avaliado ainda

        # aprovação move a taxa
        assert c.post(f"/api/jobs/{jid}/aprovar", json={"aprovado": True}).status_code == 200
        m2 = c.get("/api/dashboard").json()
        assert m2["taxa_aprovacao"] == 1.0 and m2["avaliados"] == 1
        assert c.get("/dashboard").status_code == 200  # página no ar


def test_aprovar_job_inexistente_404():
    with TestClient(app) as c:
        assert c.post("/api/jobs/nao-existe/aprovar").status_code == 404
