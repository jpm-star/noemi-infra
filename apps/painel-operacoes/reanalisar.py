#!/usr/bin/env python3
"""Reanalisa as análises que ficaram com score 0 POR FALHA DE LLM (fonte='extrativo').

O Radar degrada honesto: LLM fora => resumo extrativo, score 0, fonte='extrativo'.
O problema é que na tela isso fica IDÊNTICO a "vídeo ruim" — e 71% dos zeros (45 de 63)
eram falha de LLM, não conteúdo fraco. Um vídeo bom sobre rodar IA de 400B num Mac
(3060 chars de transcrição) virou nota 0.

Reusa a transcrição JÁ SALVA — não baixa vídeo de novo (custo zero, sem yt-dlp/Whisper).
Só reescreve a linha se a nova análise for de verdade (fonte='llm'); se o LLM ainda
estiver fora, deixa como está em vez de sobrescrever com outro degradado.

Uso:
    python reanalisar.py --ver          # lista os candidatos (não altera nada)
    python reanalisar.py --rodar        # reanalisa (default: 10 mais recentes)
    python reanalisar.py --rodar -n 45  # reanalisa todos
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "packages"))


def _db() -> sqlite3.Connection:
    from shared_core.storage import db
    c = db.conn()
    c.row_factory = sqlite3.Row
    return c


def candidatos(limite: int = 10) -> list[dict]:
    """score 0 + fonte extrativa + transcrição aproveitável, mais recentes primeiro."""
    fora: list[dict] = []
    with _db() as c:
        for r in c.execute("SELECT id,origem,url,data,categoria,score,transcricao,detalhe "
                           "FROM video_analises WHERE score=0 ORDER BY id DESC"):
            try:
                d = json.loads(r["detalhe"] or "{}")
            except ValueError:
                d = {}
            # '?' = análise antiga sem o campo fonte; tratada como candidata também
            if d.get("fonte") not in ("extrativo", None, "?", ""):
                continue
            t = (r["transcricao"] or "").strip()
            if len(t) < 80:  # sem transcrição não há o que reanalisar (é falha de captura)
                continue
            fora.append({"id": r["id"], "url": r["url"] or "", "origem": r["origem"] or "",
                         "data": (r["data"] or "")[:10], "transcricao": t})
            if len(fora) >= limite:
                break
    return fora


def reanalisar(limite: int = 10, aplicar: bool = False) -> dict:
    import radar
    alvos = candidatos(limite)
    ok, falhou, resultados = 0, 0, []
    for a in alvos:
        try:
            novo = radar._insight(a["transcricao"], contexto=[])
        except Exception as exc:  # noqa: BLE001
            falhou += 1
            resultados.append({**a, "erro": str(exc)[:120]})
            continue
        if novo.get("fonte") != "llm":
            # LLM ainda fora: NÃO sobrescreve (senão troca um degradado por outro)
            falhou += 1
            resultados.append({**a, "erro": "LLM ainda indisponível"})
            continue
        ok += 1
        resultados.append({**a, "score": novo["score"], "categoria": novo["categoria"],
                           "insight": novo["insight"], "novo": novo})
        if aplicar:
            with _db() as c:
                c.execute("UPDATE video_analises SET insight=?,categoria=?,score=?,tags=?,detalhe=? "
                          "WHERE id=?",
                          (novo["insight"], novo["categoria"], novo["score"],
                           json.dumps(novo.get("tags") or [], ensure_ascii=False),
                           json.dumps(novo, ensure_ascii=False), a["id"]))
                c.commit()
    return {"total": len(alvos), "reanalisados": ok, "falharam": falhou, "resultados": resultados}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--rodar", action="store_true", help="reanalisa de verdade (sem isto, só lista)")
    ap.add_argument("-n", type=int, default=10)
    a = ap.parse_args()
    if not a.rodar:
        for x in candidatos(a.n):
            print(f"#{x['id']} [{x['data']}] {len(x['transcricao'])} chars — {x['url'][:70]}")
        print("\n(use --rodar pra reanalisar)")
        return
    r = reanalisar(a.n, aplicar=True)
    print(f"\n{r['reanalisados']}/{r['total']} reanalisados · {r['falharam']} falharam\n")
    for x in r["resultados"]:
        if x.get("erro"):
            print(f"#{x['id']} ⚠️  {x['erro']}")
        else:
            print(f"#{x['id']} nota 0 → {x['score']} [{x['categoria']}]")
            print(f"   {x['insight'][:150]}")
            print(f"   {x['url'][:75]}\n")


if __name__ == "__main__":
    main()
