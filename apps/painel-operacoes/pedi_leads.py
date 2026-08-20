"""Pé Di · captação de leads pra brinde corporativo — CSV import-ready.

Primeira base de leads da Pé Di. Nicho principal: assessoria esportiva (chinelo
entra em kit de largada/chegada de corrida de rua). Correlatos: onde brinde de
chinelo já é padrão de mercado (casamento) ou onde há evento próprio.

DE ONDE VEM CADA CAMPO — isso é o ponto do módulo:
  - nome, telefone, cidade, site, avaliações  → Google Places API (dado da API)
  - Instagram, sinal de brinde anterior       → lido do site DO PRÓPRIO LEAD (regex)
  - porte                                     → regra sobre avaliações + unidades
Nada sai de LLM. Um modelo perguntado por "100 assessorias com telefone" devolve
nomes plausíveis e telefones inventados com a mesma cara de dado real — que é o
oposto do que uma lista de prospecção precisa ser. Campo sem fonte fica
"não identificado", nunca preenchido no chute.

ponytail: reusa apps/motor-leads/coleta.py (Places oficial, dedupe por place_id,
multi-unidade). Zero coletor novo. O que este módulo acrescenta é o vocabulário
do nicho, o enriquecimento por site e o CSV no schema da aba LEADS da v2.

ponytail: a coleta gasta ~6x mais Place Details do que precisaria — coletar() pede
detalhe de TODO resultado do Text Search e ~50% morre depois no filtro de aderência.
O nome já vem no Text Search, então dava pra filtrar antes de pedir detalhe. Não
mexi porque coleta.py é compartilhado com a captação do JPOS e não vale arriscar
aquilo por custo de uma rodada. Se isso virar rotina, o corte é levar o filtro de
aderência pra dentro de coletar() — vale ~60% da conta.
"""
from __future__ import annotations

import csv
import os
import re
import sys
import urllib.request
from pathlib import Path

_RAIZ = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_RAIZ / "apps" / "motor-leads"))

import coleta  # noqa: E402  (precisa do sys.path acima)

# Raio da Pé Di: Lins e o entorno onde ela já opera, mais as duas praças grandes.
# A aba LEADS da v2 já prospectou em Bauru/Araçatuba/Interior SP — mesmo território.
CIDADES = ("Lins", "Bauru", "Marília", "Araçatuba", "São José do Rio Preto",
           "Presidente Prudente", "Jaú", "Botucatu", "Ourinhos", "Assis",
           "Campinas", "São Paulo")

# Termos granulares: o Text Search satura por volta de 60 por query, então vários
# termos estreitos rendem mais lead distinto que um termo largo.
SEGMENTOS = {
    "Assessoria esportiva": {
        "alvo": 100,
        "termos": ("assessoria esportiva", "assessoria de corrida", "treinamento de corrida de rua",
                   "grupo de corrida", "personal trainer corrida", "clube de corrida"),
    },
    "Academia / box de crossfit": {
        "alvo": 10,
        "termos": ("box de crossfit", "academia de treinamento funcional", "crossfit"),
    },
    "Cerimonialista / buffet": {
        "alvo": 10,
        "termos": ("cerimonialista de casamento", "buffet de casamento", "assessoria de casamento"),
    },
    "Organizadora de evento corporativo": {
        "alvo": 10,
        "termos": ("organizadora de eventos corporativos", "agência de eventos corporativos",
                   "produtora de eventos"),
    },
    "Clube de triathlon / natação": {
        "alvo": 10,
        "termos": ("clube de triathlon", "equipe de triathlon", "clube de natação"),
    },
}

# Sinal de que o lead JÁ distribuiu brinde em evento — procurado no site dele.
# Termos escolhidos pra evitar falso positivo: "kit" sozinho pega "kit de treino",
# então só conta em par com algo de evento/entrega.
_BRINDE = (r"kit\s+(?:do\s+)?atleta", r"kit\s+de\s+(?:largada|corrida|prova|evento)",
           r"brinde", r"camiseta\s+(?:do\s+)?evento", r"camiseta\s+(?:da\s+)?prova",
           r"sacochila", r"squeeze\s+personalizad", r"medalha\s+personalizad",
           r"kit\s+participante", r"welcome\s+kit", r"lembrancinha")
_INSTA = re.compile(r"instagram\.com/([A-Za-z0-9_.]{2,30})", re.I)

# O Text Search devolve o que estiver perto do termo, não o que é do nicho: buscar
# "assessoria de corrida" em cidade pequena traz shopping, prefeitura e academia
# genérica quando o estoque real acaba. Dois filtros, nesta ordem:
#   _EXCLUIR  → não é empresa prospectável pra brinde, cai fora
#   _ADERENCIA → é do segmento? se o nome não confirma, entra marcado, não sumido
# Descartar em silêncio esconderia que o segmento não tem estoque — que é
# justamente o que precisa ser reportado.
_EXCLUIR = re.compile(
    r"\b(shopping|supermercado|mercado|prefeitura|secretaria|hospital|santa casa|"
    r"posto de sa[uú]de|upa|banco|lot[eé]rica|farm[aá]cia|padaria|igreja|"
    r"universidade|faculdade|escola (?:municipal|estadual)|cart[oó]rio|"
    r"loja|magazine|atacad|distribuidora)\b", re.I)

_ADERENCIA = {
    "Assessoria esportiva": r"assessoria|corrida|corredor|run|esport|atletismo|treinament|"
                            r"coach|training|performance|team|maratona|triathlon|tri\b",
    "Academia / box de crossfit": r"crossfit|box|funcional|academia|fitness|gym|treinament",
    "Cerimonialista / buffet": r"cerimonial|buffet|bufê|casamento|festa|eventos|noiva|recep[çc]",
    "Organizadora de evento corporativo": r"evento|produtora|ag[eê]ncia|cerimonial|promo|corporat",
    "Clube de triathlon / natação": r"triathlon|triatlo|nata[çc]|aqu[aá]|swim|clube|nadador|piscina",
}


def _so_digitos(t: str) -> str:
    return re.sub(r"\D", "", t or "")


def _baixar(url: str, timeout: int = 8) -> str:
    """HTML do site do lead. Falha (404, TLS, timeout, site morto) = string vazia:
    site fora do ar é comum na base e não pode derrubar a coleta inteira."""
    if not url:
        return ""
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (compatible; PeDiBot/1.0)"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.read(400_000).decode("utf-8", "ignore")
    except Exception:  # noqa: BLE001 — qualquer falha de rede é "sem dado", não erro
        return ""


def _porte(total_reviews: int, n_unidades: int) -> str:
    """Porte por proxy observável. Avaliações no Google medem volume de público
    melhor que qualquer estimativa — e multi-unidade sozinho já é sinal de porte."""
    if n_unidades >= 2 or total_reviews >= 300:
        return "grande"
    if total_reviews >= 80:
        return "médio"
    return "pequeno"


def _enriquecer(lead: dict) -> dict:
    """Instagram e sinal de brinde a partir do site do lead. Sem site = sem dado."""
    html = _baixar(lead.get("website") or "")
    insta = ""
    if html:
        for m in _INSTA.finditer(html):
            alvo = m.group(1).strip(".")
            # links de navegação do próprio Instagram, não o perfil do lead
            if alvo.lower() not in ("p", "explore", "accounts", "reel", "reels", "tv", "stories"):
                insta = "@" + alvo
                break
    if not html:
        sinal = "não identificado"
    else:
        baixo = html.lower()
        sinal = "sim" if any(re.search(p, baixo) for p in _BRINDE) else "não"
    return {"instagram": insta, "sinal_brinde": sinal, "site_lido": bool(html)}


def coletar_segmento(segmento: str, api_key: str, cidades=CIDADES, verboso: bool = True,
                     teto_cidade: int = 0) -> tuple[list[dict], dict]:
    """Roda o segmento cidade a cidade até bater o alvo ou esgotar as cidades.

    Critério de parada explícito: para no alvo, ou quando acabam as cidades. Nunca
    fica em laço de busca sem fim. `teto_cidade` espalha o alvo — sem ele um alvo
    de 10 fecha inteiro na primeira cidade e a lista vira monocultura de Lins.

    Devolve (leads, diagnóstico). O diagnóstico é o que permite dizer "esse segmento
    não tem estoque" em vez de entregar 10 linhas fracas.
    """
    cfg = SEGMENTOS[segmento]
    alvo = cfg["alvo"]
    teto = teto_cidade or max(3, alvo // 3)
    aderencia = re.compile(_ADERENCIA[segmento], re.I)
    vistos_id, vistos_fone, vistos_nome = set(), set(), set()
    fora, diag = [], {"excluidos": 0, "aderencia_baixa": 0, "duplicados": 0, "cidades_usadas": []}
    teto_bruto = alvo * 3  # trava de orçamento: não varre o mapa atrás do último aderente
    n_adere = 0

    for cidade in cidades:
        if n_adere >= alvo or len(fora) >= teto_bruto:
            break
        restam = alvo - n_adere
        try:
            brutos = coleta.coletar(cidade, cfg["termos"], api_key=api_key,
                                    limite=min(restam + 10, 25))
        except Exception as e:  # noqa: BLE001 — uma cidade falhar não mata o segmento
            if verboso:
                print(f"    ! {cidade}: {e}")
            continue
        nesta, baixa = 0, 0
        for b in brutos:
            if n_adere >= alvo or nesta >= teto or len(fora) >= teto_bruto:
                break
            nome = b.get("nome") or ""
            if b["place_id"] in vistos_id:
                continue
            # dedupe real: o mesmo negócio aparece com 2 place_id (matriz/filial
            # cadastrada duas vezes). Telefone e nome pegam o que o place_id perde —
            # e sem isso o duplicado ainda virava "multi-unidade" = porte grande.
            fone = _so_digitos(b.get("telefone") or "")
            chave_nome = coleta._norm_nome(nome)
            if (fone and fone in vistos_fone) or (chave_nome and chave_nome in vistos_nome):
                diag["duplicados"] += 1
                continue
            if _EXCLUIR.search(nome):
                diag["excluidos"] += 1
                continue
            vistos_id.add(b["place_id"])
            if fone:
                vistos_fone.add(fone)
            if chave_nome:
                vistos_nome.add(chave_nome)
            b["segmento"] = segmento
            b["adere"] = bool(aderencia.search(nome))
            if b["adere"]:
                n_adere += 1
            else:
                diag["aderencia_baixa"] += 1
                baixa += 1
            b.update(_enriquecer(b))
            fora.append(b)
            nesta += 1
        if nesta:
            diag["cidades_usadas"].append(f"{cidade}:{nesta}")
        if verboso:
            print(f"    {cidade}: +{nesta} (aderência baixa {baixa}) → {n_adere}/{alvo} aderentes")

    # unidades e porte só no fim: contar por cidade marcava rede onde havia duplicata
    _unidades_global(fora)
    for l in fora:
        l["porte"] = _porte(l.get("total_reviews") or 0, l.get("n_unidades") or 1)
    diag["aderentes"] = sum(1 for x in fora if x["adere"])
    return fora, diag


def _unidades_global(leads: list[dict]) -> None:
    """Rede de verdade = mesmo nome em CIDADES diferentes. Mesmo nome na mesma
    cidade já foi barrado como duplicata antes de chegar aqui."""
    por_nome: dict[str, set] = {}
    for l in leads:
        por_nome.setdefault(coleta._norm_nome(l["nome"]), set()).add(l.get("cidade_origem"))
    for l in leads:
        l["n_unidades"] = len(por_nome[coleta._norm_nome(l["nome"])])


# Schema da aba 03_LEADS da PEDI_OPERACIONAL_v2 + as colunas que o brief pede.
# Casar com a planilha que o JP já usa evita retrabalho manual no import.
COLUNAS = ["ID", "Empresa", "Segmento", "Cidade", "Telefone/WhatsApp", "Instagram",
           "Site", "Porte estimado", "Distribuiu brinde antes", "Avaliações Google",
           "Nota Google", "Unidades", "Confere com o segmento", "Origem do contato",
           "Status", "Score (1-10)", "Próxima ação", "Notas"]


def _score(lead: dict) -> int:
    """Score 1-10: fit pra brinde. Sinal de brinde anterior pesa mais que porte —
    quem já comprou brinde não precisa ser convencido de que a categoria existe."""
    if not lead.get("adere", True):
        return 1  # não confirmou ser do segmento — fim da fila, nunca no topo
    s = 3
    s += {"grande": 3, "médio": 2, "pequeno": 1}[lead["porte"]]
    if lead["sinal_brinde"] == "sim":
        s += 3
    if lead.get("telefone"):
        s += 1
    return min(s, 10)


def _dedupe_global(leads: list[dict]) -> list[dict]:
    """Um negócio, uma linha — mesmo que tenha caído em dois segmentos. Fica a
    ocorrência de maior score, que é a de segmento mais aderente."""
    melhor: dict[str, dict] = {}
    for l in sorted(leads, key=_score, reverse=True):
        chave = _so_digitos(l.get("telefone") or "") or coleta._norm_nome(l.get("nome") or "")
        if chave and chave not in melhor:
            melhor[chave] = l
    return list(melhor.values())


def para_linhas(leads: list[dict]) -> list[dict]:
    linhas = []
    for i, l in enumerate(sorted(_dedupe_global(leads), key=_score, reverse=True), 1):
        cidade = (l.get("endereco") or "").split(" - ")
        linhas.append({
            "ID": f"PD{i:04d}",
            "Empresa": l.get("nome") or "",
            "Segmento": l["segmento"],
            "Cidade": l.get("cidade_origem") or (cidade[1] if len(cidade) > 1 else ""),
            "Telefone/WhatsApp": l.get("telefone") or "",
            "Instagram": l.get("instagram") or "",
            "Site": l.get("website") or "",
            "Porte estimado": l["porte"],
            "Distribuiu brinde antes": l["sinal_brinde"],
            "Avaliações Google": l.get("total_reviews") or 0,
            "Nota Google": l.get("rating") or "",
            "Unidades": l.get("n_unidades") or 1,
            "Confere com o segmento": "sim" if l.get("adere", True) else "CONFERIR",
            "Origem do contato": "Google Places" + (" + site" if l.get("site_lido") else ""),
            "Status": "A contatar",
            "Score (1-10)": _score(l),
            "Próxima ação": "Ligar e oferecer chinelo pro kit do próximo evento",
            "Notas": " | ".join(x for x in [
                l.get("endereco") or "",
                f"busca: {l.get('categoria')}" if l.get("categoria") else "",
                "site não abriu" if not l.get("site_lido") and l.get("website") else "",
                "sem site" if not l.get("website") else "",
            ] if x),
        })
    return linhas


def _escrever(linhas: list[dict], destino: str) -> str:
    with open(destino, "w", newline="", encoding="utf-8-sig") as f:  # BOM: Excel/Sheets pt-BR
        w = csv.DictWriter(f, fieldnames=COLUNAS)
        w.writeheader()
        w.writerows(linhas)
    return destino


def exportar(leads: list[dict], destino: str) -> dict:
    """Dois arquivos de propósito. Misturar os dois faria o JP peneirar na mão
    justamente no momento em que ele quer só discar — e "import-ready" morre aí.
    O duvidoso não é descartado: fica ao lado, com o motivo na coluna."""
    todas = para_linhas(leads)
    fila = [x for x in todas if x["Confere com o segmento"] == "sim"]
    conferir = [x for x in todas if x["Confere com o segmento"] != "sim"]
    alt = destino.replace(".csv", "_conferir.csv")
    _escrever(fila, destino)
    _escrever(conferir, alt)
    return {"fila": destino, "n_fila": len(fila), "conferir": alt, "n_conferir": len(conferir)}


def _chave() -> str:
    k = os.environ.get("GOOGLE_PLACES_API_KEY", "").strip()
    if not k:
        env = _RAIZ / ".env"
        if env.exists():
            for ln in env.read_text(encoding="utf-8", errors="ignore").splitlines():
                if ln.startswith("GOOGLE_PLACES_API_KEY"):
                    k = ln.partition("=")[2].strip().strip('"').strip("'")
    if not k:
        raise coleta.FaltaChave("defina GOOGLE_PLACES_API_KEY")
    return k


def rodar(destino: str, segmentos=None) -> dict:
    api_key = _chave()
    todos, resumo = [], {}
    for seg in (segmentos or list(SEGMENTOS)):
        print(f"\n== {seg} (alvo {SEGMENTOS[seg]['alvo']}) ==")
        achados, diag = coletar_segmento(seg, api_key)
        todos.extend(achados)
        alvo_seg = SEGMENTOS[seg]["alvo"]
        resumo[seg] = {
            "coletados": len(achados), "alvo": alvo_seg,
            "aderentes": diag["aderentes"], "aderencia_baixa": diag["aderencia_baixa"],
            "descartados_ruido": diag["excluidos"], "duplicados_barrados": diag["duplicados"],
            "com_telefone": sum(1 for x in achados if x.get("telefone")),
            "com_site": sum(1 for x in achados if x.get("website")),
            "com_instagram": sum(1 for x in achados if x.get("instagram")),
            "brinde_sim": sum(1 for x in achados if x["sinal_brinde"] == "sim"),
            "cidades": diag["cidades_usadas"],
            "veredito": ("alvo batido" if diag["aderentes"] >= alvo_seg
                         else "SEM ESTOQUE: %d aderentes de %d pedidos" % (diag["aderentes"], alvo_seg)),
        }
    arqs = exportar(todos, destino)
    return {**arqs, "brutos_coletados": len(todos), "por_segmento": resumo}


if __name__ == "__main__":
    if "--selfcheck" in sys.argv:
        # regras puras, sem rede — o que quebra se alguém mexer na classificação
        assert _porte(500, 1) == "grande" and _porte(10, 3) == "grande"
        assert _porte(120, 1) == "médio" and _porte(5, 1) == "pequeno"
        html = '<a href="https://instagram.com/corridalins">ig</a> entregamos o kit do atleta'
        assert _INSTA.search(html).group(1) == "corridalins"
        assert any(re.search(p, html.lower()) for p in _BRINDE)
        # "kit" solto NÃO pode contar como brinde
        assert not any(re.search(p, "montamos seu kit de treino semanal") for p in _BRINDE)
        base = {"porte": "grande", "sinal_brinde": "sim", "telefone": "x", "adere": True}
        assert _score(base) == 10
        assert _score({"porte": "pequeno", "sinal_brinde": "não", "telefone": "", "adere": True}) == 4
        # o shopping que entrou no topo da 1a rodada: aderência falsa mata o score
        assert _score({**base, "adere": False}) == 1
        assert _EXCLUIR.search("Marília Shopping") and not _EXCLUIR.search("Lobo Assessoria")
        ad = re.compile(_ADERENCIA["Assessoria esportiva"], re.I)
        assert ad.search("Lobo Assessoria Esportiva") and not ad.search("Centro Social Urbano")
        assert _so_digitos("(14) 99832-0333") == "14998320333"
        print("OK — self-check das regras passou.")
    else:
        alvo = sys.argv[1] if len(sys.argv) > 1 else "pedi_leads.csv"
        import json
        print(json.dumps(rodar(alvo), ensure_ascii=False, indent=2))
