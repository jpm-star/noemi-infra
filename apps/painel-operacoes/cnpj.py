"""CNPJ ⇄ dados. Dois lados:

  • buscar(cnpj)            CNPJ → razão + QSA           BrasilAPI, grátis, exato.
  • procurar_por_nome(...)  nome+cidade → CNPJ + tudo    CNPJá, pago, FUZZY.

O lado nome→CNPJ é lossy: a clínica é registrada como "Ana Souza Odontologia
LTDA" e o Places mostra o fantasia "Sorriso Perfeito". Por isso o matcher é
ESTRITO — filtra por cidade/UF, pontua o nome do lead contra razão+fantasia e
DESCARTA quando o melhor não passa do corte ou há empate ambíguo. Vazio é melhor
que CNPJ errado numa lista de ligação. Key: env CNPJA_API_KEY (nunca no código).
"""
from __future__ import annotations

import json
import os
import re
import unicodedata
import urllib.error
import urllib.parse
import urllib.request

_URL = "https://brasilapi.com.br/api/cnpj/v1/{}"
_CNPJA = "https://api.cnpja.com/office"
# qualificação no QSA que sugere poder de decisão (heurística p/ marcar "decide")
_DECIDE = ("administrador", "titular", "presidente", "diretor", "sócio-administrador")
_CORTE = float(os.environ.get("CNPJA_CORTE", "0.34"))   # Jaccard mínimo p/ aceitar match


class _SemCredito(Exception):
    """CNPJá sem créditos (429 permanente). O lote para de vez ao invés de girar à toa."""
_MARGEM = float(os.environ.get("CNPJA_MARGEM", "0.12"))  # 1º tem que superar o 2º por isso
# tokens genéricos que não distinguem uma empresa da outra (não contam no score)
_STOP = {"clinica", "clinica", "odontologia", "odontologica", "consultorio", "ltda", "me",
         "epp", "eireli", "sa", "s", "a", "de", "da", "do", "e", "dr", "dra", "centro",
         "servicos", "servico", "comercio", "empresa", "cia", "the", "and"}


def _parse(dados: dict) -> dict:
    """Extrai razão social + sócios do JSON da BrasilAPI. Puro (testável offline)."""
    qsa = []
    for s in (dados.get("qsa") or []):
        nome = str(s.get("nome_socio") or s.get("nome") or "").strip()
        if not nome:
            continue
        qual = str(s.get("qualificacao_socio") or s.get("qual") or "").strip()
        qsa.append({"nome": nome, "qualificacao": qual,
                    "decide": any(t in qual.lower() for t in _DECIDE)})
    return {"ok": True, "razao_social": str(dados.get("razao_social") or "").strip(),
            "nome_fantasia": str(dados.get("nome_fantasia") or "").strip(),
            "qsa": qsa, "qsa_disponivel": bool(qsa)}


def buscar(cnpj: str, timeout: float = 12) -> dict:
    """CNPJ (qualquer formato) → {ok, razao_social, qsa[...]}. Erros honestos."""
    d = re.sub(r"\D", "", cnpj or "")
    if len(d) != 14:
        return {"ok": False, "erro": "CNPJ precisa ter 14 dígitos"}
    try:
        req = urllib.request.Request(_URL.format(d), headers={"User-Agent": "noemi-painel"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            dados = json.load(r)
    except urllib.error.HTTPError as e:
        return {"ok": False, "erro": "CNPJ não encontrado" if e.code == 404 else f"BrasilAPI erro {e.code}"}
    except Exception as e:  # rede/timeout — best-effort, nunca derruba o painel
        return {"ok": False, "erro": f"falha de rede: {e}"}
    out = _parse(dados)
    out["cnpj"] = d
    return out


def _sa(s: str) -> str:
    """minúsculo sem acento."""
    return "".join(c for c in unicodedata.normalize("NFKD", str(s or "").lower())
                   if not unicodedata.combining(c))


def _toks(s: str) -> set:
    """tokens significativos (>=3 letras, fora da stoplist genérica)."""
    return {t for t in re.findall(r"[a-z0-9]{3,}", _sa(s)) if t not in _STOP}


def _limpar_nome(nome: str) -> str:
    """Nome do Places vem sujo ('DVI Radiologia: Exames, Lins SP'). Pega o núcleo
    antes do 1º separador (':', ' - ', ',') — é onde mora a marca."""
    n = re.split(r"[:,]| - | – ", str(nome or ""), 1)[0].strip()
    return n or str(nome or "").strip()


def _score(nome_lead: str, razao: str, fantasia: str) -> float:
    """Jaccard dos tokens do lead contra razão+fantasia COMBINADOS. Combinar (em vez
    de max) faz o candidato que casa nos dois campos ganhar de quem só casa no fantasia
    — desempata franquia (razão da unidade local) vs quem só compartilha a marca."""
    a = _toks(_limpar_nome(nome_lead))
    b = _toks(razao) | _toks(fantasia)
    return len(a & b) / len(a | b) if (a and b) else 0.0


def _qsa_de(members: list) -> list:
    """company.members da CNPJá → mesmo formato do QSA da BrasilAPI."""
    out = []
    for m in (members or []):
        nome = str((m.get("person") or {}).get("name") or "").strip()
        if not nome:
            continue
        qual = str((m.get("role") or {}).get("text") or "").strip()
        out.append({"nome": nome, "qualificacao": qual,
                    "decide": any(t in qual.lower() for t in _DECIDE)})
    return out


def procurar_por_nome(nome: str, cidade: str = "", uf: str = "", *,
                      limite: int = 10, timeout: float = 25, _fetch=None) -> dict:
    """nome (+cidade/uf) → melhor CNPJ com match ESTRITO. `_fetch(nome,limite)->records`
    injetável p/ teste. Retorna {ok, cnpj, razao_social, nome_fantasia, cidade, uf,
    confianca, qsa, motivo}. ok=False quando descarta (ambíguo/fraco/nada)."""
    nucleo = _limpar_nome(nome)
    mun = codigo_ibge(cidade, uf or "SP") if cidade else None
    recs = _fetch(nucleo, limite) if _fetch else _fetch_cnpja(nucleo, limite, timeout, municipio=mun)
    if recs is None:
        return {"ok": False, "motivo": "erro de rede/api"}
    cid = _sa(cidade).split("/")[0].strip()
    uf_n = _sa(uf).strip()
    cand = []
    for r in recs:
        end = r.get("address") or {}
        comp = r.get("company") or {}
        # filtro geográfico: se o lead tem cidade, o candidato TEM que bater
        if cid and _sa(end.get("city", "")) != cid:
            continue
        if uf_n and _sa(end.get("state", "")) not in (uf_n, ""):
            continue
        sc = _score(nome, comp.get("name", ""), r.get("alias", ""))
        cand.append((sc, r))
    if not cand:
        return {"ok": False, "motivo": "nenhum candidato na cidade"}
    cand.sort(key=lambda x: x[0], reverse=True)
    melhor_sc, melhor = cand[0]
    segundo_sc = cand[1][0] if len(cand) > 1 else 0.0
    if melhor_sc < _CORTE:
        return {"ok": False, "motivo": f"match fraco ({melhor_sc:.2f}<{_CORTE})",
                "confianca": round(melhor_sc, 2)}
    if melhor_sc - segundo_sc < _MARGEM and segundo_sc >= _CORTE:
        return {"ok": False, "motivo": f"ambíguo ({melhor_sc:.2f} vs {segundo_sc:.2f})",
                "confianca": round(melhor_sc, 2)}
    comp = melhor.get("company") or {}
    end = melhor.get("address") or {}
    return {"ok": True, "cnpj": str(melhor.get("taxId") or ""),
            "razao_social": str(comp.get("name") or "").strip(),
            "nome_fantasia": str(melhor.get("alias") or "").strip(),
            "cidade": str(end.get("city") or ""), "uf": str(end.get("state") or ""),
            "status": str((melhor.get("status") or {}).get("text") or ""),
            "qsa": _qsa_de(comp.get("members")), "confianca": round(melhor_sc, 2),
            "motivo": "ok"}


_IBGE_CACHE: dict[str, int] = {}


def codigo_ibge(cidade: str, uf: str = "SP") -> int | None:
    """Cidade -> código IBGE do município, via API pública do IBGE (grátis, sem key).

    Existe porque a busca da CNPJá é textual NACIONAL: procurar "Dentista em Bauru"
    devolve candidatos de Ponta Grossa, João Pessoa e Brasília. Sem filtrar município
    NO SERVIDOR, o match local descarta tudo e o acerto vira ~0% (era esse o bug).
    Cache em memória: 1 chamada por UF, não por lead."""
    cid = _sa(cidade).strip()
    if not cid:
        return None
    uf = (uf or "SP").strip().upper()[:2] or "SP"
    if uf not in _IBGE_CACHE:
        try:
            u = f"https://servicodados.ibge.gov.br/api/v1/localidades/estados/{uf}/municipios"
            # O IBGE responde GZIP mesmo pedindo identity, e o urllib NÃO descomprime
            # sozinho (UnicodeDecodeError no magic byte 0x8b). curl mascarava isso.
            # Detecta pelo magic e descomprime — funciona comprimido ou não.
            req = urllib.request.Request(u, headers={"User-Agent": "noemi-painel"})
            with urllib.request.urlopen(req, timeout=20) as r:
                bruto = r.read()
            if bruto[:2] == b"\x1f\x8b":
                import gzip as _gz
                bruto = _gz.decompress(bruto)
            _IBGE_CACHE[uf] = {_sa(m["nome"]): m["id"] for m in json.loads(bruto.decode("utf-8"))}
        except Exception:  # noqa: BLE001 — IBGE fora => segue sem filtro (degrada, não quebra)
            _IBGE_CACHE[uf] = {}
    return (_IBGE_CACHE.get(uf) or {}).get(cid)


def _fetch_cnpja(nucleo: str, limite: int, timeout: float, _sleep=None, municipio: int | None = None):
    """GET /office?names.in=<núcleo>[&address.municipality.in=<ibge>]. records[] ou None.
    Faz backoff em 429 (rate-limit) respeitando Retry-After — necessário em lote."""
    import time
    key = os.environ.get("CNPJA_API_KEY", "").strip()
    if not key:
        return None
    sleep = _sleep or time.sleep
    params = {"names.in": nucleo[:40], "limit": str(limite)}
    if municipio:  # filtra NO SERVIDOR: sem isto a busca é nacional e o match morre
        params["address.municipality.in"] = str(municipio)
    qs = urllib.parse.urlencode(params)
    req = urllib.request.Request(f"{_CNPJA}?{qs}",
                                 headers={"Authorization": key, "User-Agent": "noemi-painel"})
    for tentativa in range(4):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return (json.load(r) or {}).get("records") or []
        except urllib.error.HTTPError as e:
            corpo = ""
            try:
                corpo = e.read().decode()[:200]
            except Exception:  # noqa: BLE001
                pass
            # 429 "not enough credits" é PERMANENTE (quota esgotada) — aborta já, não faz
            # backoff (senão vira 30s/lead à toa). Só 429 de rate-limit real dá retry.
            if e.code == 429 and "credit" not in corpo.lower() and tentativa < 3:
                espera = int(e.headers.get("Retry-After") or 0) or 5 * (tentativa + 1)
                sleep(min(espera, 60))
                continue
            if e.code == 429 and "credit" in corpo.lower():
                raise _SemCredito()  # sinaliza o lote a parar de vez
            return None
        except Exception:  # noqa: BLE001 — rede/timeout → None, o chamador degrada
            return None
    return None


if __name__ == "__main__":  # self-check offline (mocka a resposta da BrasilAPI)
    fake = {"razao_social": "CLINICA X LTDA", "nome_fantasia": "Clínica X",
            "qsa": [{"nome_socio": "ANA SOUZA", "qualificacao_socio": "Sócio-Administrador"},
                    {"nome_socio": "JOAO LIMA", "qualificacao_socio": "Sócio"},
                    {"nome_socio": "", "qualificacao_socio": "x"}]}  # sem nome = ignorado
    r = _parse(fake)
    assert r["razao_social"] == "CLINICA X LTDA" and r["qsa_disponivel"]
    assert len(r["qsa"]) == 2 and r["qsa"][0]["decide"] is True and r["qsa"][1]["decide"] is False
    assert _parse({"qsa": []})["qsa_disponivel"] is False  # MEI/simplificado sem QSA
    assert buscar("123")["ok"] is False  # CNPJ inválido não chama rede

    # --- matcher nome→CNPJ (mockado, sem rede) ---
    def mock(nome, lim):  # 2 candidatos na mesma cidade; um casa forte, outro não
        return [
            {"taxId": "36357991000101", "alias": "Bom Sorrir",
             "company": {"name": "CLINICA BOM SORRIR LTDA",
                         "members": [{"person": {"name": "Luana Pires"}, "role": {"text": "Administrador"}}]},
             "address": {"city": "Janaúba", "state": "MG"}, "status": {"text": "Ativa"}},
            {"taxId": "11111111000191", "alias": "Padaria Pão", "company": {"name": "PADARIA PAO QUENTE ME"},
             "address": {"city": "Janaúba", "state": "MG"}, "status": {"text": "Ativa"}},
        ]
    ok = procurar_por_nome("Clínica Bom Sorrir", "Janaúba", "MG", _fetch=mock)
    assert ok["ok"] and ok["cnpj"] == "36357991000101", ok
    assert ok["qsa"] and ok["qsa"][0]["decide"] is True   # Administrador = decide
    # cidade que não bate → descarta (proteção geográfica)
    assert procurar_por_nome("Bom Sorrir", "São Paulo", "SP", _fetch=mock)["ok"] is False
    # nome que não casa com ninguém forte → descarta (não chuta)
    assert procurar_por_nome("Auto Peças Silva", "Janaúba", "MG", _fetch=mock)["ok"] is False
    # limpeza de nome sujo do Places
    assert _limpar_nome("DVI Radiologia: Exames, Lins SP") == "DVI Radiologia"
    print("cnpj OK — BrasilAPI (CNPJ→QSA) + CNPJá matcher estrito (nome→CNPJ, descarta ambíguo)")
