"""Derivados do vídeo pronto (Motor B — Onda 1.5, quick-wins).

Cada função recebe o vídeo COMPLETO já gerado e devolve (bytes, mime) de uma
variante — proporção extra, ficha na tela, capa, teaser, versão muda, loop. Tudo
é FFmpeg reusando `pos.py` (mesma casa de FFmpeg, mesmas constantes/erro). São
derivados SOB DEMANDA (endpoint /api/assets/{id}/derivar) — não incham o job
principal nem o schema: cada derivado vira um asset novo ligado ao original.

ponytail: derivado é acabamento, não geração — nada aqui chama LLM/provider de
vídeo. Reusa pos._ffmpeg/_ALVO/_FONT/_cor_ffmpeg; cada função é um passo ffmpeg.
"""
from __future__ import annotations

import tempfile
from pathlib import Path

import pos

TEASER_S = 15   # teaser vertical pra WhatsApp
LOOP_S = 5      # loop curto pro hero do site


def _tmp_video(dados: bytes, tdir: Path) -> Path:
    p = tdir / "in.mp4"
    p.write_bytes(dados)
    return p


def _drawtext(texto: str, tdir: Path, nome: str, *, tamanho: str, y: str,
              cor="white", box="black@0.4", alpha: str | None = None) -> str:
    arq = tdir / f"{nome}.txt"
    arq.write_text(texto[:120], encoding="utf-8")
    a = f":alpha='{alpha}'" if alpha else ""
    return (f"drawtext=fontfile={pos._FONT}:textfile={arq}:fontcolor={cor}:fontsize={tamanho}:"
            f"x=(w-tw)/2:y={y}:box=1:boxcolor={box}:boxborderw=12{a}")


# 1) proporção extra (1:1 além do 9:16/16:9) — mesmo vídeo, outro enquadramento
def proporcao(video: bytes, aspect: str) -> tuple[bytes, str]:
    """Reframe crop-to-fill pro aspect pedido (ex.: 1:1 pro feed). Reusa o reframe
    do pos.pos_processar (sem watermark/legenda — só o enquadramento)."""
    if aspect not in pos._ALVO:
        raise pos.PosErro("ffmpeg", f"aspect não suportado: {aspect} (use {list(pos._ALVO)})")
    dados, mime, _ = pos.pos_processar(video, "video/mp4", aspect=aspect)
    return dados, mime


# 2) texto animado com dado da ficha (preço/endereço/código) no overlay
def ficha(video: bytes, ficha: dict, brand: dict | None = None) -> tuple[bytes, str]:
    """Queima os dados da ficha (preço, endereço, código) como texto animado
    (fade-in escalonado) no topo do vídeo. Só entram os campos que vierem."""
    brand = brand or {}
    linhas = pos.ficha_linhas(ficha)  # seleção/ordem única (preço/local/medidas/código)
    if not linhas:
        raise pos.PosErro("ffmpeg", "ficha vazia — nada pra sobrepor")
    acento = pos._cor_ffmpeg(brand.get("cor_acento"))
    with tempfile.TemporaryDirectory() as t:
        tdir = Path(t)
        entrada = _tmp_video(video, tdir)
        filtros = []
        for i, (campo, valor) in enumerate(linhas):
            atraso = 0.3 + i * 0.35  # escalonado
            alpha = f"if(lt(t,{atraso:.2f}),0,if(lt(t,{atraso + 0.5:.2f}),(t-{atraso:.2f})/0.5,1))"
            box = acento if campo == "preco" else "black@0.5"
            filtros.append(_drawtext(valor, tdir, f"f{i}", tamanho="h/26",
                                     y=f"h/12+{i}*(h/13)", box=box, alpha=alpha))
        saida = tdir / "out.mp4"
        pos._ffmpeg(["-i", str(entrada), "-vf", ",".join(filtros),
                     "-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
                     "-pix_fmt", "yuv420p", "-c:a", "copy", "-movflags", "+faststart", str(saida)])
        return saida.read_bytes(), "video/mp4"


# 3) capa personalizada: melhor frame + fundo desfocado + título + marca
def capa(video: bytes, titulo: str, brand: dict | None = None) -> tuple[bytes, str]:
    """JPEG de capa: pega um frame representativo, desfoca como fundo, sobrepõe o
    frame nítido centralizado e o título + marca. Serve de thumbnail/pôster."""
    brand = brand or {}
    marca = str(brand.get("nome") or "").strip()
    with tempfile.TemporaryDirectory() as t:
        tdir = Path(t)
        entrada = _tmp_video(video, tdir)
        tit = tdir / "tit.txt"; tit.write_text((titulo or "").strip()[:80] or " ", encoding="utf-8")
        # fundo = frame borrado e escurecido; título grande centralizado
        vf = ("boxblur=20:2,eq=brightness=-0.15,"
              + _drawtext_raw(tit, tamanho="h/14", y="(h-th)/2", cor="white", box="black@0.35"))
        if marca:
            mk = tdir / "mk.txt"; mk.write_text(marca[:40], encoding="utf-8")
            vf += "," + _drawtext_raw(mk, tamanho="h/28", y="h-th-h/12",
                                      cor="white@0.9", box=pos._cor_ffmpeg(brand.get("cor_acento")) + "@0.9")
        saida = tdir / "capa.jpg"
        # -ss 1: frame ~1s (evita o preto inicial); 1 quadro
        pos._ffmpeg(["-ss", "1", "-i", str(entrada), "-vf", vf, "-frames:v", "1", "-q:v", "3", str(saida)])
        return saida.read_bytes(), "image/jpeg"


def _drawtext_raw(arq: Path, *, tamanho: str, y: str, cor: str, box: str) -> str:
    return (f"drawtext=fontfile={pos._FONT}:textfile={arq}:fontcolor={cor}:fontsize={tamanho}:"
            f"x=(w-tw)/2:y={y}:box=1:boxcolor={box}:boxborderw=14")


# 4) teaser vertical de 15s pra WhatsApp
def teaser(video: bytes, segundos: int = TEASER_S, brand: dict | None = None) -> tuple[bytes, str]:
    """Recorta os primeiros `segundos` (≤15) e reenquadra 9:16 pro WhatsApp."""
    seg = max(3, min(int(segundos or TEASER_S), 15))
    w, h = pos._ALVO["9:16"]
    with tempfile.TemporaryDirectory() as t:
        tdir = Path(t)
        entrada = _tmp_video(video, tdir)
        saida = tdir / "teaser.mp4"
        pos._ffmpeg(["-t", str(seg), "-i", str(entrada),
                     "-vf", f"scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h}",
                     "-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
                     "-pix_fmt", "yuv420p", "-c:a", "aac", "-movflags", "+faststart", str(saida)])
        return saida.read_bytes(), "video/mp4"


# 5) versão silenciosa com legenda hardcoded (feed autoplay sem som)
def silenciosa(video: bytes, legenda: str, brand: dict | None = None) -> tuple[bytes, str]:
    """Remove o áudio e queima a legenda fixa — pro feed que dá autoplay mudo."""
    brand = brand or {}
    leg = (legenda or "").strip()
    if not leg:
        raise pos.PosErro("ffmpeg", "legenda vazia — versão silenciosa precisa de texto")
    acento = pos._cor_ffmpeg(brand.get("cor_acento"))
    with tempfile.TemporaryDirectory() as t:
        tdir = Path(t)
        entrada = _tmp_video(video, tdir)
        vf = _drawtext(leg, tdir, "leg", tamanho="h/24", y="h-th-h/9", box=f"{acento}@0.9")
        saida = tdir / "mudo.mp4"
        pos._ffmpeg(["-i", str(entrada), "-an", "-vf", vf,
                     "-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
                     "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(saida)])
        return saida.read_bytes(), "video/mp4"


# 6) loop curto (5s) pro hero do site — boomerang costura o fim no começo
def loop(video: bytes, segundos: int = LOOP_S) -> tuple[bytes, str]:
    """Recorta `segundos` e faz boomerang (ida + volta) — loop sem salto pro hero,
    sem áudio. ponytail: boomerang é o jeito barato de costurar sem casar frames."""
    seg = max(2, min(int(segundos or LOOP_S), 8))
    metade = round(seg / 2, 2)
    with tempfile.TemporaryDirectory() as t:
        tdir = Path(t)
        entrada = _tmp_video(video, tdir)
        saida = tdir / "loop.mp4"
        # corta metade, concatena com a versão reversa → ida-e-volta contínua
        filtro = ("[0:v]trim=0:%s,setpts=PTS-STARTPTS,split[a][b];"
                  "[b]reverse[r];[a][r]concat=n=2:v=1:a=0[out]" % metade)
        pos._ffmpeg(["-i", str(entrada), "-filter_complex", filtro, "-map", "[out]",
                     "-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
                     "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(saida)])
        return saida.read_bytes(), "video/mp4"


# despacho por tipo (usado pelo endpoint) — cada tipo mapeia pros params do corpo
def derivar(tipo: str, video: bytes, params: dict, brand: dict | None = None) -> tuple[bytes, str]:
    if tipo == "proporcao":
        return proporcao(video, params.get("aspect", "1:1"))
    if tipo == "ficha":
        return ficha(video, params.get("ficha") or {}, brand)
    if tipo == "capa":
        return capa(video, params.get("titulo", ""), brand)
    if tipo == "teaser":
        return teaser(video, params.get("segundos", TEASER_S), brand)
    if tipo == "silenciosa":
        return silenciosa(video, params.get("legenda", ""), brand)
    if tipo == "loop":
        return loop(video, params.get("segundos", LOOP_S))
    raise pos.PosErro("ffmpeg", f"tipo de derivado desconhecido: {tipo}")


TIPOS = ("proporcao", "ficha", "capa", "teaser", "silenciosa", "loop")


if __name__ == "__main__":  # self-check: roda os 6 derivados sobre um clipe real
    import subprocess
    with tempfile.TemporaryDirectory() as _t:
        src = Path(_t) / "src.mp4"
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi",
                        "-i", "testsrc2=size=1280x720:duration=6:rate=24", "-f", "lavfi",
                        "-i", "sine=frequency=440:duration=6", "-c:v", "libx264",
                        "-pix_fmt", "yuv420p", "-c:a", "aac", str(src)], check=True)
        v = src.read_bytes()
        brand = {"nome": "Imobiliária Sol", "cor_acento": "#0E7C86"}

        def _dim(dados, ext="mp4"):
            f = Path(_t) / f"o.{ext}"; f.write_bytes(dados)
            r = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0",
                                "-show_entries", "stream=width,height", "-of", "csv=p=0", str(f)],
                               capture_output=True, text=True)
            return r.stdout.strip()

        b, m = proporcao(v, "1:1"); assert _dim(b) == "1080,1080", _dim(b)
        b, m = ficha(v, {"preco": "R$ 850.000", "endereco": "Rua das Flores, 123", "codigo": "REF-4821"}, brand); assert m == "video/mp4" and len(b) > 0
        b, m = capa(v, "Apartamento 3 quartos", brand); assert m == "image/jpeg" and b[:2] == b"\xff\xd8"
        b, m = teaser(v, 15, brand); assert _dim(b) == "720,1280"
        b, m = silenciosa(v, "Agende sua visita", brand)
        f = Path(_t) / "s.mp4"; f.write_bytes(b)
        na = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "a", "-show_entries",
                             "stream=index", "-of", "csv=p=0", str(f)], capture_output=True, text=True)
        assert na.stdout.strip() == "", "versão silenciosa ainda tem áudio"
        b, m = loop(v, 4); assert len(b) > 0
        print("derivados OK — proporcao/ficha/capa/teaser/silenciosa/loop")
