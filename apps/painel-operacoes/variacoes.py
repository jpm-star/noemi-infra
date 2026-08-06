"""Variação de abertura em lote — pra 1.446 mensagens não saírem idênticas.

O RISCO CONCRETO: mandar o mesmo texto pra 1.446 números do mesmo chip é o padrão que
os antifraudes do WhatsApp procuram. Não é teoria — é como conta de disparo é derrubada.
Variar a redação não torna spam em não-spam, mas remove o sinal mais barato de detecção
de um envio que já é legítimo (lead real, gancho verdadeiro, opt-out honesto).

COMO: uma mensagem-base por (segmento, tier), e daí N redações da MESMA promessa. Roda
em BATCH antes do disparo e o resultado fica em disco — nunca em tempo real, porque uma
chamada de LLM no caminho do envio transforma rate limit em fila de mensagem parada.

CADA VARIAÇÃO PASSA PELO JUIZ (auditor_copy) antes de entrar. Gerar 20 e mandar as 20 só
multiplica por 20 o texto ruim: variedade sem controle é pior que repetição controlada.

Gerador: pool do gateway (10 chaves em round-robin). O Gemini que o JP indicou está sem
crédito na chave do servidor (429 "prepayment credits are depleted", medido 2026-08-06);
`GEMINI_API_KEY` com saldo faz este módulo preferi-lo sem mudar mais nada.
"""
from __future__ import annotations

import json
import logging
import os
import sys
from pathlib import Path

import auditor_copy

log = logging.getLogger(__name__)

MODELO = os.environ.get("VARIACOES_MODELO", "pool-groq")

_SYS = (
    "Você reescreve a MESMA mensagem de abertura de WhatsApp de várias formas diferentes.\n"
    "REGRAS DURAS:\n"
    "- A promessa, o gancho e o fato citado são IDÊNTICOS em todas. Só muda a redação.\n"
    "- Português falado do interior de São Paulo. Curto: no máximo 2 frases.\n"
    "- NUNCA invente fato, número, prazo, preço ou contato prévio.\n"
    "- Sem 'Olá!', sem 'Espero que esteja bem', sem emoji, sem CAIXA ALTA.\n"
    "- Cada variação tem que soar como uma PESSOA diferente escrevendo, não como sinônimo "
    "trocado: mude a ordem, o que vem primeiro, o jeito de perguntar.\n"
    '- {nome} é um marcador que fica literal no texto — nunca preencha.\n'
    'Responda SOMENTE JSON: {"variacoes":["...","..."]}'
)


def _gerar_cru(base: str, quantas: int, contexto: str) -> list[str]:
    if "/root/motor-site" not in sys.path:
        sys.path.insert(0, "/root/motor-site")
    from app.providers.llm_orquestrador import _chamar, _master
    user = (f"CONTEXTO: {contexto}\n" if contexto else "") + \
           f"MENSAGEM-BASE:\n{base}\n\nGere {quantas} variações."
    # Gemini primeiro SE tiver saldo — é o que o JP pediu; hoje a chave está zerada e a
    # exceção cai no pool sem travar nada.
    if chave := auditor_copy._do_env("GEMINI_API_KEY"):
        try:
            return _do_gemini(_SYS, user, chave, quantas)
        except Exception as e:  # noqa: BLE001
            log.info("Gemini indisponível (%s) — variações pelo pool", e)
    d = _chamar(os.environ.get("LITELLM_BASE", "http://127.0.0.1:4000") + "/v1/chat/completions",
                _master(), MODELO, _SYS, user, 0.9)   # temperatura alta: variedade é o objetivo
    return [str(v).strip() for v in (d.get("variacoes") or []) if str(v).strip()]


def _do_gemini(sys_prompt: str, user: str, chave: str, quantas: int) -> list[str]:
    import urllib.request
    corpo = json.dumps({
        "systemInstruction": {"parts": [{"text": sys_prompt}]},
        "contents": [{"parts": [{"text": user}]}],
        "generationConfig": {"temperature": 0.9, "responseMimeType": "application/json"},
    }).encode()
    url = ("https://generativelanguage.googleapis.com/v1beta/models/"
           f"{os.environ.get('GEMINI_MODELO', 'gemini-2.0-flash')}:generateContent?key={chave}")
    req = urllib.request.Request(url, data=corpo, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=90) as r:
        d = json.loads(r.read())
    txt = d["candidates"][0]["content"]["parts"][0]["text"]
    return [str(v).strip() for v in (json.loads(txt).get("variacoes") or []) if str(v).strip()][:quantas]


def gerar(base: str, quantas: int = 10, contexto: str = "", auditar: bool = True) -> dict:
    """{'base', 'aprovadas', 'reprovadas', 'juiz'}. Só `aprovadas` deve ser disparado.

    As reprovadas voltam COM o motivo em vez de sumirem: três reprovações do mesmo tipo
    apontam pro prompt, não pras três frases."""
    base = (base or "").strip()
    if not base:
        return {"base": "", "aprovadas": [], "reprovadas": [], "erro": "mensagem-base vazia"}
    try:
        cruas = _gerar_cru(base, quantas, contexto)
    except Exception as e:  # noqa: BLE001
        log.warning("geração de variações falhou: %s", e)
        return {"base": base, "aprovadas": [], "reprovadas": [],
                "erro": f"{type(e).__name__}: {e}"}
    # dedup exato: o modelo repete frase entre variações e isso derrota o propósito
    vistos, unicas = set(), []
    for v in cruas:
        k = " ".join(v.lower().split())
        if k not in vistos:
            vistos.add(k)
            unicas.append(v)
    if not auditar:
        return {"base": base, "aprovadas": unicas, "reprovadas": [], "juiz": "pulado"}
    ok, nao = [], []
    for v in unicas:
        a = auditor_copy.auditar(v, contexto=contexto or "abertura de WhatsApp para lead frio")
        (ok if a["aprovado"] else nao).append(
            {"texto": v, "nota": a["nota"],
             "motivo": "; ".join(f"{p['tipo']}: {p['por_que']}" for p in a["problemas"])})
    return {"base": base, "aprovadas": ok, "reprovadas": nao,
            "juiz": auditor_copy.MODELO_JUIZ, "gerador": MODELO}


def _caminho(seg: str, tier: str) -> Path:
    d = Path(os.environ.get("VARIACOES_DIR",
                            str(Path(__file__).resolve().parents[2] / "data" / "variacoes")))
    return d / f"{'-'.join((seg or 'geral').lower().split())}_{(tier or 'x').upper()}.json"


def salvar(seg: str, tier: str, r: dict) -> str:
    p = _caminho(seg, tier)
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(r, ensure_ascii=False, indent=1), encoding="utf-8")
        return str(p)
    except OSError as e:
        log.warning("não gravei as variações: %s", e)
        return ""


def carregar(seg: str, tier: str) -> list[str]:
    """Só os textos APROVADOS. [] quando o lote ainda não rodou — quem dispara vê lista
    vazia e usa a base, em vez de mandar uma variação que ninguém auditou."""
    p = _caminho(seg, tier)
    try:
        return [x["texto"] for x in json.loads(p.read_text(encoding="utf-8")).get("aprovadas", [])]
    except (OSError, ValueError, KeyError, TypeError):
        return []


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    assert gerar("")["erro"], "base vazia tem que reclamar"
    base = ("Oi! Aqui é a Noemi, da JPOS. Vi que a {nome} não tem site — quem busca o "
            "serviço de vocês no Google não acha. Posso te mostrar uma demo pronta?")
    r = gerar(base, quantas=6, contexto="primeiro contato com dono de pet shop, tier T1")
    print(f"\ngerador={r.get('gerador')} juiz={r.get('juiz')} "
          f"aprovadas={len(r['aprovadas'])} reprovadas={len(r['reprovadas'])}")
    for v in r["aprovadas"]:
        print(f"  OK  [{v['nota']}] {v['texto']}")
    for v in r["reprovadas"]:
        print(f"  REV [{v['nota']}] {v['texto'][:70]}  << {v['motivo'][:60]}")
