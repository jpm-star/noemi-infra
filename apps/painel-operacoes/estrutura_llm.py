"""A estrutura da página é decidida pelo LLM na hora, a partir de CONCEITOS gerais.

MUDANÇA DE MODELO (JP, 2026-08-07). Antes: receitas fatiadas por segmento — cada nicho
tinha sua lista fechada de ordens, e a biblioteca de referência só alimentava o gerador
se o rótulo de segmento batesse. O custo disso apareceu inteiro na auditoria de ontem:

  · 39 das 91 referências aprovadas (42,9%) estavam em segmentos SEM receita e nunca
    eram consultadas por lead nenhum — não por serem ruins, por causa do rótulo;
  · 10 delas eram clínicas brasileiras de verdade, marcadas como 'servicos' na ingestão;
  · imobiliária tinha 821 leads com nome utilizável e UMA referência;
  · e um segmento novo exigia escrever receita à mão antes de gerar qualquer coisa.

Nada disso era problema de conteúdo. Era o segmento agindo como cerca.

AGORA: os conceitos são gerais e ficam todos disponíveis. "Preço antes de tudo tira a
objeção nº1" não é um fato sobre academia — é sobre quem hesita por preço, em qualquer
ramo. O LLM recebe todos, mais o que se sabe do negócio, e monta a ordem para AQUELE
lead. Segmento vira contexto (uma frase no prompt), não filtro.

O QUE NÃO MUDA: a lista de blocos possíveis (`ORDEM_DEFAULT`) segue fechada. O LLM
escolhe a ORDEM e o que omitir; não inventa seção que o template não sabe renderizar.
Saída inválida cai na ordem determinística de sempre — o site sai, com a estrutura de
antes, nunca quebrado.
"""
from __future__ import annotations

import json
import logging
import os
import sys
from pathlib import Path

log = logging.getLogger(__name__)

sys.path.insert(0, str(Path(__file__).resolve().parent))
import receitas  # noqa: E402

MODELO = os.environ.get("ESTRUTURA_MODELO", "analise")


def conceitos(con=None, limite: int = 40) -> list[str]:
    """Todos os conceitos de estrutura conhecidos, SEM filtro de segmento.

    Junta os curados (`RECEITAS[*].porque` — hipóteses escritas à mão) com os que o JP
    subiu como referência aprovada. Dedup por texto: o mesmo argumento escrito duas vezes
    não vale duas vezes no prompt, só encarece."""
    fora: list[str] = []
    vistos: set[str] = set()

    def _add(txt: str) -> None:
        t = " ".join(str(txt or "").split())
        k = t.lower()[:80]
        if len(t) > 12 and k not in vistos:
            vistos.add(k)
            fora.append(t)

    for lista in receitas.RECEITAS.values():
        for r in lista:
            _add(r.get("porque", ""))
    try:  # referências aprovadas de QUALQUER segmento — o rótulo deixou de decidir
        c = receitas._db(con)
        for r in c.execute("SELECT tag, receita FROM templates_referencia "
                           "WHERE aprovada=1 AND tipo='estrutura' ORDER BY id DESC LIMIT 200"):
            try:
                rec = json.loads(r[1]) if isinstance(r[1], str) else (r[1] or {})
            except (ValueError, TypeError):
                rec = {}
            _add(rec.get("porque") or rec.get("conceito") or "")
    except Exception:  # noqa: BLE001 — banco fora não pode travar geração
        pass
    return fora[:limite]


_SYS = (
    "Você decide a ORDEM DAS SEÇÕES de uma landing page de conversão, para UM negócio "
    "específico. Recebe: o negócio, os blocos disponíveis e uma lista de conceitos sobre o "
    "que costuma converter.\n"
    "REGRAS:\n"
    "- Use SOMENTE os blocos da lista. Não invente seção.\n"
    "- Pode OMITIR blocos que não servem a este negócio — página curta e certa vence longa.\n"
    "- 'formulario' é sempre o último.\n"
    "- Os conceitos são hipóteses gerais, não regras: escolha os que se aplicam A ESTE "
    "negócio e ignore o resto. Não force um conceito que não cabe.\n"
    "- O campo 'porque' explica a decisão em UMA frase, citando o que no negócio a "
    "motivou. Nunca frase genérica que serviria pra qualquer cliente.\n"
    'Responda SOMENTE JSON: {"ordem":["..."],"hero":"video|foto|texto","porque":"..."}'
)


def _valida(d: dict) -> dict | None:
    """Normaliza a saída do LLM ou devolve None. Aqui é onde a alucinação morre."""
    ordem = [str(x).strip() for x in (d.get("ordem") or []) if str(x).strip()]
    ordem = [b for b in ordem if b in receitas.BLOCOS]        # bloco inventado sai fora
    ordem = list(dict.fromkeys(ordem))                        # sem repetição
    if len(ordem) < 3:
        return None
    if "formulario" in ordem:                                 # contato por último, sempre
        ordem = [b for b in ordem if b != "formulario"] + ["formulario"]
    hero = str(d.get("hero") or "").strip().lower()
    return {"ordem": ordem, "hero": hero if hero in ("video", "foto", "texto") else "",
            "porque": str(d.get("porque") or "").strip()[:200] or "decidido pelo LLM",
            "nome": "llm", "origem": "llm"}


def escolher(nicho: str, empresa: str = "", contexto: str = "", con=None) -> dict:
    """Estrutura para ESTE lead, decidida na hora. Cai na determinística se algo falhar.

    O fallback não é detalhe: um LLM fora do ar não pode impedir uma demo de sair. A
    ordem de sempre é pior que a escolhida, e infinitamente melhor que nenhuma."""
    cs = conceitos(con)
    if not cs:
        return receitas.escolher(nicho, con=con)
    user = "\n".join([
        f"NEGÓCIO: {empresa or '(sem nome)'}",
        f"RAMO: {nicho or '(não informado)'}",
        (f"O QUE SE SABE: {contexto[:600]}" if contexto else ""),
        "",
        "BLOCOS DISPONÍVEIS: " + ", ".join(receitas.BLOCOS),
        "",
        "CONCEITOS (hipóteses gerais sobre o que converte):",
        *(f"- {c}" for c in cs),
    ])
    try:
        if "/root/motor-site" not in sys.path:
            sys.path.insert(0, "/root/motor-site")
        from app.providers.llm_orquestrador import _chamar, _master
        d = _chamar(os.environ.get("LITELLM_BASE", "http://127.0.0.1:4000") + "/v1/chat/completions",
                    _master(), MODELO, _SYS, user, 0.4)
    except Exception as e:  # noqa: BLE001
        log.warning("estrutura pelo LLM falhou (%s); ordem determinística", e)
        return receitas.escolher(nicho, con=con)
    r = _valida(d if isinstance(d, dict) else {})
    if r is None:
        log.warning("LLM devolveu ordem inválida para %r; ordem determinística", nicho)
        return receitas.escolher(nicho, con=con)
    return r


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    # self-check da validação (puro, sem rede)
    assert _valida({"ordem": ["sobre"]}) is None, "ordem curta demais tem que cair"
    assert _valida({"ordem": []}) is None
    v = _valida({"ordem": ["formulario", "sobre", "preco", "inexistente", "sobre"], "hero": "X"})
    assert v["ordem"] == ["sobre", "preco", "formulario"], v          # bloco falso fora,
    assert v["hero"] == "", v                                          # dedup, form no fim
    cs = conceitos()
    print(f"conceitos disponíveis (sem segmento): {len(cs)}")
    for c in cs[:4]:
        print("  -", c[:90])
    print()
    for nicho, emp in (("clínica odontológica", "Implante Real"), ("imobiliária", "Moradas")):
        r = escolher(nicho, emp)
        print(f"{emp} [{nicho}] origem={r['origem']}")
        print("   ordem:", " › ".join(r["ordem"]))
        print("   porquê:", r["porque"][:120])
