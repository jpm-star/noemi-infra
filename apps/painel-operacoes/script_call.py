"""Script de cold call / porta-a-porta para T3 e T4 — o canal que a Noemi NÃO toca.

Roteamento firmado: T1/T2 vão pro WhatsApp da Noemi (automático); T3/T4 são ligação e
visita do JP e do Lincon. O motor aqui NÃO dispara nada: ele prepara o material e
ordena a fila. Quem fala é gente.

O que ele monta por lead:
  · abertura de ~15 segundos, com o nome do negócio e um gancho do SEGMENTO (nunca
    "somos uma empresa de sites"), e o nome do DECISOR quando o QSA da CNPJá trouxe;
  · as 3 objeções mais prováveis daquele ramo, cada uma com resposta pronta;
  · a MESMA oferta do WhatsApp — demo grátis + 15% pra quem fechar até a sexta desta
    semana. Se a oferta divergir entre canais, o prospect que ouviu as duas percebe.

A ORDEM da fila é o que economiza o dia: dentro de uma cidade dá pra bater cinco portas
a pé; saltar Bauru → Jales → Bauru queima a manhã em estrada. Por isso a lista agrupa
por cidade e encadeia as cidades pelo vizinho mais próximo saindo de Marília — e só
dentro do grupo é que o score de fit decide quem vem primeiro.

ponytail: funções puras sobre `prospeccao_dia.lista_do_dia`. Sem tabela nova, sem fila,
sem estado. O que já existe (gancho honesto, decisor do QSA, dedup do log) é reusado.
"""
from __future__ import annotations

import json
import logging
import math
import os
import re
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import prospeccao_dia

log = logging.getLogger(__name__)
SP = ZoneInfo("America/Sao_Paulo")

# Base de saída da rota: o JP mora e opera em Marília (DDD 14).
ORIGEM = "Marília"

# Coordenadas das cidades da base (interior de SP). Tabela estática de propósito: são
# ~30 cidades que mudam de lugar nunca, e uma chamada de geocoding por lead seria uma
# dependência de rede no caminho de um relatório que precisa abrir offline.
CIDADES: dict[str, tuple[float, float]] = {
    "marília": (-22.21, -49.95), "bauru": (-22.31, -49.06),
    "são josé do rio preto": (-20.81, -49.38), "presidente prudente": (-22.13, -51.39),
    "ribeirão preto": (-21.18, -47.81), "jaú": (-22.30, -48.56),
    "araçatuba": (-21.21, -50.44), "tupã": (-21.93, -50.51),
    "são carlos": (-22.02, -47.89), "lins": (-21.68, -49.74),
    "jundiaí": (-23.19, -46.88), "indaiatuba": (-23.09, -47.21),
    "franca": (-20.54, -47.40), "botucatu": (-22.89, -48.44),
    "birigui": (-21.29, -50.34), "avaré": (-23.10, -48.93),
    "araraquara": (-21.79, -48.18), "americana": (-22.74, -47.33),
    "votuporanga": (-20.42, -49.98), "sumaré": (-22.82, -47.27),
    "sertãozinho": (-21.14, -47.99), "piracicaba": (-22.73, -47.65),
    "mirassol": (-20.82, -49.52), "limeira": (-22.56, -47.40),
    "jales": (-20.27, -50.55), "garça": (-22.21, -49.66),
    "catanduva": (-21.14, -48.98), "campinas": (-22.91, -47.06),
    "bariri": (-22.07, -48.74), "assis": (-22.66, -50.41),
    "ourinhos": (-22.98, -49.87), "adamantina": (-21.68, -51.07),
    "são paulo": (-23.55, -46.63), "sorocaba": (-23.50, -47.46),
}


def _norm(c: str) -> str:
    return " ".join(str(c or "").split()).strip().rstrip("/-").lower()


def _coord(cidade: str) -> tuple[float, float] | None:
    c = _norm(cidade)
    c = re.sub(r"[\s/-]*(sp|s\.p\.)$", "", c).strip()   # "Bauru - SP" → "bauru"
    return CIDADES.get(c)


def km(a: tuple[float, float], b: tuple[float, float]) -> float:
    """Distância em linha reta (haversine). Estrada é mais longa, mas para ORDENAR
    cidades a reta acerta — o que importa é quem está perto de quem, não o km exato."""
    r = 6371.0
    dlat, dlon = math.radians(b[0] - a[0]), math.radians(b[1] - a[1])
    h = (math.sin(dlat / 2) ** 2
         + math.cos(math.radians(a[0])) * math.cos(math.radians(b[0])) * math.sin(dlon / 2) ** 2)
    return 2 * r * math.asin(math.sqrt(h))


def rota(cidades: list[str], origem: str = ORIGEM) -> list[str]:
    """Ordena as cidades pelo vizinho mais próximo saindo da origem.

    Vizinho-mais-próximo, não rota ótima: o caixeiro-viajante exato com 30 cidades é
    caro de calcular e o ganho é irrelevante quando o JP vai visitar 5 num dia. Cidade
    sem coordenada vai pro fim — a lista não pode sumir com um lead por falta de mapa."""
    conhecidas = [c for c in cidades if _coord(c)]
    resto = [c for c in cidades if not _coord(c)]
    fora, atual = [], _coord(origem) or (-22.21, -49.95)
    pendentes = list(dict.fromkeys(conhecidas))
    while pendentes:
        prox = min(pendentes, key=lambda c: km(atual, _coord(c)))
        pendentes.remove(prox)
        fora.append(prox)
        atual = _coord(prox)
    return fora + sorted(dict.fromkeys(resto))


def score_fit(lead: dict) -> int:
    """0-100: quem atende primeiro. Só usa sinal que já está no banco.

    T4 vale mais que T3 porque a oferta é maior (site + Noemi vs SEO/AEO), e ter o nome
    do decisor muda a ligação de "posso falar com o responsável?" pra "o Wagner está?" —
    é o fator que mais move a taxa de chegar em quem decide."""
    s = 40
    s += 20 if (lead.get("tier") or "").upper() == "T4" else 10
    if lead.get("decisor"):
        s += 20
    if lead.get("tem_whatsapp"):
        s += 10           # não liga por WhatsApp, mas dá canal de follow-up
    if lead.get("cnpj"):
        s += 5            # CNPJ = empresa formalizada, tem quem assine contrato
    if (lead.get("achado") or "").strip():
        s += 5            # tem gancho concreto pra abrir
    return min(s, 100)


def prazo_oferta(agora: datetime | None = None) -> str:
    """Sexta desta semana (dd/mm). MESMA regra do cartucho da Noemi (cerebro.prazo_oferta):
    a oferta tem que ser idêntica nos dois canais, senão quem ouviu os dois pega a
    diferença — e aí a urgência inteira vira conversa de vendedor."""
    agora = agora or datetime.now(SP)
    faltam = (4 - agora.weekday()) % 7
    if faltam == 0 and agora.hour >= 12:
        faltam = 7
    return (agora + timedelta(days=faltam)).strftime("%d/%m")


# ── objeções por segmento ────────────────────────────────────────────────────────
_SYS_OBJ = (
    "Você treina vendedores de porta-a-porta no interior de São Paulo. Recebe o RAMO de "
    "um negócio pequeno e o que está sendo vendido, e devolve as 3 objeções que o DONO "
    "mais provavelmente vai dar numa ligação fria — as reais, ditas do jeito que ele "
    "fala, não objeções de manual.\n\n"
    "COMO ESCREVER A RESPOSTA (isto é o que reprova ou aprova):\n"
    "- No MÁXIMO 2 frases curtas. Fala, não redação.\n"
    "- PROIBIDO começar com 'Entendo', 'Compreendo', 'Perfeitamente', 'Isso é ótimo' — "
    "é abertura de manual e o dono percebe na hora.\n"
    "- PROIBIDO os conectores 'de forma que', 'podemos explorar', 'talvez possamos', "
    "'gostaria de', 'venho por meio'.\n"
    "- PROIBIDO prometer resultado ('vai vender mais', 'não perde mais cliente', "
    "'aparece no Google') e PROIBIDO afirmar capacidade que não está na lista abaixo.\n"
    "- Não discuta. Aceite o que a objeção tem de verdade e devolva com UMA pergunta ou "
    "UMA oferta concreta e pequena.\n\n"
    "RUIM: \"Entendo perfeitamente, o tempo é valioso, mas talvez possamos encontrar uma "
    "maneira de integrar isso sem aumentar sua carga de trabalho.\"\n"
    "BOM: \"Imagino. Por isso já vai pronto — você só olha e diz se serve.\"\n"
    "RUIM: \"Isso é ótimo, já ter presença online é um bom começo, mas podemos explorar "
    "como um site novo pode atrair mais clientes.\"\n"
    "BOM: \"Boa. Então nem precisa começar do zero — te mando a demo e você compara.\"\n\n"
    'Responda SOMENTE JSON: {"objecoes":[{"o":"...","r":"..."}]} com exatamente 3 itens.'
)

# combinações que já falharam NESTE processo — não re-tenta até reiniciar. Escopo de
# processo de propósito: uma indisponibilidade passageira não pode virar cache em disco,
# senão o segmento fica sem objeção pra sempre.
_falhou: set[str] = set()

_OFERTAS = {
    "T3": "SEO + AEO — aparecer no Google E nas respostas de IA (ChatGPT, Gemini)",
    "T4": "site novo + a Noemi atendendo no WhatsApp 24h",
}


def _cache_path() -> Path:
    return Path(os.environ.get(
        "OBJECOES_CACHE", str(Path(__file__).resolve().parents[2] / "data" / "objecoes_cache.json")))


def objecoes(segmento: str, tier: str, gerar: bool = False) -> list[dict]:
    """3 objeções + resposta para (segmento, tier). Cache em disco: são ~8 combinações
    na base inteira, então isto custa uma rodada de LLM na vida. [] se o LLM não vier —
    script sem objeção ainda serve pra ligar; script que não abre, não.

    `gerar=False` por padrão: SÓ LÊ O CACHE. A geração passa por LLM + auditoria (3
    chamadas por combinação) e chegou a minutos numa primeira carga — a página de campo
    ficava em "carregando fila…" com o JP olhando. Trabalho de LLM não entra no caminho
    de uma request. Quem gera é `--aquecer`, offline."""
    chave = f"{_norm(segmento)}|{(tier or '').upper()}"
    p = _cache_path()
    try:
        cache = json.loads(p.read_text(encoding="utf-8")) if p.is_file() else {}
    except (OSError, ValueError):
        cache = {}
    if chave in cache:
        return cache[chave]
    if chave in _falhou or not gerar:
        return []
    import sys
    if "/root/motor-site" not in sys.path:
        sys.path.insert(0, "/root/motor-site")
    try:
        from app.providers.llm_orquestrador import _chave, _groq_json
        # o MESMO contrato de produto que o juiz cobra. Sem ele o gerador prometia
        # capacidade que não existe e 27 de 33 objeções eram reprovadas por "promessa" —
        # o autor não pode adivinhar a régua que o avaliador usa.
        import auditor_copy as _ac
        d = _groq_json(_SYS_OBJ + _ac.contrato_produto(),
                       f"RAMO: {segmento}\nESTOU VENDENDO: {_OFERTAS.get((tier or '').upper(), 'site profissional')}",
                       _chave(), temperatura=0.5)
        itens = [{"o": str(x.get("o", "")).strip(), "r": str(x.get("r", "")).strip()}
                 for x in (d.get("objecoes") or [])[:3]
                 if str(x.get("o", "")).strip() and str(x.get("r", "")).strip()]
    except Exception as e:  # noqa: BLE001
        # LEMBRA A FALHA. Sem isto, os 65 leads re-tentavam as MESMAS 8 combinações
        # (o cache em disco só grava sucesso), e uma indisponibilidade curta virava 65
        # chamadas em rajada — o retry amplificava o 429 que o causou. Medido: o log
        # saiu com 40+ linhas de "clínica odontológica/T3 falhou" numa única rodada.
        _falhou.add(chave)
        log.warning("objeções de %s/%s falharam: %s", segmento, tier, e)
        return []
    if not itens:
        return []
    # JUIZ ADVERSARIAL antes do cache. O llama pede desculpa e escreve prosa de manual
    # ("Entendo perfeitamente, o tempo é valioso e é importante priorizar...") — medido
    # na primeira rodada real. Uma resposta assim ao telefone faz o dono desligar, e o
    # cache a congelaria pra sempre. Reprovada entra marcada, nunca some: o JP precisa
    # ver o que o motor produziu de ruim pra corrigir o prompt, não descobrir um buraco.
    try:
        import auditor_copy
        for it in itens:
            a = auditor_copy.auditar(
                it["r"], contexto=f"resposta à objeção '{it['o']}' numa ligação fria "
                                  f"para dono de {segmento}")
            it["ok"] = a["aprovado"]
            it["nota"] = a["nota"]
            it["revisar"] = "; ".join(f"{p['tipo']}: {p['por_que']}" for p in a["problemas"])
    except Exception as e:  # noqa: BLE001 — sem juiz, entrega sem selo em vez de travar
        log.warning("auditoria das objeções indisponível: %s", e)
    cache[chave] = itens
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(cache, ensure_ascii=False, indent=1), encoding="utf-8")
    except OSError:
        pass
    return itens


def abertura(lead: dict) -> str:
    """Os 15 primeiros segundos, escritos pra serem LIDOS em voz alta.

    Reusa `prospeccao_dia.gancho`, que já é a versão honesta e não-ofensiva (nada de
    contato prévio forjado, e achado sensível — "reviews reclamam de demora" — nunca
    abre conversa). Aqui só vira fala: quem fala, com quem quer falar, o gancho, e uma
    pergunta que devolve a palavra em vez de emendar pitch."""
    quem = (lead.get("decisor") or "").strip()
    saudacao = f"Oi, {quem.split()[0]}?" if quem else "Oi, tudo bem?"
    empresa = (lead.get("empresa") or "").strip()
    # nome de negócio garimpado do Google vem com cauda de SEO ("X: Radiologia, Exames,
    # Lins SP"). Falar isso em voz alta entrega na hora que é lista comprada.
    empresa = re.split(r"\s*[:|–—]\s*", empresa)[0].strip() or empresa
    return (f"{saudacao} Aqui é o JP, da JPOS, de Marília. "
            f"Tô ligando pra {empresa} porque {lead.get('gancho', '')}. "
            f"Posso te tomar um minuto pra te mostrar o que dá pra fazer?")


def lista(tier: str = "", limite: int = 200, com_objecoes: bool = True) -> dict:
    """A fila do dia pronta pra imprimir: cidades em rota, leads em ordem de fit."""
    # UM PEDIDO POR TIER, não um pedido geral filtrado depois: `lista_do_dia` corta em
    # `fora[:limite]` DEPOIS de ordenar com T1 na frente, então pedir 200 e filtrar T3/T4
    # devolvia zero — os 1.446 T1/T2 comiam a cota inteira antes do filtro.
    tiers = [tier.upper()] if tier else ["T3", "T4"]
    alvos = [l for t in tiers for l in prospeccao_dia.lista_do_dia(tier=t, limite=limite)
             .get("leads", [])]
    for l in alvos:
        l["score"] = score_fit(l)
        l["abertura"] = abertura(l)
        l["oferta"] = _OFERTAS.get((l.get("tier") or "").upper(), "")
    ordem = rota(sorted({(l.get("cidade") or "").strip() for l in alvos if l.get("cidade")}))
    # SÓ CACHE aqui (gerar=False é o default). A geração é offline, por `aquecer()`.
    if com_objecoes:
        for l in alvos:
            l["objecoes"] = objecoes(l.get("segmento") or "", l.get("tier") or "")
    grupos = []
    for cid in ordem:
        do_grupo = sorted([l for l in alvos if (l.get("cidade") or "").strip() == cid],
                          key=lambda x: (-x["score"], x["empresa"].lower()))
        if do_grupo:
            c = _coord(cid)
            # o km que importa em campo é o SALTO (daqui pra próxima parada), não a
            # distância até Marília: é ele que diz se dá pra emendar duas cidades no dia.
            ant = _coord(grupos[-1]["cidade"]) if grupos else _coord(ORIGEM)
            grupos.append({"cidade": cid, "leads": do_grupo,
                           "km_da_origem": round(km(_coord(ORIGEM), c)) if c else None,
                           "km_do_anterior": round(km(ant, c)) if (c and ant) else None})
    sem_cidade = [l for l in alvos if not (l.get("cidade") or "").strip()]
    if sem_cidade:
        grupos.append({"cidade": "(sem cidade)", "leads": sem_cidade, "km_da_origem": None})
    return {"gerado_em": datetime.now(SP).strftime("%d/%m/%Y %H:%M"),
            "prazo_oferta": prazo_oferta(), "origem": ORIGEM,
            "total": len(alvos), "cidades": len(grupos), "grupos": grupos}


def aquecer(tiers: tuple[str, ...] = ("T3", "T4")) -> dict:
    """Gera e audita as objeções de todas as combinações (segmento, tier) da fila.

    Roda OFFLINE — é aqui que os minutos de LLM acontecem, e é por isso que a página
    de campo abre na hora. Chame depois de importar leads novos ou de mexer no prompt."""
    combos = {(l.get("segmento") or "", t)
              for t in tiers
              for l in prospeccao_dia.lista_do_dia(tier=t, limite=500).get("leads", [])}
    ok = rev = 0
    for seg, t in sorted(combos):
        for o in objecoes(seg, t, gerar=True):
            ok, rev = (ok + 1, rev) if o.get("ok") else (ok, rev + 1)
        log.info("· %s/%s pronto", seg, t)
    return {"combinacoes": len(combos), "aprovadas": ok, "revisar": rev}


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    # self-check das partes puras (sem rede, sem banco)
    assert _coord("Bauru - SP") and _coord("BAURU") == _coord("bauru")
    assert _coord("Xique-Xique") is None
    assert round(km(CIDADES["marília"], CIDADES["bauru"])) == 92  # Marília→Bauru em linha reta
    r = rota(["Jales", "Garça", "Campinas", "Bauru", "Atlântida"])
    assert r[0] == "Garça", f"o vizinho de Marília é Garça, veio {r[0]}"
    assert r[-1] == "Atlântida", "cidade sem coordenada tem que ir pro fim"
    assert score_fit({"tier": "T4", "decisor": "x", "tem_whatsapp": True, "cnpj": "1"}) == 95
    assert score_fit({"tier": "T3"}) == 50
    sexta = datetime(2026, 8, 7, 9, 0, tzinfo=SP)
    assert prazo_oferta(sexta) == "07/08" and prazo_oferta(sexta.replace(hour=15)) == "14/08"
    a = abertura({"empresa": "DVI Radiologia: Exames, Lins SP", "decisor": "Ana Paula",
                  "gancho": "vocês não aparecem no Google"})
    assert a.startswith("Oi, Ana?") and "DVI Radiologia" in a and "Exames, Lins" not in a
    print("script_call OK — rota, score, prazo e abertura conferem")
    import sys
    if "--aquecer" in sys.argv:
        print("\naquecendo objeções (isto chama LLM, leva minutos)…")
        print(aquecer())
    d = lista(com_objecoes=False)
    print(f"\n{d['total']} leads T3/T4 em {d['cidades']} cidades · oferta até {d['prazo_oferta']}")
    for g in d["grupos"][:6]:
        print(f"  {g['cidade']} ({g['km_da_origem']} km): "
              + ", ".join(f"{l['empresa'][:28]} [{l['score']}]" for l in g["leads"][:3]))
