"""Provider MOCK de vídeo (default, MOCK_MODE=True).

Gera um mp4 REAL de teste com ffmpeg (testsrc2 + tom de áudio), pra todo o
fluxo — worker, asset, front <video> — ser exercitado de verdade sem custo.
"""
from __future__ import annotations

import os
import subprocess
import tempfile
import time
from pathlib import Path

from shared_core.ai.cost import track_cost


@track_cost("mock")
def generate(asset: dict, config: dict) -> dict:
    duracao = int(config.get("duration", 4))
    # simula latência de geração pro front mostrar 'processing' (0 nos testes)
    time.sleep(float(os.environ.get("MOCK_DELAY_S", "2")))
    with tempfile.TemporaryDirectory() as tmp:
        saida = Path(tmp) / "teste.mp4"
        try:
            subprocess.run(
                ["ffmpeg", "-y", "-loglevel", "error",
                 "-f", "lavfi", "-i", f"testsrc2=duration={duracao}:size=1280x720:rate=24",
                 "-f", "lavfi", "-i", f"sine=frequency=440:duration={duracao}",
                 "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac",
                 "-movflags", "+faststart", str(saida)],
                check=True, capture_output=True, timeout=120,
            )
        except subprocess.CalledProcessError as e:
            # N1: sem isto, o job registra só "exit status 1" — inútil pra debugar
            linhas = (e.stderr or b"").decode("utf-8", "replace").strip().splitlines()
            raise RuntimeError(f"ffmpeg falhou: {linhas[-1][:300] if linhas else 'sem stderr'}") from e
        except subprocess.TimeoutExpired:
            raise RuntimeError("ffmpeg passou de 120s gerando o mock")
        dados = saida.read_bytes()
    return {
        "bytes": dados,
        "mime": "video/mp4",
        "modelo": "mock/testsrc2",
        "custo_creditos": 0,
        "meta": {"asset_origem": asset["id"], "duracao_s": duracao},
    }
