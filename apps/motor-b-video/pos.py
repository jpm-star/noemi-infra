"""Pós-processamento do vídeo de SAÍDA via FFmpeg (motor-b-video, Onda 1).

Aplica no vídeo pronto (mock ou Higgsfield), ANTES de virar asset:
  - reframe automático pro aspect alvo (9:16 / 16:9 / 1:1) — crop-to-fill centrado
  - watermark de marca (nome da marca, drawtext semitransparente no canto)
  - legenda animada (uma linha de CTA/destaque, fade-in)

Best-effort por contrato (igual media.normalizar): se o ffmpeg falhar, o chamador
degrada pro vídeo original — pós-processamento é acabamento, NUNCA condição de
correção. Erro sempre estruturado. Um passo ffmpeg único (filtergraph), sem
reencode duplo; se nada se aplica, devolve os bytes originais sem tocar no ffmpeg.

ponytail: watermark é o NOME da marca via drawtext; overlay de PNG de logo real
= follow-up pra quando o cliente subir um logo. drawtext usa DejaVuSans-Bold
(presente na base). Textos vão por `textfile=` — zero escaping frágil no filtro.
"""
from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path

TIMEOUT_S = 180
_FONT = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
# aspect alvo → (largura, altura) par (divisível por 2, exigência do H.264)
_ALVO = {"9:16": (720, 1280), "16:9": (1280, 720), "1:1": (1080, 1080), "4:5": (864, 1080)}


class PosErro(RuntimeError):
    """FFmpeg falhou no pós-processamento. nivel: ffmpeg|timeout|ambiente."""

    def __init__(self, nivel: str, mensagem: str):
        self.nivel = nivel
        self.mensagem = mensagem
        super().__init__(f"[{nivel}] {mensagem}")


def _cor_ffmpeg(hex_cor: str | None, fallback: str = "0x7c5cff") -> str:
    if isinstance(hex_cor, str) and hex_cor.startswith("#") and len(hex_cor) == 7:
        return "0x" + hex_cor[1:]
    return fallback


def pos_processar(dados: bytes, mime: str, *, aspect: str | None = None,
                  brand: dict | None = None, legenda: str | None = None) -> tuple[bytes, str, dict]:
    """(bytes, mime, meta) pós-processados. meta['aplicado'] lista o que rodou.
    Lança PosErro se o ffmpeg falhar. No-op (retorna original) se nada se aplica."""
    if not mime.startswith("video/"):
        return dados, mime, {"aplicado": []}

    brand = brand or {}
    with tempfile.TemporaryDirectory() as tmp:
        tdir = Path(tmp)
        filtros: list[str] = []
        aplicado: list[str] = []

        # 1) reframe crop-to-fill (só se o alvo é conhecido)
        if aspect in _ALVO:
            w, h = _ALVO[aspect]
            filtros.append(f"scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h}")
            aplicado.append(f"reframe:{aspect}")

        acento = _cor_ffmpeg(brand.get("cor_acento"))

        # 2) legenda animada (fade-in nos primeiros 0.6s), faixa inferior central
        legenda = (legenda or "").strip()
        if legenda:
            arq = tdir / "legenda.txt"
            arq.write_text(legenda[:120], encoding="utf-8")
            filtros.append(
                f"drawtext=fontfile={_FONT}:textfile={arq}:fontcolor=white:fontsize=h/26:"
                f"x=(w-tw)/2:y=h-th-h/9:box=1:boxcolor={acento}@0.85:boxborderw=14:"
                f"alpha='if(lt(t,0.3),0,if(lt(t,0.9),(t-0.3)/0.6,1))'"
            )
            aplicado.append("legenda")

        # 3) watermark de marca (nome, canto inferior direito)
        marca = str(brand.get("nome") or "").strip()
        if marca:
            arq = tdir / "marca.txt"
            arq.write_text(marca[:40], encoding="utf-8")
            filtros.append(
                f"drawtext=fontfile={_FONT}:textfile={arq}:fontcolor=white@0.8:fontsize=h/32:"
                f"x=w-tw-24:y=h-th-24:box=1:boxcolor=black@0.35:boxborderw=8"
            )
            aplicado.append("watermark")

        if not filtros:
            return dados, mime, {"aplicado": []}

        entrada = tdir / "in"
        saida = tdir / "out.mp4"
        entrada.write_bytes(dados)
        _ffmpeg(["-i", str(entrada), "-vf", ",".join(filtros),
                 "-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
                 "-pix_fmt", "yuv420p", "-c:a", "copy", "-movflags", "+faststart",
                 str(saida)])
        return saida.read_bytes(), "video/mp4", {"aplicado": aplicado}


def extrair_frame(dados_video: bytes, *, fim: bool = True) -> bytes:
    """PNG do último (fim=True) ou primeiro frame do vídeo. É o elo do
    storyboard: o último frame de uma cena vira o START da próxima. Lança
    PosErro se o ffmpeg falhar."""
    with tempfile.TemporaryDirectory() as tmp:
        entrada = Path(tmp) / "in.mp4"
        saida = Path(tmp) / "frame.png"
        entrada.write_bytes(dados_video)
        # -sseof -0.2 posiciona perto do fim; -update 1 sobrescreve até o último
        pos_args = ["-sseof", "-0.2", "-i", str(entrada)] if fim else ["-i", str(entrada), "-ss", "0"]
        _ffmpeg([*pos_args, "-update", "1", "-frames:v", "1", str(saida)])
        return saida.read_bytes()


def concatenar(clips: list[bytes], largura: int, altura: int) -> bytes:
    """Concatena os clipes das cenas num walkthrough único (corte seco — o frame
    encadeado já dá continuidade). Cada clipe é escalado/cropado pra largura×altura
    comum (concat exige mesma geometria). Sem áudio (walkthrough silencioso; trilha
    é outra etapa). Lança PosErro."""
    if not clips:
        raise PosErro("ffmpeg", "sem clipes pra concatenar")
    if len(clips) == 1:
        return clips[0]
    with tempfile.TemporaryDirectory() as tmp:
        entradas: list[str] = []
        partes: list[str] = []
        for i, c in enumerate(clips):
            p = Path(tmp) / f"c{i}.mp4"
            p.write_bytes(c)
            entradas += ["-i", str(p)]
            partes.append(
                f"[{i}:v]scale={largura}:{altura}:force_original_aspect_ratio=increase,"
                f"crop={largura}:{altura},setsar=1,fps=24[v{i}]")
        cadeia = "".join(f"[v{i}]" for i in range(len(clips)))
        filtro = ";".join(partes) + f";{cadeia}concat=n={len(clips)}:v=1:a=0[out]"
        saida = Path(tmp) / "walkthrough.mp4"
        _ffmpeg([*entradas, "-filter_complex", filtro, "-map", "[out]",
                 "-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
                 "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(saida)])
        return saida.read_bytes()


def _ffmpeg(args: list[str]) -> None:
    try:
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", *args],
                       check=True, capture_output=True, timeout=TIMEOUT_S)
    except subprocess.TimeoutExpired:
        raise PosErro("timeout", f"ffmpeg passou de {TIMEOUT_S}s")
    except subprocess.CalledProcessError as e:
        raise PosErro("ffmpeg", _stderr_legivel(e.stderr))
    except FileNotFoundError:
        raise PosErro("ambiente", "ffmpeg não encontrado no PATH")


def _stderr_legivel(stderr: bytes | None) -> str:
    txt = (stderr or b"").decode("utf-8", "replace").strip()
    return txt.splitlines()[-1][:300] if txt else "sem stderr"


if __name__ == "__main__":  # self-check: gera um clipe e aplica os 3 efeitos
    with tempfile.TemporaryDirectory() as _t:
        src = Path(_t) / "src.mp4"
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi",
                        "-i", "testsrc2=size=1280x720:duration=2:rate=24",
                        "-f", "lavfi", "-i", "sine=frequency=440:duration=2",
                        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac",
                        str(src)], check=True)
        out, mime, meta = pos_processar(
            src.read_bytes(), "video/mp4", aspect="9:16",
            brand={"nome": "Ateliê Pedra", "cor_acento": "#0E7C86"},
            legenda="Agende sua visita hoje")
        assert mime == "video/mp4" and len(out) > 0
        assert meta["aplicado"] == ["reframe:9:16", "legenda", "watermark"], meta
        # confirma que o reframe mudou a resolução pra 720x1280
        outf = Path(_t) / "out.mp4"
        outf.write_bytes(out)
        probe = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0",
                                "-show_entries", "stream=width,height", "-of", "csv=p=0",
                                str(outf)], capture_output=True, text=True)
        assert probe.stdout.strip() == "720,1280", probe.stdout
        # no-op quando nada se aplica
        _b, _m, _meta = pos_processar(b"x", "image/jpeg")
        assert _meta["aplicado"] == []
        print("pos OK — 1280x720 →", probe.stdout.strip(), "| efeitos:", meta["aplicado"])
