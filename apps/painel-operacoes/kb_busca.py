"""Caixa de Ideias — busca semântica + dedup sobre `video_analises` (Fase 0 do KOS).

Vetoriza cada análise (embeddings.gerar → Gemini) e guarda em `kb_embeddings`.
Puro código do projeto, SEM Ruflo. API pronta pra consumir:
  indexar()   → vetoriza análises novas
  buscar(q)   → top-k por similaridade semântica
  duplicados()→ pares quase-idênticos (dedup)
Best-effort: sem chave de embedding → indexa 0 / busca [] (degrada, nunca crasha).
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone


def _db() -> sqlite3.Connection:
    from shared_core.storage import db
    c = db.conn()
    c.row_factory = sqlite3.Row
    c.execute("CREATE TABLE IF NOT EXISTS kb_embeddings ("
              "analise_id INTEGER PRIMARY KEY, vec TEXT, criado_em TEXT)")
    c.commit()
    return c


def _texto(row: sqlite3.Row) -> str:
    """Texto representativo da análise pra embutir (resumo + insight + sinais do schema novo)."""
    det = {}
    try:
        det = json.loads(row["detalhe"] or "{}")
    except (ValueError, TypeError):
        det = {}
    partes = [row["insight"] or "", det.get("resumo", ""), det.get("assinatura_tema", ""),
              " ".join(det.get("tecnicas_persuasao") or []),
              " ".join((row["tags"] or "").split(","))]
    return " · ".join(p for p in partes if p)[:2000]


def indexar(limite: int = 500, _embed=None) -> dict:
    """Vetoriza as análises ainda não indexadas. Devolve {indexados, ja}."""
    from shared_core.ai import embeddings
    embed = _embed or embeddings.gerar
    with _db() as c:
        ja = {r[0] for r in c.execute("SELECT analise_id FROM kb_embeddings")}
        rows = [r for r in c.execute("SELECT id, insight, tags, detalhe FROM video_analises "
                                     "ORDER BY id DESC LIMIT ?", (limite * 2,)) if r["id"] not in ja][:limite]
        if not rows:
            return {"indexados": 0, "ja": len(ja)}
        vecs = embed([_texto(r) for r in rows])
        agora = datetime.now(timezone.utc).isoformat()
        n = 0
        for r, v in zip(rows, vecs):
            if v:
                c.execute("INSERT OR REPLACE INTO kb_embeddings (analise_id, vec, criado_em) VALUES (?,?,?)",
                          (r["id"], json.dumps(v), agora))
                n += 1
        c.commit()
    return {"indexados": n, "ja": len(ja)}


def buscar(q: str, k: int = 8, _embed=None) -> list[dict]:
    """Busca semântica: top-k análises mais próximas de `q`."""
    from shared_core.ai import embeddings
    embed = _embed or embeddings.gerar
    qv = embed([q])
    if not qv or not qv[0]:
        return []
    qv = qv[0]
    with _db() as c:
        emb = {r["analise_id"]: json.loads(r["vec"]) for r in c.execute("SELECT analise_id, vec FROM kb_embeddings")}
        if not emb:
            return []
        ranked = sorted(((embeddings.cosseno(qv, v), aid) for aid, v in emb.items()), reverse=True)[:k]
        ids = [aid for _, aid in ranked]
        ph = ",".join("?" * len(ids))
        meta = {r["id"]: dict(r) for r in c.execute(
            f"SELECT id, origem, url, insight, categoria, score FROM video_analises WHERE id IN ({ph})", ids)}
    return [{"sim": round(s, 4), **(meta.get(aid) or {"id": aid})} for s, aid in ranked if aid in meta]


def duplicados(threshold: float = 0.90, _embed=None) -> list[dict]:
    """Pares de análises quase-idênticas (sim >= threshold) — pra dedup da Caixa de Ideias."""
    from shared_core.ai import embeddings
    with _db() as c:
        emb = [(r["analise_id"], json.loads(r["vec"])) for r in c.execute("SELECT analise_id, vec FROM kb_embeddings")]
    pares = []
    for i in range(len(emb)):
        for j in range(i + 1, len(emb)):
            s = embeddings.cosseno(emb[i][1], emb[j][1])
            if s >= threshold:
                pares.append({"a": emb[i][0], "b": emb[j][0], "sim": round(s, 4)})
    return sorted(pares, key=lambda p: -p["sim"])


if __name__ == "__main__":  # self-check offline: DB temp + embedder MOCK (keyword flags)
    import os
    import tempfile
    os.environ["NOEMI_DATA_DIR"] = tempfile.mkdtemp(suffix="_kbtest")
    con = sqlite3.connect(os.environ["NOEMI_DATA_DIR"] + "/noemi.db")
    con.execute("CREATE TABLE video_analises (id INTEGER PRIMARY KEY AUTOINCREMENT, origem TEXT, url TEXT, "
                "data TEXT, transcricao TEXT, insight TEXT, categoria TEXT, score REAL, tags TEXT, detalhe TEXT, feedback TEXT)")
    for ins, tags in [("dica de escassez e urgencia", "escassez,urgencia"),
                      ("mesma dica de escassez urgencia", "escassez,urgencia"),  # ~dup do 1º
                      ("como fazer um site que converte", "site,conversao")]:
        con.execute("INSERT INTO video_analises (origem, insight, tags, detalhe) VALUES ('@x',?,?,?)",
                    (ins, tags, json.dumps({"resumo": ins, "assinatura_tema": tags})))
    con.commit(); con.close()

    _KW = ["escassez", "urgencia", "site"]
    def mock(textos):  # vetor por presença de keyword (determinístico)
        return [[1.0 if kw in t.lower() else 0.0 for kw in _KW] for t in textos]

    r = indexar(_embed=mock)
    assert r["indexados"] == 3, r
    achados = buscar("quero site", k=2, _embed=mock)
    assert achados and "site" in (achados[0]["insight"] or ""), achados
    dups = duplicados(threshold=0.99, _embed=mock)
    assert dups and {dups[0]["a"], dups[0]["b"]} == {1, 2}, dups   # as 2 dicas de escassez
    print("kb_busca OK — indexar, buscar semântico (mock), dedup acha o par quase-idêntico")
