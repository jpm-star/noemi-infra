"""Item 8: pacote de entrega — MP4 + copy + hashtags + CTA num payload só."""
import base64
import time

from fastapi.testclient import TestClient

from main import app

PNG_1PX = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="
)


def _job_completo(c: TestClient, config: dict) -> dict:
    aid = c.post("/api/upload", files={"file": ("i.png", PNG_1PX, "image/png")},
                 data={"owner": "teste-pacote"}).json()["asset_id"]
    jid = c.post("/api/jobs", json={"asset_id": aid, "config": config}).json()["job_id"]
    prazo, job = time.time() + 30, None
    while time.time() < prazo:
        job = c.get(f"/api/jobs/{jid}").json()
        if job["estado"] in ("completed", "failed"):
            break
        time.sleep(0.2)
    assert job and job["estado"] == "completed", job
    return job


def test_pacote_entrega_payload_unico():
    with TestClient(app) as c:
        job = _job_completo(c, {"duration": 1, "descricao": "apartamento 3 quartos vista mar",
                                "codigo": "AP-12", "preco": "R$ 850 mil", "bairro": "Cambuí"})
        aid = job["asset_video"]
        r = c.get(f"/api/assets/{aid}/pacote")
        assert r.status_code == 200, r.text
        p = r.json()
        assert p["video_url"] == f"/api/assets/{aid}/file"
        assert p["titulo"] and isinstance(p["hashtags"], list) and len(p["hashtags"]) >= 8
        assert "AP-12" in p["cta"] and "wa.me" not in p["cta"]  # sem whatsapp no cartucho → sem link
        assert p["titulo"] in p["copy"] and "AP-12" in p["copy"]  # caption pronta cita o código
        assert p["ficha"]["codigo"] == "AP-12" and p["ficha"]["preco"] == "R$ 850 mil"
        # o MP4 do pacote realmente baixa
        assert c.get(p["video_url"]).content[4:8] == b"ftyp"


def test_pacote_404_para_nao_video():
    with TestClient(app) as c:
        assert c.get("/api/assets/inexistente/pacote").status_code == 404
