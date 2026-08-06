"""Auditoria adversarial de tudo que vai sair falando com um prospect.

O gerador de texto é otimista com o próprio texto: pedir "seja coloquial" e depois pedir
pra ele avaliar se ficou coloquial dá sempre "sim". Por isso o JUIZ é outro modelo, de
outra arquitetura, e com uma instrução invertida: a tarefa dele é REPROVAR, não aprovar.

O que ele procura (as três coisas que custam dinheiro de verdade):
  · TOM ROBÔ — "Entendo perfeitamente, o tempo é valioso e é importante priorizar" é
    prosa de manual. Ninguém fala assim ao telefone, e o dono desliga.
  · PROMESSA — capacidade de produto que não existe ("a Noemi filtra só as urgentes"),
    resultado de venda garantido, prazo inventado, preço chutado.
  · CHEIRO DE GOLPE — urgência falsa, contato prévio forjado, "oportunidade única",
    linguagem de spam. Num canal de WhatsApp isso não é só feio: é risco de denúncia.

Onde é usado: objeções do cold call (script_call), variações de abertura em massa
(variacoes) e o gate de amostra antes de qualquer disparo grande.

DeepSeek era o juiz previsto e não há chave no servidor — o slot está aqui (DEEPSEEK_API_KEY
no .env liga sozinho). Até lá o juiz é um gpt-oss pelo gateway: arquitetura diferente do
llama que escreve, que é a parte que importa. Um juiz que é o próprio autor não é juiz.
"""
from __future__ import annotations

import json
import logging
import os
import sys
import time
from pathlib import Path

log = logging.getLogger(__name__)

# Juiz != autor. `site-copy`/`analise` (llama-3.3) escrevem; `juiz` (gpt-oss-120b sobre as
# 10 chaves do pool) julga. Trocar aqui é trocar o juiz — nunca aponte pro modelo do gerador.
MODELO_JUIZ = os.environ.get("AUDITOR_MODELO", "juiz")  # 10 chaves em round-robin no gateway

_SYS = (
    "Você é um auditor CÉTICO de comunicação comercial no Brasil. Sua função é REPROVAR. "
    "Você recebe um texto que uma empresa vai enviar ou falar para um dono de negócio "
    "pequeno que NÃO pediu contato. Encontre o que está errado.\n\n"
    "REPROVE quando houver:\n"
    "- tom_robotico: frase que ninguém fala em voz alta. Prosa de manual, conector "
    "corporativo ('perfeitamente', 'de forma que', 'podemos explorar como'), resposta "
    "com mais de 2 frases, ou educação artificial.\n"
    "- promessa: capacidade de produto afirmada sem prova, resultado de venda garantido "
    "('vai aumentar seu faturamento'), prazo ou preço inventado, número sem fonte.\n"
    "- golpe: urgência falsa, contato prévio que não existiu ('conforme conversamos'), "
    "'oportunidade única', 'última chance', promessa de gratuidade com pegadinha, "
    "qualquer coisa que soe a spam de WhatsApp.\n"
    "- ofensa: dizer na cara do dono que o negócio dele é ruim, malfeito ou mal avaliado.\n\n"
    "Seja duro. Texto medíocre que 'dá pra usar' deve ser REPROVADO — o custo de mandar "
    "uma mensagem ruim para 1.400 pessoas é maior que o de reescrever uma.\n"
    'Responda SOMENTE JSON: {"aprovado":true|false,"problemas":[{"tipo":"tom_robotico|'
    'promessa|golpe|ofensa","trecho":"o trecho exato","por_que":"até 12 palavras"}],'
    '"nota":0-10}. Sem problema encontrado: aprovado=true e problemas=[].'
)


def _julgar(prompt_user: str) -> dict:
    """Uma chamada ao juiz. Levanta — quem chama decide o que fazer sem veredito."""
    if "/root/motor-site" not in sys.path:
        sys.path.insert(0, "/root/motor-site")
    from app.providers.llm_orquestrador import _chamar, _master

    if chave := _do_env("DEEPSEEK_API_KEY"):   # slot preferido, quando o JP puser a chave
        return _chamar("https://api.deepseek.com/chat/completions", chave, "deepseek-chat",
                       _SYS, prompt_user, 0.2)
    if mk := _master():
        return _chamar(os.environ.get("LITELLM_BASE", "http://127.0.0.1:4000") + "/v1/chat/completions",
                       mk, MODELO_JUIZ, _SYS, prompt_user, 0.2)
    raise RuntimeError("sem juiz disponível (nem DEEPSEEK_API_KEY nem gateway)")


def _do_env(nome: str) -> str:
    for env in ("/root/noemi-infra/.env", "/root/noemi-infra/infra/.env", "/root/sdr-motor/.env"):
        p = Path(env)
        if not p.is_file():
            continue
        for l in p.read_text(errors="ignore").splitlines():
            if l.strip().startswith(f"{nome}="):
                return l.split("=", 1)[1].strip().strip('"').strip("'")
    return ""


_CARTUCHO = os.environ.get("CARTUCHO_JPOS",
                           "/root/sdr-motor/backend/cartuchos/jpos_prospeccao.json")


def contrato_produto() -> str:
    """A fronteira do que o produto FAZ e do que nunca se promete, tirada do cartucho.

    Sem isto o juiz só reconhece exagero óbvio ("aumento de 300%") e deixa passar a
    promessa plausível — na primeira rodada real ele aprovou com nota 9 uma resposta
    que dizia que a Noemi "filtra as mensagens e responde só as urgentes". Soa razoável
    e é justamente por isso que passa. O cartucho já mantém essa lista (`produto_vende`)
    e é a fonte de verdade da operação; duplicá-la aqui seria criar uma segunda verdade."""
    try:
        d = json.loads(Path(_CARTUCHO).read_text(encoding="utf-8")).get("produto_vende") or {}
    except (OSError, ValueError):
        return ""
    faz = "; ".join(str(x) for x in (d.get("faz_hoje") or []))
    nunca = "; ".join(str(x) for x in (d.get("nunca_prometer") or []))
    if not faz and not nunca:
        return ""
    return (f"\nO PRODUTO SÓ FAZ ISTO HOJE: {faz}.\n"
            f"NUNCA PODE PROMETER: {nunca}.\n"
            "Qualquer capacidade afirmada fora da primeira lista é 'promessa', mesmo que "
            "soe razoável e mesmo que o texto esteja bem escrito.")


def auditar(texto: str, contexto: str = "") -> dict:
    """{'aprovado', 'problemas', 'nota', 'juiz'}.

    SEM VEREDITO É REPROVAÇÃO. Se o juiz não responde, o texto não passa: um gate que
    libera quando o verificador cai não é gate — e o custo de segurar um envio é zero
    perto do custo de mandar 1.400 mensagens que soam golpe."""
    t = (texto or "").strip()
    if not t:
        return {"aprovado": False, "problemas": [{"tipo": "vazio", "trecho": "", "por_que": "texto vazio"}],
                "nota": 0, "juiz": "-"}
    user = ((f"CONTEXTO: {contexto}\n" if contexto else "") + contrato_produto()
            + f"\nTEXTO A AUDITAR:\n{t}")
    # RETRY COM ESPERA. Um gate roda em rajada (12 itens × 3 ângulos = 36 chamadas) e o
    # 429 chega no meio. Sem retry, o lote inteiro voltava "sem_juiz" — tecnicamente o
    # comportamento seguro, mas inútil: o JP via 36 reprovações que não diziam nada sobre
    # o texto. Auditoria roda offline, então esperar é o recurso mais barato disponível.
    erro = None
    for tentativa in range(3):
        try:
            d = _julgar(user)
            break
        except Exception as e:  # noqa: BLE001
            erro = e
            if tentativa < 2:
                time.sleep(4 * (tentativa + 1) ** 2)   # 4s, 16s
    else:
        log.warning("juiz indisponível após 3 tentativas: %s", erro)
        return {"aprovado": False, "nota": 0, "juiz": "indisponível",
                "problemas": [{"tipo": "sem_juiz", "trecho": "",
                               "por_que": f"auditoria não rodou ({type(erro).__name__})"}]}
    probs = [{"tipo": str(p.get("tipo", "?")), "trecho": str(p.get("trecho", ""))[:160],
              "por_que": str(p.get("por_que", ""))[:120]}
             for p in (d.get("problemas") or []) if isinstance(p, dict)]
    # o veredito vem dos PROBLEMAS, não do campo `aprovado`: modelo às vezes lista três
    # defeitos e marca aprovado=true no mesmo JSON. A evidência ganha da autodeclaração.
    return {"aprovado": not probs, "problemas": probs,
            "nota": int(d.get("nota") or 0), "juiz": MODELO_JUIZ}


def auditar_lote(itens: list[dict], campo: str = "texto", contexto: str = "") -> dict:
    """Audita uma amostra e resume. `itens` = [{campo: texto, ...}].

    Devolve o mesmo relatório que o gate de disparo consome: quantos passaram, quais
    problemas apareceram e com que frequência — porque 3 reprovações do MESMO tipo
    significam consertar o prompt, não consertar as 3 mensagens."""
    fora, por_tipo = [], {}
    for i, it in enumerate(itens):
        r = auditar(str(it.get(campo, "")), contexto)
        for p in r["problemas"]:
            por_tipo[p["tipo"]] = por_tipo.get(p["tipo"], 0) + 1
        fora.append({**{k: v for k, v in it.items() if k != campo},
                     "texto": str(it.get(campo, "")), "auditoria": r, "i": i})
    aprovados = sum(1 for x in fora if x["auditoria"]["aprovado"])
    return {"total": len(fora), "aprovados": aprovados,
            "reprovados": len(fora) - aprovados, "por_tipo": por_tipo, "itens": fora}


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    assert auditar("")["aprovado"] is False, "texto vazio nunca passa"
    ruim = ("Entendo perfeitamente, o tempo é valioso e é importante priorizar, mas talvez "
            "possamos encontrar uma maneira de integrar o site e o atendimento no WhatsApp "
            "de forma que não aumente sua carga de trabalho.")
    bom = "Imagino. Por isso a demo é pronta — você só olha e diz se serve."
    golpe = ("OPORTUNIDADE ÚNICA! Conforme conversamos, sua vaga expira HOJE. "
             "Garantimos aumento de 300% no faturamento.")
    for nome, txt in (("prosa de manual", ruim), ("fala de gente", bom), ("golpe", golpe)):
        r = auditar(txt, contexto="resposta a objeção numa ligação fria para dono de clínica")
        print(f"\n[{nome}] aprovado={r['aprovado']} nota={r['nota']} juiz={r['juiz']}")
        for p in r["problemas"]:
            print(f"   - {p['tipo']}: {p['por_que']} · {p['trecho'][:60]!r}")
