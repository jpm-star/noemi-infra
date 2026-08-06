#!/usr/bin/env python3
"""Compressão OBRIGATÓRIA de mídia no pipeline de geração de site.

Auditoria Rações & Cia (erro crítico #4): vídeo de hero de ~7MB servido cru. A tag já
tinha `preload="metadata"` e poster — o problema nunca foi o HTML, foi o ARQUIVO. Um
lead em 4G desiste antes do site pintar, e nenhuma quantidade de lazy-load conserta
byte que não devia existir.

Duas conversões, ambas com ferramenta que já está na máquina (custo R$0):
  imagem → WebP (Pillow), qualidade 82, teto de 1600px no lado maior
  vídeo   → H.264 CRF 28 + poster JPEG do 1º frame (ffmpeg)

REGRA: nunca piora. Se a conversão sair MAIOR que o original (acontece com PNG já
otimizado e vídeo já comprimido), devolve o original. Compressão que engorda é bug
silencioso — o site fica pior e ninguém percebe.
"""
from __future__ import annotations

import io
import subprocess
import tempfile
from pathlib import Path

MAX_LADO = 1600      # acima disso é resolução que nenhum hero usa
QUALIDADE = 82       # WebP: indistinguível do original a olho, ~30% do peso
CRF_VIDEO = 28       # H.264: "bom o bastante" pra vídeo de fundo
LIMITE_VIDEO_MB = 12  # acima disso, recomprime mesmo que já seja mp4


def comprimir_imagem(dados: bytes, nome: str = "img") -> tuple[bytes, str]:
    """(bytes, extensão). WebP quando compensa; original quando não."""
    if not dados:
        return dados, "jpg"
    try:
        from PIL import Image
        im = Image.open(io.BytesIO(dados))
        im.load()
        if im.mode in ("RGBA", "LA", "P"):
            im = im.convert("RGBA") if "A" in im.mode else im.convert("RGB")
        else:
            im = im.convert("RGB")
        if max(im.size) > MAX_LADO:
            escala = MAX_LADO / max(im.size)
            im = im.resize((int(im.width * escala), int(im.height * escala)),
                           Image.LANCZOS)
        buf = io.BytesIO()
        im.save(buf, "WEBP", quality=QUALIDADE, method=6)
        saida = buf.getvalue()
    except Exception:  # noqa: BLE001 — imagem exótica não pode derrubar a geração
        return dados, (nome.rsplit(".", 1)[-1] or "jpg").lower()[:5]
    if len(saida) >= len(dados):
        # NÃO piora: PNG já otimizado costuma virar WebP maior
        return dados, (nome.rsplit(".", 1)[-1] or "jpg").lower()[:5]
    return saida, "webp"


def comprimir_video(dados: bytes) -> tuple[bytes, bytes | None]:
    """(video_bytes, poster_jpeg). Poster é o 1º frame — sem ele, `preload=metadata`
    deixa um retângulo preto no lugar do hero até o vídeo começar."""
    if not dados:
        return dados, None
    with tempfile.TemporaryDirectory() as d:
        ent = Path(d) / "in.mp4"
        sai = Path(d) / "out.mp4"
        pos = Path(d) / "poster.jpg"
        ent.write_bytes(dados)
        try:
            subprocess.run(
                ["ffmpeg", "-y", "-i", str(ent), "-vf", f"scale='min({MAX_LADO},iw)':-2",
                 "-c:v", "libx264", "-crf", str(CRF_VIDEO), "-preset", "veryfast",
                 "-movflags", "+faststart", "-an", str(sai)],
                capture_output=True, timeout=600, check=True)
            subprocess.run(
                ["ffmpeg", "-y", "-i", str(ent), "-frames:v", "1", "-q:v", "4", str(pos)],
                capture_output=True, timeout=120, check=True)
        except Exception:  # noqa: BLE001 — ffmpeg indisponível/vídeo quebrado
            return dados, None
        novo = sai.read_bytes() if sai.exists() else b""
        poster = pos.read_bytes() if pos.exists() else None
    if not novo or len(novo) >= len(dados):
        return dados, poster        # não piora, mas o poster ainda ajuda
    return novo, poster


def relatorio(antes: int, depois: int) -> str:
    if antes <= 0:
        return ""
    return f"{antes / 1e6:.1f}MB -> {depois / 1e6:.1f}MB ({100 - round(100 * depois / antes)}% menor)"


if __name__ == "__main__":  # self-check com imagem gerada na hora (sem rede)
    from PIL import Image
    buf = io.BytesIO()
    Image.new("RGB", (3000, 2000), (200, 40, 40)).save(buf, "PNG")
    grande = buf.getvalue()
    saida, ext = comprimir_imagem(grande, "teste.png")
    assert ext == "webp" and len(saida) < len(grande), (ext, len(saida), len(grande))
    from PIL import Image as _I
    assert max(_I.open(io.BytesIO(saida)).size) <= MAX_LADO
    # imagem minúscula: conversão não compensa e o original tem que voltar intacto
    b2 = io.BytesIO(); Image.new("RGB", (4, 4)).save(b2, "WEBP", quality=1)
    peq = b2.getvalue()
    s2, e2 = comprimir_imagem(peq, "p.webp")
    assert s2 == peq or len(s2) < len(peq), "nunca pode devolver maior"
    assert comprimir_imagem(b"", "x")[0] == b""
    print(f"assets_web OK — {relatorio(len(grande), len(saida))}, teto {MAX_LADO}px, "
          "nunca devolve maior que o original")
