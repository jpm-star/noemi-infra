"""Editar o catálogo da loja pelo painel — sem terminal, sem abrir arquivo.

O site é estático e o catálogo vive em arquivos Markdown com frontmatter. Isso é
ótimo pra versionar e péssimo pra operar: trocar um preço exigia SSH. Aqui os
arquivos continuam sendo a verdade (o build lê deles), mas quem escreve passa a
ser o painel.

DECISÃO — COLEÇÃO É SELO, NÃO PÁGINA: um campo de texto livre no produto
("Coleção Verão") que vira etiqueta no card. Página própria de coleção competiria
com a segmentação por pessoa e reabriria o problema que a remoção de /colecao
fechou: uma porta que mostra tudo desfaz o corte da primeira decisão.

ponytail: reusa `_reescrever_frontmatter` de `pedi_midia` — o parser de YAML já
existe e já foi testado; um segundo seria duas verdades sobre o mesmo arquivo.
"""
from __future__ import annotations

import json
import re
import shutil
import unicodedata
from pathlib import Path

from pedi_midia import _PRODUTOS, _REPO, ErroMidia, _reescrever_frontmatter, _slug_valido

PUBLICOS = ("mulher", "homem", "crianca")
_LIXO = Path("/root/.pedi-lixeira")


def _slugificar(nome: str) -> str:
    s = unicodedata.normalize("NFD", (nome or "").strip().lower())
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    s = re.sub(r"[^a-z0-9]+", "-", s).strip("-")
    return s[:60]


def listar() -> list[dict]:
    """Todas as estampas com os campos editáveis. Fonte: os próprios .md."""
    import yaml
    fora = []
    for md in sorted(_PRODUTOS.glob("*.md")):
        try:
            m = re.match(r"^---\n(.*?)\n---", md.read_text(encoding="utf-8"), re.S)
            d = yaml.safe_load(m.group(1)) if m else {}
        except (OSError, ValueError):
            continue
        fora.append({
            "slug": md.stem,
            "nome": d.get("nome", md.stem),
            "descricao": d.get("descricao", ""),
            "preco": d.get("preco"),
            "publico": d.get("publico") or [],
            "colecao": d.get("colecao") or "",
            "linha": str(d.get("linha") or ""),
            "cor": d.get("cor") or "",
            "mock": bool(d.get("mock")),
            "imagens": len(d.get("imagens") or []),
        })
    return sorted(fora, key=lambda x: x["nome"])


def salvar(slug: str, campos: dict) -> dict:
    """Grava os campos editáveis de uma estampa existente.

    Só toca no que veio: ausente ≠ vazio. Mandar o formulário sem o campo `preco`
    não pode zerar o preço — senão o operador perde dado sem perceber.
    """
    md = _slug_valido(slug)

    def muda(d: dict) -> None:
        if "nome" in campos and str(campos["nome"]).strip():
            d["nome"] = str(campos["nome"]).strip()[:80]
        if "descricao" in campos:
            d["descricao"] = str(campos["descricao"]).strip()[:400]
        if "preco" in campos:
            v = campos["preco"]
            # string vazia = "tirar o preço" (volta pro padrão do site); número = preço
            if v in ("", None):
                d.pop("preco", None)
            else:
                try:
                    d["preco"] = round(float(str(v).replace(",", ".")), 2)
                except ValueError:
                    raise ErroMidia(f"preço inválido: {v!r}")
        if "publico" in campos:
            pubs = [p for p in campos["publico"] if p in PUBLICOS]
            if not pubs:
                raise ErroMidia("escolha pelo menos um público (mulher/homem/criança)")
            d["publico"] = pubs
        if "colecao" in campos:
            c = str(campos["colecao"]).strip()[:40]
            if c:
                d["colecao"] = c
            else:
                d.pop("colecao", None)

    _reescrever_frontmatter(md, muda)
    return {"ok": True, "slug": slug}


def criar(nome: str, campos: dict | None = None) -> dict:
    """Cria uma estampa nova, pronta pra receber foto.

    Nasce com `mock: true` e uma imagem placeholder: sem isso o schema do Astro
    reprova (imagens exige ao menos 1) e o build inteiro quebra — a estampa nova
    derrubaria o site em vez de aparecer nele. `mock` cai sozinho quando a primeira
    foto real sobe (ver `pedi_midia.apontar_foto`).
    """
    campos = campos or {}
    nome = (nome or "").strip()
    if len(nome) < 2:
        raise ErroMidia("dê um nome à estampa")
    slug = _slugificar(nome)
    if not slug:
        raise ErroMidia(f"não consegui gerar endereço a partir de {nome!r}")
    md = _PRODUTOS / f"{slug}.md"
    if md.exists():
        raise ErroMidia(f"já existe uma estampa com esse endereço: {slug}")

    ordem = 1 + max((x.get("ordem", 0) for x in _ordens()), default=0)
    pubs = [p for p in (campos.get("publico") or ["mulher", "homem"]) if p in PUBLICOS]
    linha = campos.get("linha") or "brisa"
    corpo = {
        "nome": nome, "descricao": campos.get("descricao") or f"Estampa {nome}, sublimada à mão em Lins/SP.",
        "linha": linha, "personalizavel": True, "destaque": False, "ordem": ordem,
        "publico": pubs or ["mulher"], "mock": True,
        "numeracoes": ["33/34", "35/36", "37/38", "39/40", "41/42", "43/44"],
        "imagens": [{"src": "/mock/onda-neon-top.avif",
                     "alt": f"Chinelo Pé Di com a estampa {nome}, vista de cima",
                     "largura": 900, "altura": 900, "tipo": "top"}],
    }
    if campos.get("preco") not in ("", None):
        corpo["preco"] = round(float(str(campos["preco"]).replace(",", ".")), 2)
    if campos.get("colecao"):
        corpo["colecao"] = str(campos["colecao"]).strip()[:40]

    import yaml
    md.write_text("---\n" + yaml.safe_dump(corpo, allow_unicode=True, sort_keys=False, width=120)
                  + "---\n", encoding="utf-8")
    return {"ok": True, "slug": slug, "nome": nome}


def _ordens() -> list[dict]:
    import yaml
    fora = []
    for md in _PRODUTOS.glob("*.md"):
        m = re.match(r"^---\n(.*?)\n---", md.read_text(encoding="utf-8"), re.S)
        if m:
            try:
                fora.append(yaml.safe_load(m.group(1)) or {})
            except ValueError:
                pass
    return fora


def remover(slug: str) -> dict:
    """Tira a estampa do catálogo. Move pra lixeira, não apaga.

    Excluir com um clique tem que ser reversível: o operador que errar o clique
    não pode perder foto e texto pra sempre. O arquivo sai de `produtos/`, então
    o build deixa de gerar a página — e o publicar (rsync --delete) remove a rota
    do servidor. É esse par que fecha o ciclo: sem a poda, a página continuaria
    servida mesmo fora do catálogo.
    """
    md = _slug_valido(slug)
    _LIXO.mkdir(parents=True, exist_ok=True)
    destino = _LIXO / f"{slug}.md"
    shutil.move(str(md), str(destino))
    fotos = _REPO / "public/produtos" / slug
    if fotos.is_dir():
        shutil.move(str(fotos), str(_LIXO / f"{slug}-fotos"))
    return {"ok": True, "slug": slug, "lixeira": str(destino)}


if __name__ == "__main__":
    itens = listar()
    assert itens and all("slug" in x and "publico" in x for x in itens)
    assert _slugificar("Coleção Verão 2026!") == "colecao-verao-2026"
    print(json.dumps(itens[:3], ensure_ascii=False, indent=2))
    print(f"{len(itens)} estampas no catálogo")
