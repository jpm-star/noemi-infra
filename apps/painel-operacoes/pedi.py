"""Pé Di (chinelospedi.com) no painel: tráfego + o que falta pra loja vender.

Tráfego reusa o `beacon` que já media o jpos — o agregador sempre foi multi-site,
só nunca teve um segundo site. Zero tabela nova.

A parte que importa é a OUTRA: uma vitrine pode estar 100% no ar, bonita e rápida,
e mesmo assim não vender. Foi o que aconteceu de 30/07 a 10/08 — 17 páginas
publicadas apontando pra `wa.me/5514000000000`. Por isso aqui não se mede só
visita: mede-se se o caminho da venda existe.

ponytail: lê os arquivos do repo direto (json + frontmatter por regex). Sem parser
de YAML, sem import do Astro — são 4 campos num formato que a gente mesmo escreve.
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path

import beacon

_REPO = Path(os.environ.get("PEDI_REPO", "/root/pedi-site"))
_PUBLICADO = Path(os.environ.get("PEDI_PUBLICADO", "/var/www/pedi"))
_SITE = "pedi"


def _config() -> dict:
    try:
        return json.loads((_REPO / "src/content/site.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _produtos() -> list[dict]:
    """Estampas do catálogo. `mock: true` = ainda é foto gerada, não produto real."""
    fora = []
    pasta = _REPO / "src/content/produtos"
    if not pasta.is_dir():
        return fora
    for md in sorted(pasta.glob("*.md")):
        try:
            txt = md.read_text(encoding="utf-8")
        except OSError:
            continue
        pegar = lambda campo: (re.search(rf"^{campo}:\s*\"?([^\"\n]+)\"?", txt, re.M) or [None, ""])[1].strip()
        fora.append({
            "slug": md.stem,
            "nome": pegar("nome") or md.stem,
            "linha": pegar("linha"),
            "mock": pegar("mock") == "true",
            "descricao_pendente": "TODO" in txt,
        })
    return fora


def _pendencias(cfg: dict, produtos: list[dict]) -> list[dict]:
    """O que impede a loja de vender. Ordenado por gravidade, não por facilidade."""
    p = []
    num = re.sub(r"\D", "", str(cfg.get("whatsapp_numero", "")))
    if re.search(r"0{5,}", num) or not re.fullmatch(r"55\d{2}9?\d{8}", num or ""):
        p.append({"nivel": "bloqueio", "o_que": "WhatsApp é número de teste",
                  "efeito": "todo botão de compra do site leva a um número que não existe",
                  "resolve": "trocar whatsapp_numero em src/content/site.json"})
    mocks = [x for x in produtos if x["mock"]]
    if mocks:
        p.append({"nivel": "alto", "o_que": f"{len(mocks)} de {len(produtos)} estampas com foto gerada",
                  "efeito": "o cliente não vê o produto real que vai receber",
                  "resolve": "subir foto de verdade e tirar mock:true"})
    ig = str(cfg.get("redes", {}).get("instagram", ""))
    if re.fullmatch(r"https://(www\.)?instagram\.com/?", ig):
        p.append({"nivel": "medio", "o_que": "Instagram aponta pra raiz",
                  "efeito": "o link manda o visitante pro feed dele, não pro seu perfil",
                  "resolve": "pôr a URL do perfil em redes.instagram"})
    pend = [x for x in produtos if x["descricao_pendente"]]
    if pend:
        p.append({"nivel": "medio", "o_que": f"{len(pend)} estampas com descrição TODO",
                  "efeito": "texto de placeholder aparece pro cliente e pro Google",
                  "resolve": "escrever a descrição real de cada estampa"})
    return p


def _deploy() -> dict:
    """O que está NO AR é o que foi buildado? Deploy aqui é cópia manual pra
    /var/www/pedi, então o disco divergir do repo é a falha silenciosa esperada."""
    vivo, fonte = _PUBLICADO / "index.html", _REPO / "dist/index.html"
    if not vivo.exists():
        return {"estado": "não publicado", "no_ar_em": None}
    m_vivo = vivo.stat().st_mtime
    d = {"estado": "no ar", "no_ar_em": int(m_vivo)}
    if fonte.exists():
        atrasado = fonte.stat().st_mtime - m_vivo
        d["build_em"] = int(fonte.stat().st_mtime)
        # 5 min de folga: cópia de arquivos não é atômica e sempre deixa segundos
        # de diferença — alarmar nisso seria ruído todo deploy.
        if atrasado > 300:
            d["estado"] = "defasado"
            d["atraso_h"] = round(atrasado / 3600, 1)
    return d


def resumo() -> dict:
    produtos = _produtos()
    cfg = _config()
    return {
        "trafego": beacon.resumo(_SITE),
        "catalogo": {
            "estampas": len(produtos) or None,
            "com_foto_real": sum(1 for x in produtos if not x["mock"]) if produtos else None,
            "linhas": sorted({x["linha"] for x in produtos if x["linha"]}),
        },
        # lista pro seletor de upload: sai do próprio catálogo, então nunca
        # descola do que existe de verdade
        "estampas": [{"slug": x["slug"], "nome": x["nome"], "mock": x["mock"]} for x in produtos],
        "deploy": _deploy(),
        "pendencias": _pendencias(cfg, produtos),
        "url": cfg.get("dominio", "https://chinelospedi.com"),
    }


if __name__ == "__main__":  # self-check contra o repo real
    r = resumo()
    assert "trafego" in r and "pendencias" in r
    assert r["catalogo"]["estampas"] is None or r["catalogo"]["estampas"] > 0
    print(json.dumps(r, ensure_ascii=False, indent=2))
