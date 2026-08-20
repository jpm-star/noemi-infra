"""Drive → catálogo da Pé Di: troca foto gerada por foto real de produto.

O site nasceu com 8 estampas em imagem gerada (`mock: true`) e o build tem um
guarda que recusa publicar isso (`src/lib/dados.ts::guardMock`). O guarda estava
certo e o material é que faltava: sem foto real, a loja vende um produto que
ninguém viu.

FLUXO: o JP sobe as fotos no Drive numa pasta por estampa, com o NOME da estampa.
Aqui a pasta vira slug, o slug casa com o `.md` do catálogo, as imagens descem,
passam por dois filtros de qualidade e entram pelo mesmo caminho do upload manual
(`pedi_midia.salvar_foto` + `apontar_foto`) — que é quem derruba o `mock`.

DUAS DECISÕES QUE ESTE MÓDULO NÃO TOMA:
- não adivinha associação. Subpasta que não casa com estampa nenhuma é RELATADA,
  não empurrada pra estampa "parecida": errar aqui põe a foto errada numa página
  de produto, e ninguém percebe olhando o painel.
- não publica. Sincronizar mexe no catálogo; quem decide o que o cliente vê
  continua sendo o botão de publicar.

ponytail: zero SDK do Google — `shared_core.google_integ` já assina JWT de service
account com o `openssl` do sistema e fala REST por urllib.
"""
from __future__ import annotations

import os
import re
import sys
from pathlib import Path

_AQUI = Path(__file__).resolve().parent
sys.path.insert(0, str(_AQUI))
sys.path.insert(0, str(_AQUI.parents[1] / "packages"))   # shared_core, como no main.py

from pedi_catalogo import _slugificar
from pedi_midia import _PRODUTOS, ErroMidia, apontar_foto, estampas_mock, salvar_foto

RAIZ_PADRAO = os.environ.get("PEDI_DRIVE_PASTA", "Pé Di")

# O site renderiza 900x900 e `salvar_foto` faz resize pra esse lado. Aceitar uma
# foto de 400px seria mandar o Pillow AUMENTAR a imagem: sai borrada, e borrado
# não dá erro em lugar nenhum — vira produto feio no ar. O corte é quadrado e
# central, então quem manda é o MENOR lado.
LADO_MIN = 900

_TIPOS_POR_NOME = {"top": ("top", "cima", "superior"),
                   "detalhe": ("detalhe", "closeup", "close", "macro"),
                   "perfil": ("perfil", "lado", "lateral"),
                   "lifestyle": ("lifestyle", "uso", "ambiente", "modelo")}
# ordem de preenchimento quando o nome do arquivo não diz nada
_ORDEM = ("top", "detalhe", "perfil", "lifestyle")


def _catalogo() -> dict[str, str]:
    """slug → nome, lido dos próprios .md. O catálogo é a verdade; uma lista fixa
    aqui envelheceria na primeira estampa nova."""
    import yaml
    fora = {}
    for md in sorted(_PRODUTOS.glob("*.md")):
        try:
            m = re.match(r"^---\n(.*?)\n---", md.read_text(encoding="utf-8"), re.S)
            d = yaml.safe_load(m.group(1)) if m else {}
        except (OSError, ValueError):
            continue
        fora[md.stem] = (d or {}).get("nome", md.stem)
    return fora


def _tipo(nome_arquivo: str, usados: set[str]) -> str | None:
    """Que ângulo essa foto é. Nome do arquivo primeiro ('detalhe.jpg'), senão a
    próxima vaga livre. None = já tem foto de todos os 4 ângulos."""
    base = _slugificar(Path(nome_arquivo).stem)
    for tipo, palavras in _TIPOS_POR_NOME.items():
        if tipo not in usados and any(p in base for p in palavras):
            return tipo
    for tipo in _ORDEM:
        if tipo not in usados:
            return tipo
    return None


def _avaliar(dados: bytes) -> tuple[bool, str]:
    """Filtro 1 (barato, local): a imagem abre e tem pixel suficiente?"""
    import io

    from PIL import Image, UnidentifiedImageError
    try:
        img = Image.open(io.BytesIO(dados))
        img.load()
    except (UnidentifiedImageError, OSError):
        return False, "não abre como imagem (arquivo corrompido ou não é foto)"
    menor = min(img.size)
    if menor < LADO_MIN:
        return False, (f"{img.width}x{img.height} — o menor lado precisa ter ao menos "
                       f"{LADO_MIN}px; publicar isso sairia borrado")
    return True, f"{img.width}x{img.height}"


def _e_foto_de_produto(dados: bytes, nome: str) -> tuple[bool, str]:
    """Filtro 2 (visão): isso é foto de chinelo ou é print de conversa?

    A pasta da estampa também guarda copy e screenshot — material de referência que
    NÃO pode virar imagem de produto. Screenshot passa liso pelo filtro de
    resolução (print de celular tem pixel de sobra), então só olhando resolve.

    Sem OCR de propósito: o brief pede leitura por visão nativa. Se a cascata cair
    pro Tesseract, isso conta como 'não consegui ver' e a foto passa pelo critério
    de resolução — degradar é melhor que barrar foto boa com base em texto solto.
    """
    try:
        from shared_core.ai import visao
    except ImportError:
        return True, "visão indisponível (só resolução)"
    try:
        txt, fonte = visao.analisar_frames(
            [dados],
            prompt=("Esta imagem é uma FOTO DE PRODUTO de um chinelo/sandália "
                    "(o calçado aparece como assunto principal)? Responda apenas "
                    "PRODUTO, ou OUTRO se for print de tela, conversa, texto, "
                    "logotipo ou pessoa sem o calçado em destaque."))
    except Exception:  # noqa: BLE001 — visão é auxiliar; nunca derruba a sincronização
        return True, "visão falhou (só resolução)"
    if not txt or fonte in ("sem_visao", "ocr"):
        return True, "visão indisponível (só resolução)"
    if "OUTRO" in txt.upper() and "PRODUTO" not in txt.upper():
        return False, f"a visão não viu produto nisso ({nome}) — parece referência, não foto"
    return True, "produto"


def sincronizar(raiz: str | None = None, aplicar: bool = True) -> dict:
    """Varre a pasta do Drive e troca as fotos mock pelas reais.

    `aplicar=False` confere sem escrever: dá pra ver o casamento pasta→estampa e o
    que seria recusado ANTES de mexer no catálogo que está no ar.
    """
    from shared_core import google_integ as g

    nome_raiz = raiz or RAIZ_PADRAO
    rel: dict = {"raiz": nome_raiz, "aplicou": aplicar, "resolvidas": [], "sem_material": [],
                 "orfas": [], "sem_pasta": [], "rejeitadas": [],
                 "mock_antes": estampas_mock()}

    if not g.configurado():
        rel["ok"] = False
        rel["bloqueio"] = ("GOOGLE_SERVICE_ACCOUNT_JSON não está no ambiente — a "
                           "credencial existe em infra/jpos-sa.json mas não é injetada "
                           "em nenhum serviço.")
        return rel

    ok, achado = g.drive_achar_pasta(nome_raiz)
    if not ok:
        rel["ok"] = False
        rel["bloqueio"] = str(achado)
        return rel
    rel["raiz_id"] = achado

    ok, subpastas = g.drive_listar(achado, so_pastas=True)
    if not ok:
        rel["ok"] = False
        rel["bloqueio"] = f"não consegui listar a pasta: {subpastas}"
        return rel

    catalogo = _catalogo()
    casadas: dict[str, dict] = {}
    for sp in subpastas:
        slug = _slugificar(sp.get("name", ""))
        if slug in catalogo:
            casadas[slug] = sp
        else:
            # sem adivinhação: o relatório diz o nome exato pro JP renomear a pasta
            rel["orfas"].append({"pasta": sp.get("name"), "slug_gerado": slug})
    rel["sem_pasta"] = [{"slug": s, "nome": n} for s, n in catalogo.items() if s not in casadas]

    for slug, sp in sorted(casadas.items()):
        ok, arquivos = g.drive_listar(sp["id"])
        if not ok:
            rel["sem_material"].append({"slug": slug, "motivo": str(arquivos)})
            continue
        imagens = [a for a in arquivos if str(a.get("mimeType", "")).startswith("image/")]
        if not imagens:
            rel["sem_material"].append({"slug": slug, "motivo": "nenhuma imagem na pasta"})
            continue

        usados: set[str] = set()
        aceitas = 0
        for arq in sorted(imagens, key=lambda a: a.get("name", "")):
            nome = arq.get("name", "?")
            ok_dl, dados = g.drive_baixar(arq["id"])
            if not ok_dl:
                rel["rejeitadas"].append({"slug": slug, "arquivo": nome, "motivo": str(dados)})
                continue
            ok_q, motivo = _avaliar(dados)
            if not ok_q:
                rel["rejeitadas"].append({"slug": slug, "arquivo": nome, "motivo": motivo})
                continue
            ok_v, motivo_v = _e_foto_de_produto(dados, nome)
            if not ok_v:
                rel["rejeitadas"].append({"slug": slug, "arquivo": nome, "motivo": motivo_v})
                continue
            tipo = _tipo(nome, usados)
            if tipo is None:
                break                      # 4 ângulos preenchidos; o resto é acervo
            if aplicar:
                try:
                    caminhos = salvar_foto(slug, tipo, dados)
                    apontar_foto(slug, tipo, caminhos)
                except ErroMidia as e:
                    rel["rejeitadas"].append({"slug": slug, "arquivo": nome, "motivo": str(e)})
                    continue
            usados.add(tipo)
            aceitas += 1

        if aceitas:
            rel["resolvidas"].append({"slug": slug, "nome": catalogo[slug], "fotos": aceitas,
                                      "angulos": sorted(usados)})
        else:
            rel["sem_material"].append({"slug": slug,
                                        "motivo": "nenhuma imagem passou nos filtros"})

    rel["mock_depois"] = estampas_mock()
    rel["ok"] = True
    return rel


if __name__ == "__main__":
    # ângulo pelo nome do arquivo, e vaga livre quando o nome não diz nada
    assert _tipo("detalhe.jpg", set()) == "detalhe"
    assert _tipo("IMG_9021.jpg", set()) == "top"
    assert _tipo("IMG_9021.jpg", {"top"}) == "detalhe"
    assert _tipo("x.jpg", set(_ORDEM)) is None
    # a pasta "Onda Neon" tem que casar com onda-neon.md
    assert _slugificar("Onda Neon") == "onda-neon"
    assert _slugificar("Constelação") == "constelacao"

    # filtro de qualidade: pequena reprova, grande passa (é o guarda da foto borrada)
    import io

    from PIL import Image

    def _png(w, h):
        b = io.BytesIO()
        Image.new("RGB", (w, h), (120, 90, 200)).save(b, "PNG")
        return b.getvalue()

    ok1, m1 = _avaliar(_png(400, 400))
    assert ok1 is False and "900px" in m1, (ok1, m1)
    ok2, _ = _avaliar(_png(1200, 1600))
    assert ok2 is True
    ok3, m3 = _avaliar(b"nao sou imagem")
    assert ok3 is False and "não abre" in m3

    # inerte sem credencial: reporta bloqueio, não crasha e não escreve nada
    antes = os.environ.pop("GOOGLE_SERVICE_ACCOUNT_JSON", None)
    r = sincronizar()
    assert r["ok"] is False and "GOOGLE_SERVICE_ACCOUNT_JSON" in r["bloqueio"], r
    assert r["resolvidas"] == [] and r["mock_antes"] == estampas_mock()
    if antes:
        os.environ["GOOGLE_SERVICE_ACCOUNT_JSON"] = antes

    print("pedi_drive OK —", len(_catalogo()), "estampas no catálogo,",
          len(estampas_mock()), "ainda em foto gerada")
