#!/usr/bin/env python3
"""Migração 001 — unifica a escala de score do Radar em 0-10.

PROBLEMA: `video_analises.score` era 1-5 (opinião do LLM), enquanto `auto_insights`
já usava 0-10. Duas escalas coexistindo na mesma base, sem conversão → o ranking/gate
não tinha como comparar. Esta migração rescala os registros antigos de 1-5 → 0-10.

MAPA (linear ×2): 1→2, 2→4, 3→6, 4→8, 5→10. Preserva a ORDEM e unifica a UNIDADE.
NÃO des-infla o histórico (isso só vem da rubrica nova sobre análises FUTURAS, ou de
um re-score que gastaria LLM — fora do escopo). auto_insights já é 0-10, não toca.

Idempotência: `PRAGMA user_version`. 0 = não migrado; vira 1 após migrar. Rodar 2x é
no-op. Belt-and-suspenders: só multiplica linhas com score entre 1 e 5 (linhas já
0-10 de código novo que tenha rodado antes ficam intactas).

Uso:
  python3 migracao_score_0a10.py [caminho_db] [--dry-run]
  (sem caminho → usa o noemi.db padrão do monorepo via shared_core.storage.db)
"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

VERSAO_ALVO = 1


def _dist(c: sqlite3.Connection) -> dict[int, int]:
    return {r[0]: r[1] for r in c.execute(
        "SELECT score, COUNT(*) FROM video_analises GROUP BY score ORDER BY score")}


def migrar(db_path: str, dry_run: bool = False) -> dict:
    """Rescala video_analises.score 1-5 → 0-10 (×2), guardado por user_version.
    Devolve {status, antes, depois, user_version}."""
    c = sqlite3.connect(db_path, timeout=10)
    try:
        uv = c.execute("PRAGMA user_version").fetchone()[0]
        if uv >= VERSAO_ALVO:
            return {"status": "ja_migrado", "user_version": uv, "antes": _dist(c), "depois": _dist(c)}
        antes = _dist(c)
        if dry_run:
            # simula o mapa sem gravar
            depois: dict[int, int] = {}
            for s, n in antes.items():
                depois[s * 2 if 1 <= s <= 5 else s] = depois.get(s * 2 if 1 <= s <= 5 else s, 0) + n
            return {"status": "dry_run", "user_version": uv, "antes": antes, "depois": depois}
        with c:  # transação atômica
            c.execute("UPDATE video_analises SET score = score * 2 WHERE score BETWEEN 1 AND 5")
            c.execute(f"PRAGMA user_version = {VERSAO_ALVO}")
        return {"status": "migrado", "user_version": VERSAO_ALVO,
                "antes": antes, "depois": _dist(c)}
    finally:
        c.close()


def _db_padrao() -> str:
    _AQUI = Path(__file__).resolve().parent
    sys.path.insert(0, str(_AQUI.parents[1] / "packages"))
    from shared_core.storage import db
    return str(db.data_dir() / "noemi.db")


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if a != "--dry-run"]
    dry = "--dry-run" in sys.argv

    if args and args[0] == "--selftest":
        # self-check isolado: db temporário, semeia 1-5, migra, valida ×2 + idempotência
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            p = str(Path(td) / "t.db")
            cc = sqlite3.connect(p)
            cc.execute("CREATE TABLE video_analises (id INTEGER PRIMARY KEY, score INT)")
            cc.executemany("INSERT INTO video_analises (score) VALUES (?)",
                           [(1,), (2,), (3,), (4,), (4,), (5,), (5,), (5,)])
            cc.commit(); cc.close()
            r1 = migrar(p, dry_run=True)
            assert r1["status"] == "dry_run" and r1["depois"] == {2: 1, 4: 1, 6: 1, 8: 2, 10: 3}, r1
            r2 = migrar(p)
            assert r2["status"] == "migrado" and r2["depois"] == {2: 1, 4: 1, 6: 1, 8: 2, 10: 3}, r2
            assert r2["user_version"] == 1, r2
            r3 = migrar(p)  # rodar de novo é no-op
            assert r3["status"] == "ja_migrado", r3
            # verifica no disco que os valores realmente dobraram e nada extrapolou 10
            cc = sqlite3.connect(p)
            mx = cc.execute("SELECT MAX(score) FROM video_analises").fetchone()[0]
            cc.close()
            assert mx == 10, mx
        print("migracao_score_0a10 OK — ×2, user_version→1, idempotente, teto 10")
        sys.exit(0)

    db_path = args[0] if args else _db_padrao()
    res = migrar(db_path, dry_run=dry)
    print(f"[{res['status']}] {db_path}  user_version={res['user_version']}")
    print("  antes :", res["antes"])
    print("  depois:", res["depois"])
