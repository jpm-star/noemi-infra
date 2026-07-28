"""Alerta vermelho → e-mail (task 3). Carrega os 5 variantes de prompts/alertas_email.md
(versionado, não hardcoded), escolhe por tipo/recorrência do achado, formata e envia via
shared_core.email_envio. INERTE sem credencial — fica pronto esperando o JP colar SMTP.

Calendar fica em BACKLOG (mesmo tipo de credencial, service account, depois).
"""
from __future__ import annotations

import re
import sys
from datetime import datetime, timezone
from pathlib import Path

_AQUI = Path(__file__).resolve().parent
sys.path.insert(0, str(_AQUI.parents[1] / "packages"))  # shared_core no path (roda solo tb)

_ARQ = Path(__file__).resolve().parents[2] / "prompts" / "alertas_email.md"
_COMERCIAL = re.compile(r"\b(venda|vendas|cliente|clientes|convers|lead|orçamento|preço|fecha)\b", re.I)
_TECNICO = re.compile(r"\b(infra|deploy|servidor|banco|token|erro|api|container|instância|migra)\b", re.I)


def carregar_variantes() -> dict:
    """Parseia o .md → {nome: {assunto, corpo}}. '' se o arquivo sumir (nunca crasha)."""
    try:
        txt = _ARQ.read_text(encoding="utf-8")
    except OSError:
        return {}
    out = {}
    for bloco in txt.split("## variante:")[1:]:
        linhas = bloco.splitlines()
        nome = linhas[0].strip()
        corpo_all = "\n".join(linhas[1:]).split("\n---")[0]  # até o próximo separador
        m = re.search(r"^Assunto:\s*(.+)$", corpo_all, re.M)
        assunto = m.group(1).strip() if m else ""
        corpo = corpo_all[m.end():].strip() if m else corpo_all.strip()
        if nome and assunto:
            out[nome] = {"assunto": assunto, "corpo": corpo}
    return out


def _recorrente(achado: dict) -> bool:
    """Padrão já visto 3+ vezes? (heurística no texto: '3x', '4 vezes', score 9-10)."""
    t = f"{achado.get('achado','')} {achado.get('origem','')}".lower()
    if re.search(r"\b([3-9]|\d\d)\s*(x|vezes|vez)\b", t):
        return True
    return achado.get("score", 0) >= 9


def _escolher(achado: dict, n_vermelhos: int) -> str:
    if n_vermelhos > 1:
        return "consolidado"
    if _recorrente(achado):
        return "recorrencia"
    t = f"{achado.get('achado','')} {achado.get('origem','')} {achado.get('acao','')}"
    if _COMERCIAL.search(t):
        return "comercial"
    if _TECNICO.search(t):
        return "tecnica"
    return "padrao"


def _fmt(tpl: dict, achado: dict, ts: str) -> tuple[str, str]:
    titulo = (achado.get("achado", "") or "")[:60]
    campos = {"titulo_achado": titulo, "achado_completo": achado.get("achado", ""),
              "fonte": achado.get("origem", "—"), "timestamp": ts}
    return _preencher(tpl["assunto"], campos), _preencher(tpl["corpo"], campos)


def _preencher(s: str, campos: dict) -> str:
    for k, v in campos.items():
        s = s.replace("{" + k + "}", str(v))
    return s


def alertar_vermelhos(itens: list[dict]) -> dict:
    """Dispara alerta pros achados VERMELHOS. >1 no dia => 1 e-mail consolidado.
    INERTE sem credencial: devolve o que TERIA enviado, sem falhar. Não é deadline —
    é log de quando apareceu (a mensagem-base diz isso)."""
    from shared_core import email_envio
    vermelhos = [i for i in (itens or []) if i.get("nivel") == "vermelho"]
    if not vermelhos:
        return {"vermelhos": 0, "enviados": 0}
    ts = datetime.now(timezone.utc).astimezone().strftime("%d/%m/%Y %H:%M")
    variantes = carregar_variantes()
    para = None  # usa EMAIL_ALERTA_PARA
    if len(vermelhos) > 1 and "consolidado" in variantes:
        tpl = variantes["consolidado"]
        lista = "\n".join(f"• {v.get('achado','')} (origem: {v.get('origem','—')})" for v in vermelhos)
        assunto = _preencher(tpl["assunto"], {"n_vermelhos": len(vermelhos)})
        corpo = _preencher(tpl["corpo"], {"lista_achados": lista, "timestamp": ts,
                                          "n_vermelhos": len(vermelhos)})
        msgs = [(assunto, corpo)]
    else:
        msgs = [_fmt(variantes.get(_escolher(v, len(vermelhos)), variantes.get("padrao", {"assunto": "", "corpo": ""})), v, ts)
                for v in vermelhos]
    configurado = email_envio.configurado()
    enviados, prontos = 0, []
    for assunto, corpo in msgs:
        if configurado:
            ok, _ = email_envio.enviar(assunto, corpo, para)
            enviados += 1 if ok else 0
        prontos.append(assunto)
    return {"vermelhos": len(vermelhos), "configurado": configurado,
            "enviados": enviados, "teria_enviado": prontos if not configurado else []}


if __name__ == "__main__":  # self-check: parse 5 variantes + seleção + inerte sem credencial
    v = carregar_variantes()
    assert set(v) == {"padrao", "tecnica", "comercial", "recorrencia", "consolidado"}, list(v)
    assert all(v[k]["assunto"].startswith("[JPOS Radar]") for k in v), v

    assert _escolher({"achado": "erro de deploy no container", "score": 6}, 1) == "tecnica"
    assert _escolher({"achado": "perdendo cliente que pergunta preço", "score": 6}, 1) == "comercial"
    assert _escolher({"achado": "padrão apareceu 4x", "score": 8}, 1) == "recorrencia"
    assert _escolher({"achado": "algo neutro", "score": 5}, 1) == "padrao"
    assert _escolher({"achado": "qualquer", "score": 5}, 3) == "consolidado"

    a, c = _fmt(v["padrao"], {"achado": "clientes somem na sexta", "origem": "SDR", "score": 8}, "28/07 03:00")
    assert "clientes somem na sexta" in c and "SDR" in c and "28/07 03:00" in c, c

    # inerte sem credencial: não envia, mas diz o que TERIA enviado
    import os
    for k in ("SMTP_HOST", "SMTP_USER", "SMTP_PASS"):
        os.environ.pop(k, None)
    r = alertar_vermelhos([{"nivel": "vermelho", "achado": "risco real", "origem": "x", "score": 9},
                           {"nivel": "amarelo", "achado": "ignora", "score": 5}])
    assert r["vermelhos"] == 1 and r["configurado"] is False and r["enviados"] == 0 and r["teria_enviado"], r
    print("alertas OK — 5 variantes, seleção por tipo/recorrência, consolidado, inerte sem credencial")
