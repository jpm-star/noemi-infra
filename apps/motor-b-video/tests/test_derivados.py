"""Onda 1.5 quick-wins: endpoint /api/assets/{id}/derivar + os 6 derivados."""
import base64
import subprocess
import tempfile
import time
from pathlib import Path

from fastapi.testclient import TestClient

from main import app
from shared_core import storage

PNG_1PX = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="
)


def _dim(dados: bytes, ext="mp4") -> str:
    with tempfile.TemporaryDirectory() as t:
        f = Path(t) / f"o.{ext}"
        f.write_bytes(dados)
        r = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0",
                            "-show_entries", "stream=width,height", "-of", "csv=p=0", str(f)],
                           capture_output=True, text=True)
        return r.stdout.strip()


def _tem_audio(dados: bytes) -> bool:
    with tempfile.TemporaryDirectory() as t:
        f = Path(t) / "o.mp4"
        f.write_bytes(dados)
        r = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "a",
                            "-show_entries", "stream=index", "-of", "csv=p=0", str(f)],
                           capture_output=True, text=True)
        return bool(r.stdout.strip())


def _video_pronto(c: TestClient) -> str:
    """Roda um job até completar e devolve o asset_id do vídeo."""
    r = c.post("/api/upload", files={"file": ("imovel.png", PNG_1PX, "image/png")},
               data={"owner": "cliente-deriv"})
    asset_id = r.json()["asset_id"]
    r = c.post("/api/jobs", json={"asset_id": asset_id, "config": {
        "duration": 6, "marca": {"nome_exibicao": "Imobiliária Sol", "cor_acento": "#0E7C86"}}})
    job_id = r.json()["job_id"]
    prazo = time.time() + 40
    while time.time() < prazo:
        job = c.get(f"/api/jobs/{job_id}").json()
        if job["estado"] in ("completed", "failed"):
            break
        time.sleep(0.3)
    assert job["estado"] == "completed", job
    return job["asset_video"]


def _derivar(c: TestClient, video_id: str, corpo: dict) -> bytes:
    r = c.post(f"/api/assets/{video_id}/derivar", json=corpo)
    assert r.status_code == 200, r.text
    j = r.json()
    novo = storage.get_asset(j["asset_id"])
    assert novo["metadata"]["derivado_de"] == video_id
    return c.get(j["url"]).content


def test_derivar_todos_os_tipos():
    with TestClient(app) as c:
        vid = _video_pronto(c)

        # 1) proporção 1:1
        assert _dim(_derivar(c, vid, {"tipo": "proporcao", "aspect": "1:1"})) == "1080,1080"
        # 2) ficha (preço/endereço/código queimados)
        assert len(_derivar(c, vid, {"tipo": "ficha", "ficha": {
            "preco": "R$ 850.000", "endereco": "Rua das Flores, 123", "codigo": "REF-4821"}})) > 0
        # 3) capa (imagem jpeg)
        capa = _derivar(c, vid, {"tipo": "capa", "titulo": "Apartamento 3 quartos"})
        assert capa[:2] == b"\xff\xd8", "capa não é JPEG"
        # 4) teaser 15s vertical (9:16 nativo = 1080x1920)
        assert _dim(_derivar(c, vid, {"tipo": "teaser", "segundos": 15})) == "1080,1920"
        # 5) versão silenciosa (sem áudio)
        assert not _tem_audio(_derivar(c, vid, {"tipo": "silenciosa", "legenda": "Agende sua visita"}))
        # 6) loop curto
        assert len(_derivar(c, vid, {"tipo": "loop", "segundos": 4})) > 0


def test_derivar_tipo_invalido_422():
    with TestClient(app) as c:
        vid = _video_pronto(c)
        assert c.post(f"/api/assets/{vid}/derivar", json={"tipo": "explodir"}).status_code == 422


def test_derivar_asset_inexistente_404():
    with TestClient(app) as c:
        assert c.post("/api/assets/naoexiste/derivar", json={"tipo": "capa"}).status_code == 404
