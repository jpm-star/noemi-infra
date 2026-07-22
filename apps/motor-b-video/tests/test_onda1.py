"""Onda 1: Brand Kit + Auto Director + Pós-processamento (marca no vídeo)."""
import base64
import json
import time
from pathlib import Path

from fastapi.testclient import TestClient

import brand
import prompt_builder
import templates
from main import app
from shared_core import storage

PNG_1PX = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="
)


# -- Brand Kit --------------------------------------------------------------
def test_brand_default_neutro():
    k = brand.brand_kit("qualquer", None)
    assert k["nome"] == "Noemi" and k["fonte"] == "default"
    assert k["cor_acento"] == "#7c5cff" and k["watermark"] == "Noemi"


def test_brand_config_marca_vence():
    k = brand.brand_kit("x", {"marca": {"nome_exibicao": "Ateliê Pedra", "cor_acento": "0E7C86"}})
    assert k["nome"] == "Ateliê Pedra" and k["cor_acento"] == "#0E7C86"
    assert k["fonte"] == "config" and k["watermark"] == "Ateliê Pedra"


def test_brand_puxa_do_cartucho(tmp_path, monkeypatch):
    cart = {"nome_empresa": "Sorriso Vivo", "whatsapp_dono": "5511999",
            "marca": {"nome_exibicao": "Sorriso Vivo Odontologia", "cor_acento": "#0E7C86"}}
    (tmp_path / "clinica.json").write_text(json.dumps(cart), encoding="utf-8")
    monkeypatch.setenv("NOEMI_CARTUCHOS_DIR", str(tmp_path))
    k = brand.brand_kit("x", {"cartucho": "clinica"})
    assert k["nome"] == "Sorriso Vivo Odontologia" and k["cor_acento"] == "#0E7C86"
    assert k["cta_contato"] == "5511999" and k["fonte"] == "cartucho"


def test_brand_cartucho_ausente_cai_no_default(monkeypatch):
    monkeypatch.setenv("NOEMI_CARTUCHOS_DIR", "/nao/existe")
    assert brand.brand_kit("x", {"cartucho": "fantasma"})["fonte"] == "default"


def test_brand_bloqueia_path_traversal(tmp_path, monkeypatch):
    monkeypatch.setenv("NOEMI_CARTUCHOS_DIR", str(tmp_path))
    # nome com ../ é saneado, não escapa do dir
    assert brand.brand_kit("x", {"cartucho": "../../etc/passwd"})["fonte"] == "default"


# -- Auto Director ----------------------------------------------------------
def test_movimento_por_comodo_vence():
    mov = prompt_builder.escolher_movimento({"padrao": "luxo"}, {"comodo": "cozinha"})
    assert "dolly" in mov and "bancada" in mov


def test_movimento_cai_na_classificacao_sem_comodo():
    mov = prompt_builder.escolher_movimento({"padrao": "lancamento"}, {})
    assert "dramático" in mov


def test_prompt_inclui_movimento_e_cta_de_marca():
    clas = {"padrao": "economico", "tipo": "casa", "cta": True}
    tpl = templates.escolher_template(clas)
    kit = brand.brand_kit("x", {"marca": {"nome_exibicao": "Imobiliária Sol"}})
    p = prompt_builder.construir_prompt(clas, tpl, {"comodo": "fachada"}, brand=kit)
    assert "Movimento de câmera" in p["prompt"] and "fachada" in p["prompt"]
    assert "Imobiliária Sol" in p["prompt"]  # CTA usa o nome da marca
    assert p["movimento"]


# -- E2E: marca aplicada no vídeo final -------------------------------------
def test_e2e_video_sai_com_pos_processamento():
    with TestClient(app) as c:
        r = c.post("/api/upload", files={"file": ("imovel.png", PNG_1PX, "image/png")},
                   data={"owner": "cliente-marca"})
        asset_id = r.json()["asset_id"]
        # economico → template 9:16 → reframe deve rodar; marca custom → watermark
        r = c.post("/api/jobs", json={"asset_id": asset_id, "config": {
            "duration": 1, "marca": {"nome_exibicao": "Imobiliária Sol", "cor_acento": "#0E7C86"}}})
        job_id = r.json()["job_id"]

        prazo, job = time.time() + 40, None
        while time.time() < prazo:
            job = c.get(f"/api/jobs/{job_id}").json()
            if job["estado"] in ("completed", "failed"):
                break
            time.sleep(0.2)
        assert job and job["estado"] == "completed", f"{job and job['estado']}: {job and job.get('erro')}"

        video = storage.get_asset(job["asset_video"])
        aplicado = video["metadata"]["pos"]["aplicado"]
        assert "reframe:9:16" in aplicado, aplicado
        assert "watermark" in aplicado and "legenda" in aplicado, aplicado
