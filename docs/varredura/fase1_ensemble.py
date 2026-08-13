"""FASE 1 — ensemble (Gemini + 3 lanes Groq) procurando o BURACO nas 150 taxonomias.

Não é pra dobrar o catálogo: é pra achar o que os 150 originais deixaram de fora.
Cada lane recebe a lista INTEIRA e uma pergunta diferente — lanes com a mesma
pergunta devolvem a mesma coisa três vezes e a diversidade vira custo sem retorno.

Saída: JSON cru de cada lane em /root/jpos-entregaveis/fase1/, pro Claude sintetizar
depois. Guardar o cru importa: se a síntese estiver errada, dá pra reler a fonte.
"""
from __future__ import annotations

import json
import os
import pathlib
import sys
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, "/root/noemi-infra/apps/painel-operacoes")
sys.path.insert(0, "/root/noemi-infra/packages")
import vocabulario as V  # noqa: E402
from shared_core.ai import http_llm  # noqa: E402

SAIDA = pathlib.Path("/root/jpos-entregaveis/fase1")
SAIDA.mkdir(parents=True, exist_ok=True)


def _envs() -> dict:
    fora = {}
    for f in ("/root/noemi-infra/infra/.env", "/root/noemi-infra/.env"):
        try:
            for l in open(f, encoding="utf-8"):
                k, _, v = l.partition("=")
                if v.strip():
                    fora.setdefault(k.strip(), v.strip())
        except OSError:
            pass
    return fora


ENV = _envs()

NICHOS = sorted({t for termos in V.NICHOS.values() for t in termos})
ESTRUTURAS = [e["nome"] for e in V.ESTRUTURAS_LISTA]
PRINCIPIOS = V.principios()

CONTEXTO = f"""Você analisa o vocabulário de um GERADOR DE SITES brasileiro (JPOS).
Ele vende 4 tiers: T1 landing única (R$500, sem mensalidade), T2 multi-página+SEO
(R$1.000 + R$397/mês), T3 IA no site que agenda (R$1.500 + R$697/mês), T4 painel de
operação do cliente (R$2.500 + R$1.297/mês). Clientes: negócio local do interior de
São Paulo (clínica, academia, advocacia, salão, imobiliária, restaurante, e-commerce
pequeno). O motor gera HTML ESTÁTICO, sem framework, e compõe estilos visuais por
seção. T1/T2 são vendidos por VELOCIDADE (Core Web Vitals), então nada pesado neles.

VOCABULÁRIO ATUAL ({len(NICHOS)} nichos, {len(ESTRUTURAS)} estruturas de seção, {len(PRINCIPIOS)} princípios):

NICHOS: {", ".join(NICHOS)}

ESTRUTURAS DE SEÇÃO: {", ".join(ESTRUTURAS)}

PRINCÍPIOS: {", ".join(PRINCIPIOS)}
"""

LANES = {
    "gemini-lacunas": (
        "gemini",
        "Aponte o que está FALTANDO neste vocabulário. Não repita nem renomeie o que já "
        "está lá. Foque em: (a) nichos de negócio local brasileiro comuns no interior "
        "paulista que não aparecem; (b) estruturas de seção que negócios BRASILEIROS "
        "usam e a lista ignora (pense em PIX, WhatsApp, parcelamento, consórcio, "
        "convênio, delivery, agendamento por link); (c) princípios de conversão "
        "específicos do comportamento brasileiro em celular. Seja concreto e curto."),
    "groq-antipadrao": (
        "groq",
        "Aponte os ANTIPADRÕES e as ARMADILHAS que este vocabulário NÃO cobre: coisas que "
        "sites de negócio local fazem e que DESTROEM conversão, e que um gerador "
        "automático repetiria sem perceber. Para cada um, diga o que o gerador deveria "
        "fazer no lugar. Não liste boas práticas genéricas."),
    "groq-monetizacao": (
        "groq",
        "Este catálogo tem 4 tiers e alguns upsells (WhatsApp 24h R$97/mês, domínio+e-mail "
        "R$29/mês, radar de uptime R$47/mês, landing avulsa R$250, vídeo IA R$197/mês, "
        "Calendar R$97/mês). Aponte PRODUTOS ou ADD-ONS que este vocabulário sugere que "
        "seriam vendáveis e que ainda não existem no catálogo — especialmente receita "
        "RECORRENTE e receita que não exige o dono trabalhar mais horas. Para cada: o que "
        "é, por que o cliente pagaria, e faixa de preço plausível no Brasil."),
    # LANE REMOVIDA (13/08/2026): "groq-vertical" rodava em llama-3.3-70b e devolveu
    # "galeria de trabalhos", "cardápio online" e "tabela de horários" — os três já
    # estavam nas 77 estruturas. Zero contribuição, custo integral.
    #
    # A causa não foi o modelo ser ruim: foi a PERGUNTA. "escolha as 6 verticais mais
    # promissoras e diga a seção que cada uma precisa" pede exatamente o que a lista
    # que veio no contexto já responde — o modelo leu o vocabulário e devolveu o
    # vocabulário. Pergunta que pode ser respondida pelo próprio contexto não precisa
    # de LLM nenhum.
    #
    # DECISÃO: 3 lanes bastam, com a regra de que cada pergunta tem que ser
    # IMPOSSÍVEL de responder só relendo o contexto. As que sobraram passam nesse
    # teste: lacuna (o que NÃO está aqui), antipadrão (o que dá errado) e monetização
    # (o que não existe no catálogo). Uma 4ª lane só entra com pergunta que não seja
    # variação dessas três.
}


def _gemini(pergunta: str) -> str:
    chave = ENV.get("GEMINI_API_KEY", "")
    corpo = json.dumps({"contents": [{"parts": [{"text": CONTEXTO + "\n\nTAREFA: " + pergunta}]}]}).encode()
    # models.list ANUNCIA gemini-2.5-flash e generateContent RECUSA ("no longer
    # available to new users"). Listar não é poder usar: a cadeia tenta na ordem e
    # o primeiro que responde ganha, em vez de eu cravar um id que some sem aviso.
    ultimo = ""
    for modelo in ("gemini-2.5-pro", "gemini-3-flash-preview", "gemini-2.5-flash-lite"):
        url = (f"https://generativelanguage.googleapis.com/v1beta/models/"
               f"{modelo}:generateContent")
        try:
            d = http_llm.post_json(url, json.loads(corpo.decode()), chave,
                                   tipo="goog", timeout=240)
            partes = d["candidates"][0]["content"]["parts"]
            return f"<!-- modelo: {modelo} -->\n" + "".join(x.get("text", "") for x in partes)
        except urllib.error.HTTPError as e:
            ultimo = f"{modelo}: HTTP {e.code}"
            continue
    raise RuntimeError(f"nenhum modelo Gemini respondeu ({ultimo})")


_GROQ_KEYS = [ENV[k] for k in ("GROQ_POOL_01", "GROQ_POOL_02", "GROQ_POOL_03",
                               "GROQ_ANALISE", "GROQ_API_KEY") if ENV.get(k)]


# TETO DE SAÍDA. O `max_tokens` conta INTEIRO contra o TPM mesmo que a resposta seja
# curta: pedir 8000 com 2.4k de entrada dá 10.4k e estoura um limite de 8.000.
TETO_SAIDA = int(os.environ.get("GROQ_TETO", "5000"))


def _groq(pergunta: str, i: int) -> str:
    """Uma lane. As chaves giram por lane, mas isso NÃO multiplica vazão — ver abaixo.

    O TPM DO GROQ É POR ORGANIZAÇÃO, NÃO POR CHAVE. Medido em 13/08/2026, com a
    mensagem do próprio Groq:

        Request too large for model `openai/gpt-oss-120b` in organization
        `org_01ktcf8...` service tier `on_demand` on tokens per minute (TPM):
        Limit 8000, Requested 8072

    Eu tinha escrito aqui que "uma chave por lane" evitaria o 429. Está errado: as 5
    chaves do pool dividem o MESMO orçamento de 8.000 TPM. Girar chave protege contra
    limite de REQUISIÇÕES por chave, não contra o de tokens da organização — e foi por
    isso que duas lanes em paralelo derrubaram as duas.

    Consequência prática: as lanes Groq rodam em SÉRIE. Paralelismo aqui não é
    otimização, é a causa da falha.
    """
    chave = _GROQ_KEYS[i % len(_GROQ_KEYS)]
    # MODELOS DE FAMÍLIAS DIFERENTES por lane. Três instâncias do mesmo modelo com
    # prompts diferentes devolvem a mesma voz três vezes; famílias diferentes é que
    # dão diversidade de verdade — que é a única razão de rodar ensemble.
    modelo = ("openai/gpt-oss-120b", "qwen/qwen3.6-27b")[i % 2]
    # Cliente compartilhado: o User-Agent vem de lá. Foi a falta dele que derrubou o
    # primeiro round inteiro deste script com 403/1010, e o teto de 8000 existe porque
    # modelo de raciocínio gasta orçamento pensando — com 3000 o qwen devolveu o
    # bloco <think> e ficou sem espaço pra resposta.
    txt = http_llm.groq(
        [{"role": "system", "content": CONTEXTO}, {"role": "user", "content": pergunta}],
        chave, modelo=modelo, temperatura=0.8, teto=TETO_SAIDA)
    return f"<!-- modelo: {modelo} -->\n" + txt


def rodar(nome: str, spec: tuple, i: int) -> tuple[str, str]:
    provedor, pergunta = spec
    try:
        txt = _gemini(pergunta) if provedor == "gemini" else _groq(pergunta, i)
        (SAIDA / f"{nome}.md").write_text(txt, encoding="utf-8")
        return nome, f"OK {len(txt)} chars"
    except urllib.error.HTTPError as e:
        det = e.read()[:200].decode(errors="replace")
        return nome, f"HTTP {e.code}: {det}"
    except Exception as e:  # noqa: BLE001
        return nome, f"{type(e).__name__}: {str(e)[:160]}"


if __name__ == "__main__":
    print(f"vocabulário: {len(NICHOS)} nichos · {len(ESTRUTURAS)} estruturas · "
          f"{len(PRINCIPIOS)} princípios")
    print(f"chaves Groq disponíveis: {len(_GROQ_KEYS)}")
    itens = list(LANES.items())
    # Gemini é outro provedor e outro orçamento: pode ir junto. As lanes Groq vão em
    # SÉRIE porque compartilham o TPM da organização (ver _groq).
    gem = [(i, n, sp) for i, (n, sp) in enumerate(itens) if sp[0] == "gemini"]
    grq = [(i, n, sp) for i, (n, sp) in enumerate(itens) if sp[0] == "groq"]
    with ThreadPoolExecutor(max_workers=max(1, len(gem))) as ex:
        futs = [ex.submit(rodar, n, sp, i) for i, n, sp in gem]
        for i, n, sp in grq:
            nome, st = rodar(n, sp, i)
            print(f"  {nome:<22} {st}")
            time.sleep(float(os.environ.get("GROQ_PAUSA_S", "62")))  # janela de TPM
        for f in futs:
            n, st = f.result()
            print(f"  {n:<22} {st}")
    print(f"\ncru em {SAIDA}")
