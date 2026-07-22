"""OG image do site (banner 1200x630 pro preview no WhatsApp/redes).

Sem og:image, o link colado no WhatsApp aparece sem imagem = cara de spam, taxa
de clique despenca. WhatsApp exige PNG/JPG absoluto (ignora SVG/data-URI), então
rasterizamos com FFmpeg (já presente) um card com a cor de acento do TEMA do site
+ nome do negócio. Reusa design.escolher_tema pra o acento bater com o site.

ponytail: drawtext, um passo ffmpeg; sem lib de imagem nova. Best-effort — se o
ffmpeg falhar, o site publica do mesmo jeito (só sem preview), nunca quebra.
"""
from __future__ import annotations

import re
import subprocess
import tempfile
from pathlib import Path

_FONT = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"


def _acento(nicho: str, nome: str) -> str:
    """Acento do tema do site (mesmo que o template usa). Fallback roxo Noemi."""
    try:
        from app import design
        cor = design.escolher_tema(nicho or "", nome or "").acento
        if isinstance(cor, str) and cor.startswith("#") and len(cor) == 7:
            return "0x" + cor[1:]
    except Exception:
        pass
    return "0x7c5cff"


def gerar_og(nome: str, subtitulo: str, dest_dir: Path, *, nicho: str = "") -> bool:
    """Escreve <dest_dir>/og.png (1200x630). True se gerou, False se degradou."""
    acento = _acento(nicho, nome)
    dest = Path(dest_dir)
    dest.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as t:
        tn = Path(t) / "nome.txt"; tn.write_text((nome or "Noemi")[:48], encoding="utf-8")
        ts = Path(t) / "sub.txt"; ts.write_text((subtitulo or "")[:80], encoding="utf-8")
        tm = Path(t) / "marca.txt"; tm.write_text("feito com noemi", encoding="utf-8")
        vf = (
            # fundo: acento -> escuro (gradiente diagonal via 2 cores? usamos cor sólida + vinheta)
            f"drawbox=x=0:y=0:w=1200:h=630:color={acento}:t=fill,"
            f"drawbox=x=0:y=430:w=1200:h=200:color=black@0.18:t=fill,"
            f"drawtext=fontfile={_FONT}:textfile={tn}:fontcolor=white:fontsize=92:"
            f"x=(w-tw)/2:y=250-th/2:box=0,"
            f"drawtext=fontfile={_FONT}:textfile={ts}:fontcolor=white@0.9:fontsize=40:"
            f"x=(w-tw)/2:y=360,"
            f"drawtext=fontfile={_FONT}:textfile={tm}:fontcolor=white@0.6:fontsize=28:"
            f"x=(w-tw)/2:y=560"
        )
        saida = dest / "og.png"
        try:
            subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi",
                            "-i", "color=c=black:s=1200x630", "-vf", vf,
                            "-frames:v", "1", str(saida)],
                           check=True, capture_output=True, timeout=60)
            return True
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired, FileNotFoundError):
            return False


_META_RE = re.compile(r'(<meta property="og:type"[^>]*>)', re.I)


def injetar_meta(index_path: Path, slug: str, base_url: str) -> bool:
    """Insere og:image/og:url no <head> do index.html (idempotente). True se mexeu."""
    p = Path(index_path)
    if not p.is_file():
        return False
    html = p.read_text(encoding="utf-8")
    if "og:image" in html:
        return False  # já tem
    url = f"{base_url.rstrip('/')}/{slug}"
    tags = (f'<meta property="og:image" content="{url}/og.png">'
            f'<meta property="og:image:width" content="1200">'
            f'<meta property="og:image:height" content="630">'
            f'<meta property="og:url" content="{url}/">')
    if _META_RE.search(html):
        novo = _META_RE.sub(lambda m: m.group(1) + tags, html, count=1)
    else:  # sem og:type — injeta antes de </head>
        novo = html.replace("</head>", tags + "</head>", 1)
    p.write_text(novo, encoding="utf-8")
    return True


def aplicar(nome: str, subtitulo: str, nicho: str, slug: str, out_dir: Path, base_url: str) -> bool:
    """Conveniência: gera og.png + injeta a meta no index do site. Best-effort."""
    dest = Path(out_dir) / slug
    ok = gerar_og(nome, subtitulo, dest, nicho=nicho)
    if ok:
        injetar_meta(dest / "index.html", slug, base_url)
    return ok


if __name__ == "__main__":  # self-check
    with tempfile.TemporaryDirectory() as t:
        d = Path(t) / "meusite"
        d.mkdir()
        (d / "index.html").write_text(
            '<head><meta property="og:type" content="website"></head><body>x</body>', encoding="utf-8")
        assert gerar_og("Clínica Vitalis", "Atendimento no mesmo dia", d, nicho="clínica odontológica")
        assert (d / "og.png").stat().st_size > 0
        # confere que é PNG e >=1200 largura
        r = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0",
                            "-show_entries", "stream=width,height", "-of", "csv=p=0", str(d / "og.png")],
                           capture_output=True, text=True)
        assert r.stdout.strip() == "1200,630", r.stdout
        assert injetar_meta(d / "index.html", "meusite", "https://go.noemi.digital")
        assert 'og:image" content="https://go.noemi.digital/meusite/og.png"' in (d / "index.html").read_text()
        assert not injetar_meta(d / "index.html", "meusite", "https://go.noemi.digital")  # idempotente
        print("og OK — 1200x630 gerado + meta injetada")
