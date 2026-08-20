"""15 imobiliárias high-ticket pro JPOS — lista separada da base da Pé Di.

Por que arquivo próprio e não mais um segmento em pedi_leads: o alvo é OUTRO
produto. Pé Di vende chinelo pra brinde; aqui a venda é site T3/T4 do JPOS. Juntar
as duas listas no mesmo CSV faria a fila de primeiro toque do Pé Di oferecer
chinelo pra imobiliária.

"High-ticket" aqui não é chute: é imobiliária de alto padrão / lançamento, filtrada
por termo de busca e ordenada por volume de avaliação, que é o proxy observável de
movimento real.

Regra do JP: no máximo 2 franquias na lista. Rede grande decide site na matriz e o
corretor local não tem poder de compra — 15 leads todos de franquia seria uma lista
que não fecha.
"""
from __future__ import annotations

import csv
import re
import sys
from pathlib import Path

_AQUI = Path(__file__).resolve().parent
sys.path.insert(0, str(_AQUI))

import pedi_leads  # noqa: E402

TERMOS = ("imobiliária alto padrão", "imobiliária lançamentos", "imobiliária de luxo",
          "consultoria imobiliária", "imobiliária")

# Redes conhecidas: entram, mas contam contra o teto de 2.
FRANQUIAS = re.compile(
    r"\b(re/?max|century\s*21|coldwell|keller\s*williams|kw\b|lopes|century21|"
    r"engel\s*&?\s*v[oö]lkers|bossa\s*nova|auxiliadora\s*predial|"
    r"casa\s*mineira|dr\.?\s*imóveis|imobiliária\s*21)\b", re.I)

MAX_FRANQUIAS = 2
ALVO = 15
CIDADES = ("Bauru", "São José do Rio Preto", "Marília", "Araçatuba",
           "Presidente Prudente", "Campinas", "Ribeirão Preto")


def coletar(api_key: str, alvo: int = ALVO) -> tuple[list[dict], dict]:
    """Varre as praças até fechar o alvo, respeitando o teto de franquias."""
    pedi_leads.SEGMENTOS["Imobiliária high-ticket"] = {"alvo": alvo * 3, "termos": TERMOS}
    pedi_leads._ADERENCIA["Imobiliária high-ticket"] = r"imobili|im[oó]ve|corretor|realty|real\s*estate"
    brutos, diag = pedi_leads.coletar_segmento("Imobiliária high-ticket", api_key,
                                               cidades=CIDADES, teto_cidade=6)
    aderentes = [x for x in brutos if x.get("adere")]
    # mais avaliação = mais movimento; é o melhor sinal de porte que o Places dá
    aderentes.sort(key=lambda x: (x.get("total_reviews") or 0), reverse=True)

    fora, n_franquia, cidades_vistas = [], 0, {}
    for l in aderentes:
        if len(fora) >= alvo:
            break
        eh_franquia = bool(FRANQUIAS.search(l.get("nome") or ""))
        if eh_franquia and n_franquia >= MAX_FRANQUIAS:
            continue
        c = l.get("cidade_origem")
        if cidades_vistas.get(c, 0) >= 3:   # não concentrar a lista numa praça só
            continue
        l["franquia"] = "sim" if eh_franquia else "não"
        fora.append(l)
        cidades_vistas[c] = cidades_vistas.get(c, 0) + 1
        n_franquia += eh_franquia
    return fora, {**diag, "franquias_na_lista": n_franquia,
                  "aderentes_disponiveis": len(aderentes), "cidades": cidades_vistas}


COLUNAS = ["ID", "Imobiliária", "Cidade", "Telefone/WhatsApp", "Site", "Instagram",
           "Franquia", "Nota Google", "Avaliações", "Tem site?", "Tier sugerido",
           "Gancho da ligação", "Status", "Notas"]


def _tier(l: dict) -> tuple[str, str]:
    """Sem site = T3 (o site é o produto). Com site = T4 (trocar o que existe)."""
    if not l.get("website"):
        return "T3", "não tem site — hoje o cliente só te acha pelo Google Maps"
    return "T4", "tem site, mas quem vende alto padrão precisa de vitrine à altura do imóvel"


def exportar(leads: list[dict], destino: str) -> str:
    with open(destino, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=COLUNAS)
        w.writeheader()
        for i, l in enumerate(leads, 1):
            tier, gancho = _tier(l)
            w.writerow({
                "ID": f"IM{i:03d}", "Imobiliária": l.get("nome") or "",
                "Cidade": l.get("cidade_origem") or "",
                "Telefone/WhatsApp": l.get("telefone") or "",
                "Site": l.get("website") or "", "Instagram": l.get("instagram") or "",
                "Franquia": l.get("franquia", "não"),
                "Nota Google": l.get("rating") or "", "Avaliações": l.get("total_reviews") or 0,
                "Tem site?": "sim" if l.get("website") else "NÃO",
                "Tier sugerido": tier, "Gancho da ligação": gancho,
                "Status": "A contatar",
                "Notas": l.get("endereco") or "",
            })
    return destino


if __name__ == "__main__":
    import json
    if "--selfcheck" in sys.argv:
        assert FRANQUIAS.search("RE/MAX Prime") and FRANQUIAS.search("Century 21 Bauru")
        assert not FRANQUIAS.search("Imobiliária Silva & Filhos")
        assert _tier({"website": ""})[0] == "T3" and _tier({"website": "x"})[0] == "T4"
        print("OK — self-check das imobiliárias passou.")
    else:
        destino = sys.argv[1] if len(sys.argv) > 1 else "/root/jpos-entregaveis/imobiliarias.csv"
        leads, diag = coletar(pedi_leads._chave())
        exportar(leads, destino)
        print(json.dumps({"total": len(leads), "csv": destino, "diagnostico": diag,
                          "franquias": [x["nome"] for x in leads if x["franquia"] == "sim"]},
                         ensure_ascii=False, indent=2))
