"""Auto QA técnico do vídeo gerado (Motor B — item 6).

Checagem LEVE antes de marcar o job como concluído: arquivo não-vazio, mp4
decodificável com stream de vídeo, resolução válida, duração plausível. NÃO é
análise artística — é o portão que impede publicar um vídeo corrompido/truncado
(ex.: download do Higgsfield cortado no modo real). Reprovou → o job falha/retry
em vez de entregar lixo ao cliente.

ponytail: ffprobe (já presente), sem lib nova. Duração é checagem SOFT (tolerância
generosa) pra não reprovar por arredondamento; o que pega de verdade é vazio/
corrompido/sem-vídeo.
"""
from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path

_MIN_BYTES = 1024  # abaixo disso é claramente truncado/vazio


def verificar_video(dados: bytes, *, duracao_esperada: float | None = None,
                    tolerancia: float = 1.5) -> tuple[bool, str]:
    """(ok, motivo). Reprova em: vazio, sem stream de vídeo, resolução inválida,
    duração absurdamente fora do esperado. Nunca lança."""
    if not dados or len(dados) < _MIN_BYTES:
        return False, f"arquivo vazio ou truncado ({len(dados or b'')} bytes)"
    with tempfile.TemporaryDirectory() as t:
        f = Path(t) / "v.mp4"
        f.write_bytes(dados)
        try:
            r = subprocess.run(
                ["ffprobe", "-v", "error", "-select_streams", "v:0",
                 "-show_entries", "stream=width,height:format=duration",
                 "-of", "default=noprint_wrappers=1:nokey=1", str(f)],
                capture_output=True, text=True, timeout=30)
        except (subprocess.TimeoutExpired, FileNotFoundError) as e:
            return False, f"ffprobe não rodou: {type(e).__name__}"
    linhas = [x.strip() for x in r.stdout.splitlines() if x.strip()]
    if r.returncode != 0 or len(linhas) < 2:
        return False, "arquivo não decodifica / sem stream de vídeo"
    try:
        w, h = int(linhas[0]), int(linhas[1])
    except (ValueError, IndexError):
        return False, "resolução ilegível"
    if w <= 0 or h <= 0:
        return False, f"resolução inválida {w}x{h}"
    dur = None
    if len(linhas) >= 3:
        try:
            dur = float(linhas[2])
        except ValueError:
            dur = None
    if dur is not None and dur <= 0:
        return False, "duração zero"
    if duracao_esperada and dur is not None:
        margem = max(tolerancia, duracao_esperada * 0.5)  # tolerância generosa
        if abs(dur - duracao_esperada) > margem:
            return False, f"duração {dur:.1f}s fora do esperado ~{duracao_esperada:.0f}s"
    return True, f"ok {w}x{h} {dur or '?'}s"


if __name__ == "__main__":  # self-check: aprova mp4 real, reprova lixo
    with tempfile.TemporaryDirectory() as t:
        bom = Path(t) / "bom.mp4"
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi",
                        "-i", "testsrc2=size=640x360:duration=3:rate=24",
                        "-c:v", "libx264", "-pix_fmt", "yuv420p", str(bom)], check=True)
        ok, m = verificar_video(bom.read_bytes(), duracao_esperada=3)
        assert ok, m
        assert not verificar_video(b"")[0]              # vazio
        assert not verificar_video(b"x" * 5000)[0]      # bytes que não são vídeo
        assert not verificar_video(bom.read_bytes(), duracao_esperada=60)[0]  # 3s vs 60s
        print("qa OK —", m)
