"""Camada 1 — COLETA via Google Places API (Text Search + Place Details).

NÃO faz scraping do HTML do Maps (ilegal + quebra). Usa a API oficial. Dedupe
por place_id. Detecta multi-unidade (mesmo nome, endereços diferentes),
reclamação de demora nas reviews e atividade recente — tudo por regra, sem LLM.

`coletar(...)` aceita `get` injetável (teste offline). Sem api_key = levanta
FaltaChave (o orquestrador avisa o JP). Endpoints legados (textsearch/details),
que é o que "ativar Places API" habilita.
"""
from __future__ import annotations

import re
import time
from datetime import datetime, timezone

_TEXTSEARCH = "https://maps.googleapis.com/maps/api/place/textsearch/json"
_DETAILS = "https://maps.googleapis.com/maps/api/place/details/json"
_CAMPOS = ("name,formatted_phone_number,international_phone_number,website,rating,"
           "user_ratings_total,formatted_address,opening_hours,reviews,geometry")

CATEGORIAS_PADRAO = ("clínica odontológica", "clínica de estética", "fisioterapia",
                     "clínica médica", "clínica veterinária")
# grid de volume: termos GRANULARES → cada busca traz resultados distintos (o texto
# search satura em ~60/query; mais queries segmentadas = mais lead novo por célula).
CATEGORIAS_GRID = (
    "dentista", "implante dentário", "ortodontia", "clínica odontológica", "harmonização facial",
    "clínica de estética", "depilação a laser", "fisioterapia", "pilates clínico", "clínica médica",
    "dermatologista", "nutricionista", "psicólogo", "clínica veterinária", "pet shop", "quiropraxia")

_DEMORA = ("demora", "demorou", "demorad", "espera", "esperei", "esperar", "fila",
           "atras", "não atende", "nao atende", "não atendem", "ninguém atende",
           "ninguem atende", "horas de espera", "muito tempo")


class FaltaChave(RuntimeError):
    """Sem GOOGLE_PLACES_API_KEY — o script não roda (dependência humana)."""


def _norm_nome(n: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (n or "").lower())


def _reviews_reclamam_demora(reviews: list) -> bool:
    txt = " ".join((r.get("text") or "").lower() for r in (reviews or []))
    return any(k in txt for k in _DEMORA)


def _atividade_recente(reviews: list, agora: float, dias: int = 365) -> bool:
    corte = agora - dias * 86400
    return any(float(r.get("time") or 0) >= corte for r in (reviews or []))


def coletar(cidade: str, categorias=CATEGORIAS_PADRAO, *, api_key: str = "",
            limite: int = 20, get=None, agora: float | None = None,
            bairro: str = "") -> list[dict]:
    """Leads da cidade (dedupe por place_id, ~limite no total). `bairro` segmenta a
    busca (célula do grid → mais resultados distintos por área). get injetável (teste)."""
    if not api_key:
        raise FaltaChave("defina GOOGLE_PLACES_API_KEY (Google Cloud → ativar Places API)")
    _get = get or _get_http
    agora = agora if agora is not None else datetime.now(timezone.utc).timestamp()
    local = f"{bairro}, {cidade}" if bairro else cidade
    por_id: dict[str, dict] = {}
    for cat in categorias:
        busca = _get(_TEXTSEARCH, {"query": f"{cat} em {local}, SP",
                                   "language": "pt-BR", "key": api_key})
        for r in (busca.get("results") or []):
            pid = r.get("place_id")
            if not pid or pid in por_id:
                continue
            det = (_get(_DETAILS, {"place_id": pid, "fields": _CAMPOS,
                                   "language": "pt-BR", "key": api_key}).get("result") or {})
            reviews = det.get("reviews") or []
            hor = det.get("opening_hours") or {}
            por_id[pid] = {
                "place_id": pid, "cidade_origem": cidade, "categoria": cat,
                "nome": det.get("name") or r.get("name"),
                "telefone": det.get("formatted_phone_number") or det.get("international_phone_number"),
                "website": det.get("website") or "",
                "rating": det.get("rating") or r.get("rating") or 0,
                "total_reviews": det.get("user_ratings_total") or r.get("user_ratings_total") or 0,
                "endereco": det.get("formatted_address") or r.get("formatted_address"),
                "horario": " | ".join(hor.get("weekday_text") or []),
                "reviews_reclamam_demora": _reviews_reclamam_demora(reviews),
                "atividade_recente": _atividade_recente(reviews, agora),
            }
            if len(por_id) >= limite:
                break
        if len(por_id) >= limite:
            break
        if get is None:
            time.sleep(0.2)  # gentileza com a API (rate)
    leads = list(por_id.values())
    _marcar_unidades(leads)
    return leads


def _marcar_unidades(leads: list[dict]) -> None:
    """n_unidades: quantas vezes o MESMO nome aparece com place_id diferente
    (2+ endereços = rede → tier T4). Muta os leads in-place."""
    contagem: dict[str, int] = {}
    for l in leads:
        contagem[_norm_nome(l["nome"])] = contagem.get(_norm_nome(l["nome"]), 0) + 1
    for l in leads:
        l["n_unidades"] = contagem[_norm_nome(l["nome"])]


def _get_http(url: str, params: dict) -> dict:
    import httpx
    try:
        with httpx.Client(timeout=20.0) as c:
            r = c.get(url, params=params)
            return r.json() if r.status_code == 200 else {}
    except Exception:  # noqa: BLE001 — uma busca falha, o lote segue
        return {}


if __name__ == "__main__":  # self-check: coleta com get MOCK (sem key real, sem rede)
    def fake_get(url, params):
        if "textsearch" in url:
            return {"results": [
                {"place_id": "p1", "name": "Clínica Sorriso"},
                {"place_id": "p2", "name": "Clínica Sorriso"},   # 2ª unidade
                {"place_id": "p3", "name": "Vida Estética"}]}
        pid = params["place_id"]
        base = {"p1": {"name": "Clínica Sorriso", "website": "http://a.com", "rating": 4.5,
                       "user_ratings_total": 130, "reviews": [{"text": "demora muito", "time": 9e9}]},
                "p2": {"name": "Clínica Sorriso", "website": "", "rating": 4.2, "user_ratings_total": 40},
                "p3": {"name": "Vida Estética", "website": "http://v.com", "rating": 4.7,
                       "user_ratings_total": 210, "reviews": []}}
        return {"result": base.get(pid, {})}
    leads = coletar("Lins", ["clínica médica"], api_key="fake", get=fake_get, agora=9e9 + 1)
    porid = {l["place_id"]: l for l in leads}
    assert len(leads) == 3 and porid["p1"]["n_unidades"] == 2  # Sorriso x2
    assert porid["p1"]["reviews_reclamam_demora"] and porid["p1"]["atividade_recente"]
    assert porid["p3"]["n_unidades"] == 1
    try:
        coletar("Lins", api_key="")
        raise SystemExit("deveria exigir chave")
    except FaltaChave:
        pass
    print("coleta OK — dedupe, multi-unidade, demora, atividade; exige chave")
