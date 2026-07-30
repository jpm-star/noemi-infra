"""CNPJ → razão social + QSA (sócios) via BrasilAPI (grátis). stdlib only.

O gargalo do enriquecimento é o inverso — nome→CNPJ — e NÃO tem API pública
gratuita (Casa dos Dados fica atrás de Cloudflare; a rota livre é o dump da
Receita, pesado e fuzzy). Aqui a gente resolve o lado fácil: DADO um CNPJ, traz
razão social + quadro de sócios num call grátis. Enriquecimento sob demanda por
lead — o JP cola o CNPJ do lead que vai pitchar e preenche razão + sócios.
"""
from __future__ import annotations

import json
import re
import urllib.error
import urllib.request

_URL = "https://brasilapi.com.br/api/cnpj/v1/{}"
# qualificação no QSA que sugere poder de decisão (heurística p/ marcar "decide")
_DECIDE = ("administrador", "titular", "presidente", "diretor", "sócio-administrador")


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
    print("cnpj OK — parse de razão social + QSA, heurística decide, CNPJ inválido barrado")
