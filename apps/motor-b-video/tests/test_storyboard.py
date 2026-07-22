"""Storyboarding: planejamento de cenas + E2E do walkthrough (item 4)."""
import base64
import subprocess
import tempfile
import time
from pathlib import Path

from fastapi.testclient import TestClient

import storyboard
from main import app
from shared_core import storage

PNG_1PX = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="
)


# -- planejamento (puro) ----------------------------------------------------
def test_plano_default_fachada_ate_suite():
    p = storyboard.planejar_cenas({"storyboard": True}, "a1")
    assert [c["comodo"] for c in p] == ["fachada", "sala", "cozinha", "suite"]
    assert all(c["asset_id"] == "a1" for c in p)


def test_cenas_explicitas_vencem_o_default():
    p = storyboard.planejar_cenas(
        {"cenas": [{"comodo": "loft", "asset_id": "a2"}, {"comodo": "terraço"}]}, "a1")
    assert [c["comodo"] for c in p] == ["loft", "terraço"]
    assert p[0]["asset_id"] == "a2" and p[1]["asset_id"] == "a1"  # sem asset → origem


def test_eh_storyboard_detecta():
    assert storyboard.eh_storyboard({"storyboard": True})
    assert storyboard.eh_storyboard({"cenas": [{"comodo": "sala"}]})
    assert not storyboard.eh_storyboard({})
    assert not storyboard.eh_storyboard({"cenas": []})


# -- E2E: walkthrough completo ----------------------------------------------
def _dur(dados: bytes) -> float:
    with tempfile.TemporaryDirectory() as t:
        f = Path(t) / "v.mp4"
        f.write_bytes(dados)
        r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                            "-of", "csv=p=0", str(f)], capture_output=True, text=True)
        return float(r.stdout.strip())


def test_e2e_walkthrough_4_cenas_encadeadas():
    with TestClient(app) as c:
        r = c.post("/api/upload", files={"file": ("imovel.png", PNG_1PX, "image/png")},
                   data={"owner": "cliente-walk"})
        asset_id = r.json()["asset_id"]
        r = c.post("/api/jobs", json={"asset_id": asset_id, "config": {
            "storyboard": True, "duracao_cena": 2,
            "marca": {"nome_exibicao": "Imobiliária Sol", "cor_acento": "#0E7C86"}}})
        job_id = r.json()["job_id"]

        prazo, job = time.time() + 90, None
        while time.time() < prazo:
            job = c.get(f"/api/jobs/{job_id}").json()
            if job["estado"] in ("completed", "failed"):
                break
            time.sleep(0.3)
        assert job and job["estado"] == "completed", f"{job and job['estado']}: {job and job.get('erro')}"

        video = storage.get_asset(job["asset_video"])
        md = video["metadata"]
        assert md["storyboard"] is True and md["n_cenas"] == 4, md
        assert md["cenas"] == ["fachada", "sala", "cozinha", "suite"], md
        # marca aplicada no walkthrough final
        assert "watermark" in md["pos"]["aplicado"] and "legenda" in md["pos"]["aplicado"]

        # o vídeo servido é a concatenação real das 4 cenas (~4×2s), não 1 clipe
        r = c.get(job["video_url"])
        assert r.status_code == 200 and r.content[4:8] == b"ftyp"
        dur = _dur(r.content)
        assert dur >= 6.5, f"walkthrough curto demais ({dur}s) — cenas não concatenaram"
