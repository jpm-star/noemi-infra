"""Gate de amostra: ninguém dispara pros 1.446 sem passar por 10-15 primeiro.

A regra que este módulo existe pra impor: um lote grande só sai depois que uma AMOSTRA
do MESMO material passa por três ângulos independentes. Não é burocracia — é a diferença
entre descobrir um problema em 12 mensagens e descobrir em 1.446, num canal onde a
segunda opção também custa a reputação do número.

OS TRÊS ÂNGULOS (o pedido do JP, um agente por lente — redundância não acha o que
diversidade acha):
  · compliance — isto parece spam ou golpe pra quem recebe sem ter pedido nada?
  · comercial  — a oferta está clara? tem UM CTA só? dá pra responder sem reler?
  · realismo   — "se chegasse pra mim, eu responderia?" — a pergunta que mata copy
                 tecnicamente correta e comercialmente morta.

O VEREDITO É CONSERVADOR de propósito: qualquer ângulo reprovando trava o lote inteiro.
Um gate que libera "por maioria" é um gate que libera o problema que só um dos três
sabia ver — e o ângulo minoritário costuma ser justamente o especialista naquele risco.

ponytail: reusa `auditor_copy` (mesmo transporte, mesmo juiz != autor). O que muda por
ângulo é a PERGUNTA, e é só disso que precisa.
"""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import auditor_copy

log = logging.getLogger(__name__)
SP = ZoneInfo("America/Sao_Paulo")

TAMANHO_AMOSTRA = int(os.environ.get("QA_AMOSTRA", "12"))   # dentro do 10-15 pedido

ANGULOS: dict[str, str] = {
    "compliance": (
        "Você recebe esta mensagem no WhatsApp sem nunca ter pedido contato. "
        "Ela parece spam, golpe ou disparo em massa? Procure urgência falsa, contato "
        "prévio forjado, promessa grande demais, link suspeito e falta de saída clara. "
        "REPROVE se você denunciaria ou bloquearia o número."),
    "comercial": (
        "Avalie como material de vendas: a oferta está clara em uma leitura? Há UM "
        "único pedido de ação (não dois)? O que a pessoa ganha está dito antes do que "
        "ela tem que fazer? REPROVE se houver mais de um CTA, se a oferta for vaga, "
        "ou se for preciso reler pra entender o que está sendo oferecido."),
    "realismo": (
        "Você é o dono de um negócio pequeno no interior, ocupado, no meio do "
        "expediente. Chegou esta mensagem. Você responderia? REPROVE se você deixaria "
        "sem resposta, se soa a vendedor, se é longa demais pra ler no corredor, ou se "
        "não diz em 5 segundos o que quer de você."),
}


def _amostra(itens: list[dict], n: int) -> list[dict]:
    """Amostra ESPALHADA (passo fixo), não as N primeiras.

    As primeiras costumam ser do mesmo segmento e da mesma cidade — aprovar as 12
    primeiras e concluir "o lote está bom" é medir uma fatia e chamar de todo. Passo
    fixo em vez de aleatório porque o resultado precisa ser reproduzível: o JP tem que
    conseguir rodar de novo e ver a MESMA amostra que reprovou."""
    if len(itens) <= n:
        return list(itens)
    passo = len(itens) / n
    return [itens[int(i * passo)] for i in range(n)]


def rodar(itens: list[dict], campo: str = "texto", contexto: str = "",
          n: int = TAMANHO_AMOSTRA) -> dict:
    """Roda os três ângulos sobre uma amostra. `itens` = [{campo: texto, ...}].

    Devolve o relatório e o veredito. `liberado` só é True quando NENHUM ângulo achou
    problema em NENHUM item da amostra."""
    amostra = _amostra(itens, n)
    if not amostra:
        return {"liberado": False, "erro": "nada pra auditar", "amostra": 0,
                "universo": len(itens)}
    por_angulo, problemas_totais = {}, 0
    for nome, pergunta in ANGULOS.items():
        ctx = f"{contexto}\nÂNGULO DESTA AUDITORIA: {pergunta}" if contexto else pergunta
        r = auditor_copy.auditar_lote(amostra, campo=campo, contexto=ctx)
        por_angulo[nome] = {
            "aprovados": r["aprovados"], "reprovados": r["reprovados"],
            "por_tipo": r["por_tipo"],
            # só os reprovados vão em detalhe: o que passou não precisa de leitura
            "exemplos": [{"texto": x["texto"][:220],
                          "motivo": "; ".join(f"{p['tipo']}: {p['por_que']}"
                                              for p in x["auditoria"]["problemas"])}
                         for x in r["itens"] if not x["auditoria"]["aprovado"]][:5],
        }
        problemas_totais += r["reprovados"]
    liberado = problemas_totais == 0
    return {
        "gerado_em": datetime.now(SP).strftime("%d/%m/%Y %H:%M"),
        "universo": len(itens), "amostra": len(amostra),
        "juiz": auditor_copy.MODELO_JUIZ,
        "por_angulo": por_angulo,
        "reprovacoes": problemas_totais,
        "liberado": liberado,
        "veredito": ("LIBERADO para o lote completo — os três ângulos passaram na amostra."
                     if liberado else
                     f"BLOQUEADO: {problemas_totais} reprovação(ões) na amostra de "
                     f"{len(amostra)}. Corrija o PROMPT (não as frases uma a uma) e "
                     f"rode de novo antes de disparar nos {len(itens)}."),
    }


def salvar(r: dict, nome: str = "ultimo") -> str:
    p = Path(os.environ.get("QA_DIR", str(Path(__file__).resolve().parents[2] / "data" / "qa"))) \
        / f"gate_{nome}.json"
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(r, ensure_ascii=False, indent=1), encoding="utf-8")
        return str(p)
    except OSError:
        return ""


def markdown(r: dict) -> str:
    """O relatório em texto — é o que o JP lê antes de autorizar o disparo."""
    if r.get("erro"):
        return f"# QA — sem resultado\n\n{r['erro']}\n"
    L = [f"# QA gate — amostra antes do disparo",
         "", f"- **Universo:** {r['universo']} mensagens · **amostra auditada:** {r['amostra']}",
         f"- **Juiz:** `{r['juiz']}` (modelo diferente do que escreveu)",
         f"- **Gerado:** {r['gerado_em']}", "",
         f"## {'✅' if r['liberado'] else '⛔'} {r['veredito']}", ""]
    for nome, d in r["por_angulo"].items():
        L.append(f"### {nome} — {d['aprovados']} ok / {d['reprovados']} reprovados")
        if d["por_tipo"]:
            L.append("Tipos: " + ", ".join(f"`{k}` ×{v}" for k, v in d["por_tipo"].items()))
        for e in d["exemplos"]:
            L.append(f"- “{e['texto']}”  \n  ↳ {e['motivo']}")
        L.append("")
    return "\n".join(L)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    assert _amostra([], 5) == []
    assert len(_amostra([{"t": i} for i in range(100)], 12)) == 12
    assert _amostra([{"t": i} for i in range(3)], 12) == [{"t": 0}, {"t": 1}, {"t": 2}]
    # amostra espalhada: pega do começo ao fim, não os 12 primeiros
    esp = _amostra([{"t": i} for i in range(100)], 12)
    assert esp[0]["t"] == 0 and esp[-1]["t"] > 80, esp[-1]
    print("qa_gate OK — amostragem confere\n")
    import variacoes
    base = ("Oi! Aqui é a Noemi, da JPOS. Vi que a {nome} não tem site — quem busca o "
            "serviço de vocês no Google não acha. Posso te mostrar uma demo pronta?")
    v = variacoes.gerar(base, quantas=8, contexto="primeiro contato, dono de pet shop T1",
                        auditar=False)
    itens = [{"texto": t} for t in v["aprovadas"]] or [{"texto": base}]
    r = rodar(itens, contexto="mensagem de abertura fria no WhatsApp, JPOS vendendo site",
              n=min(TAMANHO_AMOSTRA, len(itens)))
    print(markdown(r))
    print("relatório:", salvar(r))
