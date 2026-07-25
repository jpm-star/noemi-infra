"""Camada 3 — SCORING determinístico (ZERO LLM). Fórmula/regra pura.

Recebe um lead já enriquecido (dict) e devolve score + tier + motivo + se passa
o corte de fila. Tudo função pura: mesmo input → mesmo output, sem I/O, sem LLM.
"""
from __future__ import annotations

# pesos da "dor" (quanto MENOS a clínica tem, mais precisa da Noemi)
_DOR_SEM_SITE = 40
_DOR_ABANDONADO = 30
_DOR_SEM_WA = 20
_DOR_SEM_CHAT = 10

# corte de fila de ligação
_CORTE_REVIEWS = 80
_CORTE_RATING = 4.3


def score_movimento(total_reviews: int, rating: float) -> float:
    """0-100: o quanto a clínica se MEXE (prova de operação). Reviews saturam em
    200 (uma clínica com 200+ avaliações já é 'movimentada'); pondera pela nota."""
    tr = max(0, int(total_reviews or 0))
    r = max(0.0, min(5.0, float(rating or 0)))
    reviews_norm = min(1.0, tr / 200.0)
    return round(reviews_norm * (r / 5.0) * 100, 1)


def score_dor(lead: dict) -> int:
    """0-100: soma dos sinais de dor (o que falta e a Noemi resolve)."""
    return (_DOR_SEM_SITE * int(bool(lead.get("sem_site")))
            + _DOR_ABANDONADO * int(bool(lead.get("site_abandonado")) and not lead.get("sem_site"))
            + _DOR_SEM_WA * int(bool(lead.get("sem_wa_button")))
            + _DOR_SEM_CHAT * int(bool(lead.get("sem_chat"))))


def _sem_wa(lead: dict) -> bool:
    # sem site também é "sem botão de WhatsApp", mas já pontua em sem_site;
    # aqui só conta quando TEM site e mesmo assim não tem wa.me.
    return bool(not lead.get("sem_site") and not lead.get("tem_wa_button"))


def _sem_chat(lead: dict) -> bool:
    return bool(not lead.get("sem_site") and not lead.get("tem_chat"))


def tier(lead: dict) -> tuple[str, str]:
    """(tier_sugerido, motivo). Ordem de precedência: multi-unidade (conta grande)
    > sem site > site ruim + reclamação > site bom recente."""
    if int(lead.get("n_unidades") or 1) >= 2:
        return "T4", f"{lead['n_unidades']} unidades no Maps — conta maior, projeto completo"
    if lead.get("sem_site"):
        return "T2", "sem site — âncora: site+SEO daqui pra cima"
    if lead.get("site_abandonado") and lead.get("reviews_reclamam_demora"):
        return "T3", f"site abandonado ({lead.get('ano_rodape') or '?'}) + reviews reclamam de demora"
    if lead.get("site_abandonado"):
        return "T2", f"site abandonado ({lead.get('ano_rodape') or '?'}) — refazer + Noemi"
    if lead.get("site_de_agencia") and not lead.get("site_abandonado"):
        return "T1", "site bom recente (agência ativa) — só Noemi ou descartar"
    return "T2", "site fraco — porta de entrada por site+Noemi"


def motivo_da_dor(lead: dict) -> str:
    """Frase legível pros vendedores (Lincon/Rodrigo) — por que ligar."""
    m = []
    if lead.get("sem_site"):
        m.append("SEM SITE")
    elif lead.get("site_abandonado"):
        m.append(f"site abandonado ({lead.get('ano_rodape') or '?'})")
    if _sem_wa(lead):
        m.append("sem botão WhatsApp")
    if _sem_chat(lead):
        m.append("sem chat/atendimento")
    if lead.get("reviews_reclamam_demora"):
        m.append("reviews reclamam de demora")
    if int(lead.get("n_unidades") or 1) >= 2:
        m.append(f"{lead['n_unidades']} unidades")
    return " · ".join(m) or "sinais fracos"


def passa_corte(lead: dict) -> bool:
    """Entra na fila de ligação só quem tem MOVIMENTO real E pelo menos 1 dor.
    reviews>=80 OU (rating>=4.3 E atividade recente), E score_dor>0."""
    tr = int(lead.get("total_reviews") or 0)
    rt = float(lead.get("rating") or 0)
    movimento_ok = tr >= _CORTE_REVIEWS or (rt >= _CORTE_RATING and bool(lead.get("atividade_recente")))
    return movimento_ok and score_dor(lead) > 0


def pontuar(lead: dict) -> dict:
    """Enriquece o lead com os campos de scoring (não muta o original)."""
    l = dict(lead)
    l["sem_wa_button"] = _sem_wa(lead)
    l["sem_chat"] = _sem_chat(lead)
    mov = score_movimento(l.get("total_reviews"), l.get("rating"))
    dor = score_dor(l)
    t, _mot_tier = tier(l)
    l.update({
        "score_movimento": mov, "score_dor": dor,
        "score_final": round(mov * dor / 100.0, 1),  # produto normalizado 0-100
        "tier_sugerido": t, "motivo_da_dor": motivo_da_dor(l),
        "passa_corte": passa_corte(l),
    })
    return l


if __name__ == "__main__":  # self-check: cada branch de tier + corte
    sem_site = {"total_reviews": 120, "rating": 4.6, "sem_site": True, "atividade_recente": True}
    r = pontuar(sem_site)
    assert r["tier_sugerido"] == "T2" and r["score_dor"] >= 40 and r["passa_corte"], r

    aband = {"total_reviews": 90, "rating": 4.1, "site_abandonado": True, "ano_rodape": 2019,
             "reviews_reclamam_demora": True, "tem_wa_button": False, "tem_chat": False}
    r = pontuar(aband)
    assert r["tier_sugerido"] == "T3" and r["passa_corte"], r

    multi = {"total_reviews": 300, "rating": 4.5, "n_unidades": 3, "tem_wa_button": True,
             "tem_chat": True, "atividade_recente": True}
    assert pontuar(multi)["tier_sugerido"] == "T4"

    bom = {"total_reviews": 200, "rating": 4.8, "site_de_agencia": True, "tem_wa_button": True,
           "tem_chat": True, "atividade_recente": True}
    rb = pontuar(bom)
    assert rb["tier_sugerido"] == "T1" and not rb["passa_corte"], rb  # sem dor → fora da fila

    fraco = {"total_reviews": 10, "rating": 4.9, "sem_site": True}  # movimento baixo
    assert not pontuar(fraco)["passa_corte"], "reviews<80 e sem atividade recente não passa"
    print("scoring OK — T2/T3/T4/T1, corte de fila e sem-dor-fora validados")
