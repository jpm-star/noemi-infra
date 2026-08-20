"""Subir foto e vídeo de chinelo pelo painel, sem terminal.

O site é estático (Astro), então "trocar a foto" são três passos que ninguém quer
fazer na mão: converter a imagem pros formatos certos, apontar o conteúdo pra ela,
e publicar. Aqui os três viram um botão.

O QUE ESTE MÓDULO NÃO FAZ, de propósito:
- não publica sozinho. Subir mídia e publicar são ações separadas, porque publicar
  é o que o cliente vê. Sobe várias fotos, confere, aí publica.
- não aceita qualquer arquivo: valida pelo CONTEÚDO (Pillow/ffprobe abrem de
  verdade), não pela extensão. Extensão é palpite do navegador.

ponytail: Pillow e ffmpeg já estão na máquina; nada de serviço de imagem novo.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from pathlib import Path

_REPO = Path(os.environ.get("PEDI_REPO", "/root/pedi-site"))
_PUBLICADO = Path(os.environ.get("PEDI_PUBLICADO", "/var/www/pedi"))
_PRODUTOS = _REPO / "src/content/produtos"
_DESTINO = _REPO / "public/produtos"          # fotos reais; /mock é o que elas substituem
_TIPOS = ("top", "detalhe", "perfil", "lifestyle")
_LARGURA = 900
_MAX_MB = int(os.environ.get("PEDI_MAX_MB", "60"))


class ErroMidia(Exception):
    """Erro que o operador consegue entender e resolver sozinho."""


def _slug_valido(slug: str) -> Path:
    if not re.fullmatch(r"[a-z0-9-]{1,60}", slug or ""):
        raise ErroMidia(f"estampa inválida: {slug!r}")
    md = _PRODUTOS / f"{slug}.md"
    if not md.exists():
        raise ErroMidia(f"estampa não existe no catálogo: {slug}")
    return md


def _cortar_quadrado(img):
    """Recorta o centro em 1:1. O site inteiro assume foto quadrada; mandar 16:9
    pro grid quebraria o alinhamento de todos os cards de uma vez."""
    lado = min(img.size)
    e, t = (img.width - lado) // 2, (img.height - lado) // 2
    return img.crop((e, t, e + lado, t + lado))


def salvar_foto(slug: str, tipo: str, dados: bytes) -> dict:
    """Converte pra webp+avif e devolve os caminhos públicos."""
    from PIL import Image, UnidentifiedImageError

    _slug_valido(slug)
    if tipo not in _TIPOS:
        raise ErroMidia(f"tipo deve ser um de {', '.join(_TIPOS)}")
    if len(dados) > _MAX_MB * 1024 * 1024:
        raise ErroMidia(f"arquivo tem {len(dados)/1048576:.1f} MB e o limite é {_MAX_MB} MB")

    import io
    try:
        img = Image.open(io.BytesIO(dados))
        img.load()                      # força a decodificação: só assim se sabe que é imagem
    except (UnidentifiedImageError, OSError):
        raise ErroMidia("não consegui abrir como imagem — o arquivo pode estar corrompido")

    img = _cortar_quadrado(img.convert("RGB")).resize((_LARGURA, _LARGURA), Image.LANCZOS)
    pasta = _DESTINO / slug
    pasta.mkdir(parents=True, exist_ok=True)
    saidas = {}
    for fmt, ext, kw in (("WEBP", "webp", {"quality": 82, "method": 5}),
                         ("AVIF", "avif", {"quality": 62})):
        alvo = pasta / f"{tipo}.{ext}"
        try:
            img.save(alvo, fmt, **kw)
            saidas[ext] = f"/produtos/{slug}/{tipo}.{ext}"
        except (OSError, KeyError, ValueError):
            # AVIF depende de plugin; sem ele o site segue com webp, que todo
            # navegador atual lê. Degradar aqui é melhor que recusar a foto.
            if ext == "webp":
                raise ErroMidia("falhou ao gravar a imagem convertida")
    return saidas


def salvar_video(slug: str, dados: bytes) -> dict:
    """Normaliza pra MP4 (H.264/AAC) + gera um quadro de capa.

    Vídeo de celular vem em HEVC/MOV, que o Chrome no Android não toca. Publicar o
    original seria publicar um vídeo que parte do público não vê — e ninguém
    descobriria, porque não dá erro: fica preto.
    """
    _slug_valido(slug)
    if len(dados) > _MAX_MB * 1024 * 1024:
        raise ErroMidia(f"vídeo tem {len(dados)/1048576:.1f} MB e o limite é {_MAX_MB} MB")
    if not shutil.which("ffmpeg"):
        raise ErroMidia("ffmpeg não está instalado nesta máquina")

    pasta = _DESTINO / slug
    pasta.mkdir(parents=True, exist_ok=True)
    bruto = pasta / ".entrada.tmp"
    bruto.write_bytes(dados)
    mp4, capa = pasta / "video.mp4", pasta / "video-capa.webp"
    try:
        r = subprocess.run(
            ["ffmpeg", "-y", "-i", str(bruto),
             # teto de 1080 na altura: acima disso é peso puro num vídeo de produto
             "-vf", "scale='min(1080,iw)':-2,fps=30",
             "-c:v", "libx264", "-preset", "medium", "-crf", "24",
             "-movflags", "+faststart",     # começa a tocar antes de baixar tudo
             "-c:a", "aac", "-b:a", "128k", "-t", "60", str(mp4)],
            capture_output=True, text=True, timeout=600)
        if r.returncode != 0 or not mp4.exists():
            raise ErroMidia(f"não consegui converter o vídeo: {(r.stderr or '')[-200:]}")
        subprocess.run(["ffmpeg", "-y", "-i", str(mp4), "-vf", "scale=900:-2",
                        "-frames:v", "1", str(capa)], capture_output=True, timeout=120)
    except subprocess.TimeoutExpired:
        raise ErroMidia("o vídeo demorou demais pra converter — mande um trecho menor")
    finally:
        bruto.unlink(missing_ok=True)
    return {"video": f"/produtos/{slug}/video.mp4",
            "capa": f"/produtos/{slug}/video-capa.webp" if capa.exists() else None}


def _reescrever_frontmatter(md: Path, muda) -> None:
    """Aplica `muda(dados)` no frontmatter YAML preservando o corpo do arquivo."""
    import yaml

    txt = md.read_text(encoding="utf-8")
    m = re.match(r"^---\n(.*?)\n---\n?(.*)$", txt, re.S)
    if not m:
        raise ErroMidia(f"{md.name} não tem frontmatter reconhecível")
    dados = yaml.safe_load(m.group(1)) or {}
    muda(dados)
    novo = yaml.safe_dump(dados, allow_unicode=True, sort_keys=False, width=120)
    md.write_text(f"---\n{novo}---\n{m.group(2)}", encoding="utf-8")


def apontar_foto(slug: str, tipo: str, caminhos: dict) -> None:
    """Faz o catálogo usar a foto nova e tira o `mock` quando não sobrar nenhuma."""
    md = _slug_valido(slug)
    src = caminhos.get("avif") or caminhos["webp"]

    def muda(d):
        imgs = d.get("imagens") or []
        for i in imgs:
            if i.get("tipo") == tipo:
                i["src"] = src
                break
        else:
            imgs.append({"src": src, "alt": f"Chinelo Pé Di {d.get('nome', slug)} — {tipo}",
                         "largura": _LARGURA, "altura": _LARGURA, "tipo": tipo})
        d["imagens"] = imgs
        # `mock` só cai quando NENHUMA imagem aponta mais pra /mock/. Tirar antes
        # liberaria o build com foto falsa ainda no ar — o guard existe pra isso.
        if not any("/mock/" in str(i.get("src", "")) for i in imgs):
            d["mock"] = False

    _reescrever_frontmatter(md, muda)


def apontar_video(slug: str, caminhos: dict) -> None:
    md = _slug_valido(slug)

    def muda(d):
        d["video"] = {"src": caminhos["video"], "capa": caminhos.get("capa")}

    _reescrever_frontmatter(md, muda)


def estampas_mock() -> list[str]:
    """Slugs que ainda mostram foto gerada. Leitura barata dos .md — roda antes do
    build pra decidir se vale gastar 40s compilando algo que não pode ir ao ar."""
    import yaml
    fora = []
    for md in sorted(_PRODUTOS.glob("*.md")):
        try:
            m = re.match(r"^---\n(.*?)\n---", md.read_text(encoding="utf-8"), re.S)
            d = yaml.safe_load(m.group(1)) if m else {}
        except (OSError, ValueError):
            continue
        if (d or {}).get("mock"):
            fora.append(md.stem)
    return fora


def publicar(permitir_mock: bool = False) -> dict:
    """Build + porteiro + cópia pro diretório servido. Falhou = nada vai ao ar.

    `PERMITIR_MOCK=1` era injetado FIXO aqui, com a justificativa de que "o porteiro
    é quem julga". Só que o porteiro que julga mock é o `guardMock` do build
    (src/lib/dados.ts) — `checa-lancavel.mjs` apenas AVISA. Injetar a variável
    sempre desarmava o único guarda que existia: o site foi ao ar com 8 de 8
    estampas em foto gerada, sem nada reclamar.

    Agora o padrão é o guarda ligado, e publicar com mock virou escolha explícita
    (`permitir_mock=True`) em vez de efeito colateral invisível.
    """
    if not (_REPO / "package.json").exists():
        return {"ok": False, "etapa": "repo", "saida": f"{_REPO} não parece o site"}
    mocks = estampas_mock()
    if mocks and not permitir_mock:
        return {"ok": False, "etapa": "porteiro", "mock": mocks,
                "saida": (f"{len(mocks)} estampa(s) ainda com foto gerada: {', '.join(mocks)}.\n"
                          "Suba as fotos reais (Drive → painel) ou publique como AMOSTRA "
                          "de propósito.")}
    passos = [("build", ["npm", "run", "build"]),
              ("checagem", ["node", "scripts/checa-lancavel.mjs"])]
    env = {**os.environ}
    if permitir_mock:
        env["PERMITIR_MOCK"] = "1"
    for nome, cmd in passos:
        r = subprocess.run(cmd, cwd=_REPO, capture_output=True, text=True, timeout=900, env=env)
        if r.returncode != 0:
            return {"ok": False, "etapa": nome, "saida": (r.stdout + r.stderr)[-1200:]}
    dist = _REPO / "dist"
    if not (dist / "index.html").exists():
        return {"ok": False, "etapa": "build", "saida": "dist/index.html não foi gerado"}
    _PUBLICADO.mkdir(parents=True, exist_ok=True)
    # `--delete`: o publicado passa a ser ESPELHO do build, não a soma histórica de
    # todos os builds. Com `cp -a` puro, rota removida do código continuava servida
    # pra sempre — 4 páginas mortas ficaram no ar depois que /colecao e /linha
    # saíram, e ninguém veria: elas respondem 200, com conteúdo velho.
    # `--exclude` protege o que NÃO vem do build e vive no mesmo diretório: as
    # fotos e vídeos subidos pelo painel. Sem isso, o primeiro publicar apagaria
    # todo o acervo do cliente.
    if shutil.which("rsync"):
        cmd = ["rsync", "-a", "--delete", "--exclude", "produtos/", "--exclude", ".well-known/",
               f"{dist}/", f"{_PUBLICADO}/"]
    else:
        cmd = ["cp", "-a", f"{dist}/.", f"{_PUBLICADO}/"]   # degrada pro antigo (sem poda)
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    if r.returncode != 0:
        return {"ok": False, "etapa": "publicação", "saida": r.stderr[-600:]}
    no_ar = len(list(_PUBLICADO.rglob("*.html")))
    no_build = len(list(dist.rglob("*.html")))
    return {"ok": True, "paginas": no_ar, "no_build": no_build,
            # publicou com foto gerada? o retorno diz — senão "ok" esconde o buraco
            "mock": mocks,
            # divergência aqui significa órfã sobrevivendo: aparece no painel em vez
            # de virar descoberta acidental daqui a semanas
            "orfas": max(0, no_ar - no_build), "podou": bool(shutil.which("rsync"))}


if __name__ == "__main__":
    print(json.dumps({"tipos": _TIPOS, "destino": str(_DESTINO),
                      "estampas": sorted(p.stem for p in _PRODUTOS.glob("*.md"))}, ensure_ascii=False, indent=2))
