#!/usr/bin/env python3
"""Captação em massa de leads pela CNPJá — empresas ATIVAS, por CNAE e município.

Por que assim: a busca `/office` paginada devolve **100 registros por chamada**, já com
telefone, e-mail e endereço. Consultar CNPJ a CNPJ gastaria 1 crédito por lead; aqui uma
chamada traz 100. É a diferença entre captar centenas e captar dezenas de milhares.

Guardas (o plano é pago e finito):
  - `--ver` estima o universo ANTES de gastar (usa `count`, não baixa registro).
  - teto explícito por rodada (`--max`), pra nunca "meter o pau" sem limite.
  - 429 "not enough credits" ABORTA limpo (não gira em retry queimando tempo).
  - dedup contra o leads.db ANTES de inserir — não repovoa quem já está na fila.
  - só ATIVA (status 2) e só com telefone (phones.ex) — lead sem contato é ruído.

Uso:
    python captar_cnpja.py --ver                    # dimensiona, custo zero
    python captar_cnpja.py --rodar --max 500        # capta até 500 novos
    python captar_cnpja.py --rodar --max 5000 --cnae odontologia,academia
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sqlite3
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
LEADS_DB = os.environ.get("LEADS_DB", str(Path(__file__).resolve().parents[2] / "data" / "leads.db"))
_API = "https://api.cnpja.com/office"
PAGINA = 100  # teto do endpoint: 100 registros por chamada

# CNAEs dos segmentos que a JPOS atende (o motor tem receita/tema pra todos eles).
CNAE = {
    "odontologia": 8630504, "medico": 8630503, "fisioterapia": 8650004,
    "academia": 9313100, "cabeleireiro": 9602501, "estetica": 9602502,
    "imobiliaria": 6821801, "advocacia": 6911701,
}
# Região de atuação (mesmas cidades da base atual + vizinhas do mesmo eixo).
CIDADES = ["Bauru", "Marília", "Assis", "Botucatu", "Jaú", "Presidente Prudente",
           "Araçatuba", "Birigui", "Adamantina", "São Carlos", "Ribeirão Preto",
           "Araraquara", "Lins", "Avaré", "Tupã", "Catanduva", "São José do Rio Preto"]


class SemCredito(Exception):
    """CNPJá sem créditos: aborta a rodada em vez de girar em retry."""


def _key() -> str:
    k = os.environ.get("CNPJA_API_KEY", "").strip()
    if not k:
        raise RuntimeError("CNPJA_API_KEY ausente no ambiente")
    return k


_ULTIMA = [0.0]
_INTERVALO = float(os.environ.get("CNPJA_INTERVALO_S", "0.9"))  # ~66 req/min < teto de 80


def _get(params: dict, timeout: float = 45) -> dict:
    # ritmo: a API corta em 80 req/janela. Espaçar na origem evita transformar metade
    # das chamadas em 429+retry (que gasta MAIS tempo total que só ir devagar).
    espera = _INTERVALO - (time.monotonic() - _ULTIMA[0])
    if espera > 0:
        time.sleep(espera)
    _ULTIMA[0] = time.monotonic()
    qs = urllib.parse.urlencode(params, doseq=True)
    req = urllib.request.Request(f"{_API}?{qs}",
                                 headers={"Authorization": _key(), "User-Agent": "noemi-captador"})
    for tentativa in range(4):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.load(r) or {}
        except urllib.error.HTTPError as e:
            corpo = ""
            try:
                corpo = e.read().decode()[:200]
            except Exception:  # noqa: BLE001
                pass
            if e.code == 429 and "credit" in corpo.lower():
                raise SemCredito(corpo)
            if e.code == 429 and tentativa < 6:  # rate-limit real: espera e repete
                # a CNPJá informa o ttl no corpo ({"limit":80,"ttl":13}) — usar o valor
                # dela é melhor que chutar backoff: espera o exato e volta.
                ttl = 0
                try:
                    ttl = int((json.loads(corpo) or {}).get("ttl") or 0)
                except Exception:  # noqa: BLE001
                    ttl = 0
                time.sleep(max(ttl + 1, int(e.headers.get("Retry-After") or 0) or 3 * (tentativa + 1)))
                continue
            raise RuntimeError(f"HTTP {e.code}: {corpo}")
        except Exception as e:  # noqa: BLE001
            if tentativa >= 2:
                raise RuntimeError(str(e)[:150])
            time.sleep(3)
    return {}


def _ibge(cidade: str, uf: str = "SP") -> int | None:
    import cnpj  # reusa o resolvedor com cache + fix de gzip
    return cnpj.codigo_ibge(cidade, uf)


def _filtros(municipio: int, cnae: int) -> dict:
    return {"status.id.in": 2, "address.municipality.in": municipio,
            "mainActivity.id.in": cnae, "phones.ex": "true"}


def dimensionar(cnaes: list[str], cidades: list[str]) -> dict:
    """Quantos leads existem por cidade×CNAE. Usa `count` — NÃO baixa registros."""
    total = 0
    linhas = []
    for cidade in cidades:
        mun = _ibge(cidade)
        if not mun:
            linhas.append((cidade, "?", "sem código IBGE"))
            continue
        soma = 0
        for nome in cnaes:
            d = _get({**_filtros(mun, CNAE[nome]), "limit": 1})
            soma += int(d.get("count") or 0)
        linhas.append((cidade, mun, soma))
        total += soma
    return {"total": total, "linhas": linhas}


def _telefone(rec: dict) -> str:
    for p in (rec.get("phones") or []):
        area, num = str(p.get("area") or ""), str(p.get("number") or "")
        if area and num:
            return f"{area}{num}"
    return ""


def _existentes() -> set[str]:
    """Telefones (8 últimos dígitos) já na base — dedup antes de inserir."""
    fora: set[str] = set()
    with sqlite3.connect(LEADS_DB) as c:
        for tabela, col in (("tracker_prospects", "telefone"), ("leads_alvo", "telefone")):
            try:
                for (t,) in c.execute(f"SELECT {col} FROM {tabela}"):
                    d = re.sub(r"\D", "", str(t or ""))[-8:]
                    if d:
                        fora.add(d)
            except sqlite3.Error:
                continue
    return fora


def _tabela(c: sqlite3.Connection) -> None:
    c.execute("""CREATE TABLE IF NOT EXISTS leads_cnpja (
        cnpj TEXT PRIMARY KEY, razao_social TEXT, fantasia TEXT, telefone TEXT, email TEXT,
        cidade TEXT, uf TEXT, cnae TEXT, segmento TEXT, socios TEXT, capturado_em TEXT)""")
    c.commit()


def captar(cnaes: list[str], cidades: list[str], maximo: int = 500) -> dict:
    """Pagina a busca e grava os NOVOS. Para no teto, no fim da fila ou sem crédito."""
    ja = _existentes()
    novos = repetidos = 0
    from datetime import datetime, timezone
    agora = datetime.now(timezone.utc).isoformat()
    with sqlite3.connect(LEADS_DB) as c:
        _tabela(c)
        for (cnpj_,) in c.execute("SELECT cnpj FROM leads_cnpja"):
            ja.add(str(cnpj_)[-8:])
        for cidade in cidades:
            mun = _ibge(cidade)
            if not mun:
                continue
            for nome in cnaes:
                cursor = None
                while novos < maximo:
                    # PAGINAÇÃO: o `token` é EXCLUSIVO — mandar os filtros junto dá 400
                    # ("token is mutually exclusive with other properties"). A 1ª página
                    # leva os filtros; as seguintes levam SÓ o token.
                    p = ({"token": cursor} if cursor
                         else {**_filtros(mun, CNAE[nome]), "limit": PAGINA})
                    try:
                        d = _get(p)
                    except SemCredito:
                        c.commit()
                        return {"novos": novos, "repetidos": repetidos, "parou": "sem crédito"}
                    except RuntimeError as e:
                        return {"novos": novos, "repetidos": repetidos, "parou": f"erro: {e}"}
                    recs = d.get("records") or []
                    if not recs:
                        break
                    for r in recs:
                        tel = _telefone(r)
                        chave = re.sub(r"\D", "", tel)[-8:]
                        if not tel or (chave and chave in ja):
                            repetidos += 1
                            continue
                        ja.add(chave)
                        comp = r.get("company") or {}
                        end = r.get("address") or {}
                        socios = [{"nome": (m.get("person") or {}).get("name", ""),
                                   "cargo": (m.get("role") or {}).get("text", "")}
                                  for m in (comp.get("members") or [])]
                        c.execute(
                            "INSERT OR IGNORE INTO leads_cnpja (cnpj,razao_social,fantasia,telefone,"
                            "email,cidade,uf,cnae,segmento,socios,capturado_em) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                            (str(r.get("taxId") or ""), comp.get("name", ""), r.get("alias") or "",
                             tel, ((r.get("emails") or [{}])[0] or {}).get("address", ""),
                             end.get("city", ""), end.get("state", ""), str(CNAE[nome]), nome,
                             json.dumps(socios, ensure_ascii=False), agora))
                        novos += 1
                        if novos >= maximo:
                            break
                    c.commit()
                    cursor = d.get("next")
                    if not cursor:
                        break
    return {"novos": novos, "repetidos": repetidos, "parou": "teto" if novos >= maximo else "fim da fila"}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ver", action="store_true", help="dimensiona o universo (custo zero)")
    ap.add_argument("--rodar", action="store_true")
    ap.add_argument("--max", type=int, default=500)
    ap.add_argument("--cnae", default=",".join(CNAE))
    ap.add_argument("--cidades", default=",".join(CIDADES))
    a = ap.parse_args()
    cnaes = [x.strip() for x in a.cnae.split(",") if x.strip() in CNAE]
    cidades = [x.strip() for x in a.cidades.split(",") if x.strip()]
    if a.ver or not a.rodar:
        d = dimensionar(cnaes, cidades)
        for cidade, mun, n in d["linhas"]:
            print(f"  {cidade:24s} {str(mun):9s} {n}")
        print(f"\n  UNIVERSO: {d['total']} empresas ativas com telefone "
              f"({len(cnaes)} CNAEs × {len(cidades)} cidades)")
        print(f"  ~{-(-d['total'] // PAGINA)} chamadas de API (100 por chamada)")
        return
    r = captar(cnaes, cidades, a.max)
    print(f"\n  {r['novos']} novos · {r['repetidos']} já existiam · parou: {r['parou']}")


if __name__ == "__main__":
    main()
