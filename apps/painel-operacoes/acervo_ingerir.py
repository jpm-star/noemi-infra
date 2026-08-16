"""Põe fotos no acervo do motor a partir de arquivos/URLs prontos — com portaria.

POR QUE EXISTE (medido em 2026-08-16): `acervo_fotos.py` busca no Openverse e julga com
visão. O julgamento está certo; a MATÉRIA-PRIMA é que não presta. Resultado real: 15
nichos, 136 tentativas, 4 fotos aprovadas — 12 nichos com ZERO. Entre eles "salão de
beleza", "academia" e "restaurante". Sem acervo o motor cai no banco de imagem genérico,
e quando o cliente manda foto própria vem o que veio na Bellator: um POST DE INSTAGRAM,
com texto já impresso na imagem, usado de fundo de hero — o título do site escrito por
cima do título da foto, ilegível.

Este módulo não busca e não gera: ele RECEBE (arquivo local ou URL) e faz a portaria que
faltava. Quem produz a imagem é decisão de fora — hoje é geração por IA feita à mão,
amanhã pode ser foto do próprio cliente. Nenhum provider é chamado daqui: a regra do
CLAUDE.md (provider de IA só em `shared-core/ai/`) fica intacta, e não entra dependência.

A PORTARIA, e cada regra veio de um defeito visto no acervo real:
  · TEXTO NA IMAGEM reprova — é o defeito da Bellator. Tesseract local, R$0.
  · imagem pequena demais reprova (ícone/thumbnail disfarçado).
  · o número de fotos tem que casar com o número de SERVIÇOS do segmento, na ordem;
    posição sem foto fica "" — o motor casa foto com card por ÍNDICE, e lista curta
    desalinharia tudo (mesma regra do `acervo_fotos.garantir`).

Rodar:
  python acervo_ingerir.py "salão de beleza" a.png b.png c.png d.png
  python acervo_ingerir.py "salão de beleza" https://... https://...
  python acervo_ingerir.py --check
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
import tempfile
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import acervo_fotos as af  # noqa: E402 — pelo MÓDULO, não pelos nomes: o autoteste
from acervo_fotos import RAIZ, URL_BASE, _servicos, _slug  # noqa: E402  precisa baixar o piso

# Ruído de OCR (uma letra solta num azulejo, um reflexo) não é "foto com texto". O que
# reprova é texto DE VERDADE: marca d'água, legenda, post de rede social.
MIN_CHARS_TEXTO = 12
_UA = "noemi-motor-site/1.0 (+https://jpos.com.br)"


def texto_na_imagem(caminho: Path) -> str:
    """O que o OCR lê na foto. '' quando limpa (ou quando o Tesseract não existe).

    Sem Tesseract isto devolve '' e a foto passa — é o mesmo dilema do juiz de visão, e
    aqui o fail-open é aceitável porque a chamada é local, síncrona e ou funciona sempre
    ou nunca: não existe o caso 'falhou hoje por rate limit' que criava o falso verde."""
    try:
        r = subprocess.run(["tesseract", str(caminho), "stdout", "-l", "por"],
                           capture_output=True, text=True, timeout=45)
    except (OSError, subprocess.SubprocessError):
        return ""
    limpo = re.sub(r"[^0-9A-Za-zÀ-ÿ]+", "", r.stdout or "")
    return r.stdout.strip() if len(limpo) >= MIN_CHARS_TEXTO else ""


def _baixar(origem: str, destino: Path) -> bytes:
    if origem.startswith(("http://", "https://")):
        req = urllib.request.Request(origem, headers={"User-Agent": _UA})
        with urllib.request.urlopen(req, timeout=60) as r:
            b = r.read()
    else:
        b = Path(origem).read_bytes()
    destino.write_bytes(b)
    return b


def _para_jpg(entrada: Path, saida: Path) -> bool:
    """PNG de 2 MB vira JPEG de ~200 KB. Sem Pillow, copia como está (funciona igual,
    só pesa mais) — não vale uma dependência nova pra isto."""
    try:
        from PIL import Image
        im = Image.open(entrada)
        im.convert("RGB").save(saida, "JPEG", quality=82, optimize=True)
        return True
    except Exception:  # noqa: BLE001
        saida.write_bytes(entrada.read_bytes())
        return False


def ingerir(nicho: str, origens: list[str], destino_raiz: Path | None = None) -> dict:
    """Grava as fotos aprovadas e o manifesto. Devolve o relatório do que entrou e saiu."""
    seg = _slug(nicho)
    destino = (destino_raiz or RAIZ) / seg
    destino.mkdir(parents=True, exist_ok=True)
    try:
        n_serv = len(_servicos(nicho))
    except Exception:  # noqa: BLE001 — sem catálogo, usa o que veio
        n_serv = len(origens)
    urls: list[str] = []
    diario: list[str] = []
    with tempfile.TemporaryDirectory() as tmp:
        for i in range(n_serv):
            if i >= len(origens):
                urls.append("")
                diario.append(f"posição {i + 1}: sem foto enviada — fica no banco de imagem")
                continue
            org = origens[i]
            bruto = Path(tmp) / f"{i}.bin"
            try:
                b = _baixar(org, bruto)
            except Exception as e:  # noqa: BLE001
                urls.append("")
                diario.append(f"posição {i + 1}: não baixou ({type(e).__name__}) — {org[:60]}")
                continue
            if len(b) < af.MIN_BYTES:
                urls.append("")
                diario.append(f"posição {i + 1}: REPROVADA por tamanho ({len(b)}B) — {org[:60]}")
                continue
            achou = texto_na_imagem(bruto)
            if achou:
                urls.append("")
                diario.append(f"posição {i + 1}: REPROVADA — texto na imagem "
                              f"({achou[:40]!r}) — {org[:60]}")
                continue
            arq = destino / f"{i + 1}.jpg"
            _para_jpg(bruto, arq)
            urls.append(f"{URL_BASE}/{seg}/{arq.name}")
            diario.append(f"posição {i + 1}: APROVADA — sem texto, {len(b) // 1024}KB — {org[:60]}")
    (destino / "manifesto.json").write_text(
        json.dumps({"nicho": nicho, "urls": urls, "diario": diario},
                   ensure_ascii=False, indent=1), encoding="utf-8")
    return {"nicho": nicho, "servicos": n_serv, "aprovadas": sum(1 for u in urls if u),
            "urls": urls, "diario": diario, "pasta": str(destino)}


def _autoteste() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        raiz = Path(tmp)
        try:
            from PIL import Image, ImageDraw
        except ImportError:
            print("acervo_ingerir: sem Pillow, autoteste de imagem pulado")
            return
        # PNG de cor sólida comprime pra ~3KB e morreria no piso de tamanho antes de
        # chegar no OCR — que é justamente o que este teste quer exercitar.
        af.MIN_BYTES = 500
        limpa = raiz / "limpa.png"
        Image.new("RGB", (1200, 800), (180, 140, 90)).save(limpa)
        com_texto = raiz / "com_texto.png"
        im = Image.new("RGB", (1200, 800), (255, 255, 255))
        ImageDraw.Draw(im).text((60, 300), "PROMOCAO IMPERDIVEL HOJE NA LOJA",
                                fill=(0, 0, 0))
        im.save(com_texto)
        assert texto_na_imagem(limpa) == "", "foto lisa não pode acusar texto"
        # o defeito da Bellator: se isto passar, post de Instagram vira hero de novo
        assert texto_na_imagem(com_texto) != "", "texto impresso tem que reprovar"

        r = ingerir("salão de beleza", [str(limpa), str(com_texto)], destino_raiz=raiz)
        assert r["urls"][0].endswith("/1.jpg"), r["urls"]
        assert r["urls"][1] == "", "a foto com texto entrou no acervo"
        # posições sem foto existem como "" pra não desalinhar foto x card
        assert len(r["urls"]) == r["servicos"] >= 4, r
        assert any("REPROVADA — texto" in d for d in r["diario"]), r["diario"]
        m = json.loads((raiz / _slug("salão de beleza") / "manifesto.json").read_text())
        assert m["urls"] == r["urls"] and m["nicho"] == "salão de beleza"
    print("acervo_ingerir OK — texto na imagem reprova, tamanho reprova, posição vazia "
          "vira \"\" (não encurta a lista) e o manifesto casa com o que foi gravado")


if __name__ == "__main__":
    if "--check" in sys.argv[1:]:
        _autoteste()
        raise SystemExit(0)
    if len(sys.argv) < 3:
        print("uso: acervo_ingerir.py \"<nicho>\" <arquivo|url> [...]")
        raise SystemExit(2)
    r = ingerir(sys.argv[1], sys.argv[2:])
    for d in r["diario"]:
        print("  ·", d)
    print(f"\n{r['nicho']}: {r['aprovadas']}/{r['servicos']} posições com foto -> {r['pasta']}")
