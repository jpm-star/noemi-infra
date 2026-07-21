"""E2E com mock: upload → fila → estados → vídeo de teste baixável."""
import base64
import time

from fastapi.testclient import TestClient

import jobs
from main import app
from shared_core import storage

PNG_1PX = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="
)


def _upload(c: TestClient) -> str:
    r = c.post("/api/upload", files={"file": ("imovel.png", PNG_1PX, "image/png")},
               data={"owner": "teste-e2e"})
    assert r.status_code == 200, r.text
    return r.json()["asset_id"]


def test_fluxo_completo_upload_ate_video():
    with TestClient(app) as c:  # lifespan liga o worker
        asset_id = _upload(c)
        r = c.post("/api/jobs", json={"asset_id": asset_id, "config": {"duration": 1}})
        assert r.status_code == 200
        job_id = r.json()["job_id"]

        prazo, job = time.time() + 30, None
        while time.time() < prazo:
            job = c.get(f"/api/jobs/{job_id}").json()
            if job["estado"] in ("completed", "failed"):
                break
            time.sleep(0.2)
        assert job and job["estado"] == "completed", f"job terminou em {job and job['estado']}: {job and job['erro']}"
        assert job["asset_video"], "job completed sem asset de vídeo vinculado"

        # vínculo job → origem → vídeo persistido
        video = storage.get_asset(job["asset_video"])
        assert video["metadata"]["asset_origem"] == asset_id
        assert video["metadata"]["job"] == job_id

        r = c.get(job["video_url"])
        assert r.status_code == 200
        assert r.headers["content-type"].startswith("video/mp4")
        assert r.content[4:8] == b"ftyp", "resposta não é mp4 de verdade"

        assert any(j["id"] == job_id for j in c.get("/api/jobs").json())
        assert c.get("/").status_code == 200  # front no ar


def test_upload_recusa_mime_invalido():
    with TestClient(app) as c:
        r = c.post("/api/upload", files={"file": ("nota.txt", b"oi", "text/plain")})
        assert r.status_code == 415


def test_upload_recusa_vazio():
    with TestClient(app) as c:
        r = c.post("/api/upload", files={"file": ("v.png", b"", "image/png")})
        assert r.status_code == 400


def test_job_para_asset_inexistente_da_404():
    with TestClient(app) as c:
        assert c.post("/api/jobs", json={"asset_id": "nao-existe"}).status_code == 404


def test_cancelamento_e_guarda_de_estado_terminal():
    asset = storage.create_asset("t", jobs.PRODUTO, "image/png", PNG_1PX)
    job = jobs.criar(asset["id"])
    assert jobs.atualizar(job["id"], "cancelled") is True
    # terminal não é sobrescrito: worker chegando atrasado não ressuscita o job
    assert jobs.atualizar(job["id"], "processing") is False
    assert jobs.obter(job["id"])["estado"] == "cancelled"


def test_health():
    with TestClient(app) as c:
        corpo = c.get("/health").json()
        assert corpo == {"ok": True, "mock": True}
