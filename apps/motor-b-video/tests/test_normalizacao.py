"""Normalização da mídia de entrada no estado uploading."""
import subprocess
import tempfile
from pathlib import Path

from fastapi.testclient import TestClient

import jobs
import media
from main import app
from shared_core import storage


def _png(size: str = "2000x2000") -> bytes:
    with tempfile.TemporaryDirectory() as t:
        out = Path(t) / "x.png"
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi",
                        "-i", f"testsrc2=size={size}:duration=1:rate=1",
                        "-frames:v", "1", str(out)], check=True)
        return out.read_bytes()


def _roda_job(c: TestClient, asset_id: str) -> dict:
    job_id = c.post("/api/jobs", json={"asset_id": asset_id, "config": {"duration": 1}}).json()["job_id"]
    import time
    prazo = time.time() + 30
    while time.time() < prazo:
        job = c.get(f"/api/jobs/{job_id}").json()
        if job["estado"] in ("completed", "failed"):
            return job
        time.sleep(0.2)
    raise AssertionError("job não terminou")


def test_imagem_grande_e_normalizada_in_place():
    grande = _png("2000x2000")
    with TestClient(app) as c:
        r = c.post("/api/upload", files={"file": ("foto.png", grande, "image/png")})
        asset_id = r.json()["asset_id"]
        assert _roda_job(c, asset_id)["estado"] == "completed"
        origem = storage.get_asset(asset_id)
        # mesmo id (in-place), agora JPEG normalizado e MENOR
        assert origem["mime"] == "image/jpeg"
        assert origem["metadata"]["normalizado"] is True
        assert origem["metadata"]["bytes_norm"] < origem["metadata"]["bytes_original"]
        # lado maior capado em 1080
        with tempfile.TemporaryDirectory() as t:
            f = Path(t) / "o.jpg"
            f.write_bytes(storage.asset_file(origem).read_bytes())
            dims = subprocess.run(
                ["ffprobe", "-v", "error", "-select_streams", "v:0",
                 "-show_entries", "stream=width,height", "-of", "csv=p=0", str(f)],
                capture_output=True, text=True, check=True).stdout.strip()
        w, h = (int(x) for x in dims.split(","))
        assert max(w, h) == 1080, f"esperava lado maior 1080, veio {dims}"


def test_bytes_invalidos_degradam_sem_quebrar_o_job():
    with TestClient(app) as c:
        # mime válido, conteúdo que o ffmpeg não decodifica
        r = c.post("/api/upload", files={"file": ("x.png", b"\x89PNG\r\n" + b"lixo" * 20, "image/png")})
        asset_id = r.json()["asset_id"]
        job = _roda_job(c, asset_id)
        assert job["estado"] == "completed", "normalização é best-effort — não pode falhar o job"
        origem = storage.get_asset(asset_id)
        assert origem["metadata"]["normalizado"] is False
        assert origem["metadata"]["normalizacao_erro"]


def test_retry_nao_re_normaliza():
    asset = storage.create_asset("t", jobs.PRODUTO, "image/jpeg", _png("100x100"),
                                 metadata={"normalizado": True, "bytes_norm": 1})
    import worker
    resultado = worker._normalizar_origem(storage.get_asset(asset["id"]), "job-x")
    assert resultado["metadata"]["bytes_norm"] == 1  # inalterado — não re-rodou ffmpeg


def test_normalizar_recusa_mime_nao_midia():
    try:
        media.normalizar(b"abc", "application/pdf")
        raise AssertionError("deveria recusar pdf")
    except media.NormalizacaoErro as e:
        assert e.nivel == "tipo"
