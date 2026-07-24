"""Normalização da mídia de ENTRADA via FFmpeg (motor-b-video).

Imagem → JPEG ≤1080 (lado maior); vídeo → H.264 720p / AAC / faststart.
Objetivo: resolução/codec/bitrate consistentes, independente do que o cliente
mandar — encolhe disco desde já e prepara o terreno pra Fase 2 (image-to-video
real, que enviará ESTA mídia normalizada pro Higgsfield).

Best-effort por contrato: se o ffmpeg não decodifica o formato, o chamador
degrada pro original — normalização é otimização, NUNCA condição de correção.
Erro sempre estruturado (nível + mensagem legível), nunca 'exit status 1' cru.

ponytail: mora no app, não em shared-core — só o motor-b normaliza input
(critério de Core: 2+ produtos reais). Sobe pra shared-core quando o Motor
Imagem nascer de verdade e precisar do mesmo.
"""
from __future__ import annotations

import os
import subprocess
import tempfile
from pathlib import Path

TIMEOUT_S = 120
# ponytail: caps fixos (1080 img / 720p vídeo) — viram env se um cliente pedir 4K
_ESCALA_IMG = "scale='min(1080,iw)':'min(1080,ih)':force_original_aspect_ratio=decrease"
_ESCALA_VID = ("scale='min(1280,iw)':'min(720,ih)':"
               "force_original_aspect_ratio=decrease:force_divisible_by=2")

# Correção de luz da foto de celular ANTES do Kling (achado real: foto escura →
# vídeo escuro; o modelo é fiel, não resgata input ruim). Só age quando a luma
# média (YAVG 0-255) está abaixo do limiar — não estoura foto boa. gamma lifta
# sombra sem clipar highlight; saturação recupera cor perdida no escuro.
_LUMA_ALVO = float(os.environ.get("MOTOR_B_LUMA_ALVO", "120"))
_LUMA_LIMIAR = float(os.environ.get("MOTOR_B_LUMA_LIMIAR", "95"))


def _medir_luma(dados: bytes) -> float | None:
    """YAVG (luma média 0-255) do 1º frame via signalstats. None se não medir."""
    with tempfile.TemporaryDirectory() as tmp:
        ent = Path(tmp) / "in"
        met = Path(tmp) / "luma.txt"
        ent.write_bytes(dados)
        try:
            subprocess.run(
                ["ffmpeg", "-y", "-loglevel", "error", "-i", str(ent), "-frames:v", "1",
                 "-vf", f"signalstats,metadata=print:file={met}", "-f", "null", "-"],
                check=True, capture_output=True, timeout=TIMEOUT_S)
            for linha in met.read_text().splitlines():
                if "YAVG=" in linha:
                    return float(linha.split("YAVG=")[1].split()[0])
        except (subprocess.SubprocessError, OSError, ValueError, IndexError):
            return None
    return None


def _correcao_luz(dados: bytes) -> str:
    """Filtro `eq=...` extra se a foto está escura; '' se já tem luz suficiente
    (ou se a medição falhar — best-effort, nunca inventa correção sem medir)."""
    y = _medir_luma(dados)
    if y is None or y >= _LUMA_LIMIAR:
        return ""
    gamma = min(1.8, 1.0 + (_LUMA_ALVO - y) / _LUMA_ALVO)  # >1 clareia midtones
    return f",eq=gamma={gamma:.2f}:saturation=1.12:contrast=1.04"


class NormalizacaoErro(RuntimeError):
    """FFmpeg não conseguiu normalizar. nivel: ffmpeg|timeout|ambiente|tipo."""

    def __init__(self, nivel: str, mensagem: str):
        self.nivel = nivel
        self.mensagem = mensagem
        super().__init__(f"[{nivel}] {mensagem}")


def normalizar(dados: bytes, mime: str) -> tuple[bytes, str]:
    """(bytes, mime) normalizados. Lança NormalizacaoErro se o ffmpeg falhar."""
    if mime.startswith("image/"):
        vf = _ESCALA_IMG + _correcao_luz(dados)  # clareia foto escura de celular
        return _rodar(dados, ".jpg", ["-vf", vf, "-q:v", "3"]), "image/jpeg"
    if mime.startswith("video/"):
        return _rodar(dados, ".mp4",
                      ["-vf", _ESCALA_VID, "-c:v", "libx264", "-preset", "veryfast",
                       "-crf", "24", "-c:a", "aac", "-b:a", "128k",
                       "-movflags", "+faststart"]), "video/mp4"
    raise NormalizacaoErro("tipo", f"mime não normalizável: {mime}")


def _rodar(dados: bytes, suf_saida: str, args_meio: list[str]) -> bytes:
    with tempfile.TemporaryDirectory() as tmp:
        # ffmpeg sonda o formato pelo conteúdo, não pela extensão: entrada sem
        # sufixo funciona pra png/jpg/webp/mp4/mov.
        entrada = Path(tmp) / "entrada"
        saida = Path(tmp) / f"saida{suf_saida}"
        entrada.write_bytes(dados)
        _ffmpeg(["-i", str(entrada), *args_meio, str(saida)])
        return saida.read_bytes()


def _ffmpeg(args: list[str]) -> None:
    try:
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", *args],
                       check=True, capture_output=True, timeout=TIMEOUT_S)
    except subprocess.TimeoutExpired:
        raise NormalizacaoErro("timeout", f"ffmpeg passou de {TIMEOUT_S}s")
    except subprocess.CalledProcessError as e:
        raise NormalizacaoErro("ffmpeg", _stderr_legivel(e.stderr))
    except FileNotFoundError:
        raise NormalizacaoErro("ambiente", "ffmpeg não encontrado no PATH")


def _stderr_legivel(stderr: bytes | None) -> str:
    txt = (stderr or b"").decode("utf-8", "replace").strip()
    return txt.splitlines()[-1][:300] if txt else "sem stderr"


if __name__ == "__main__":  # self-check: normaliza uma imagem grande de verdade
    import os
    with tempfile.TemporaryDirectory() as _t:
        _png = Path(_t) / "big.png"
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi",
                        "-i", "testsrc2=size=2000x2000:duration=1:rate=1",
                        "-frames:v", "1", str(_png)], check=True)
        _b, _m = normalizar(_png.read_bytes(), "image/png")
        assert _m == "image/jpeg" and len(_b) > 0
        assert _b[:2] == b"\xff\xd8", "saída não é JPEG"
        try:
            normalizar(b"isto nao e imagem", "image/png")
            raise SystemExit("deveria ter falhado em bytes inválidos")
        except NormalizacaoErro as e:
            assert e.nivel == "ffmpeg"
        # correção de luz: gera foto ESCURA, normaliza, confirma que a luma subiu
        _dark = Path(_t) / "dark.png"
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi",
                        "-i", "color=c=0x202020:size=800x600:duration=1:rate=1",
                        "-frames:v", "1", str(_dark)], check=True)
        y0 = _medir_luma(_dark.read_bytes())
        _bc, _ = normalizar(_dark.read_bytes(), "image/png")
        y1 = _medir_luma(_bc)
        assert y0 is not None and y1 is not None and y1 > y0 + 15, (y0, y1)
        print("media OK — 2000x2000 png →", len(_b), "bytes jpeg; erro ok; "
              f"luz {y0:.0f}→{y1:.0f}")
