"""Backfill de registro em `sites_gerados` para sites criados fora do painel.

O problema: `origem_captacao` só é editável pela UI em site que TEM linha em
`sites_gerados` — a galeria une tabela ∪ disco, e o que só existe no disco sai como
"sem registro", sem select. 43 dos 76 nasceram de script em lote, sem essa linha.

O que este script faz: cria a linha que falta, com `origem_captacao='desconhecida'`.
Não deduz origem de nome, pasta nem data — desconhecida é a verdade sobre eles.
Reclassificação é manual, pelo painel, depois.

O que NÃO faz: não toca nas linhas existentes (só INSERT de slug ausente), não valida
origem (isso é do `captacao`), não renomeia nada.

Rodar:
  python backfill_registro.py            # dry-run: mostra o que faria
  python backfill_registro.py --aplicar  # grava
Idempotente: rodar de novo não duplica (o slug já estará na tabela).
"""
from __future__ import annotations

import os
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "packages"))  # repo/packages

import captacao  # noqa: E402 — só PADRAO e garantir_coluna; a validação é dele, não daqui

SITES_DIR = Path(os.environ.get("SITE_OUT_DIR", "/var/www/sites"))
BASE_URL = os.environ.get("SITE_BASE_URL", "https://p.jpos.com.br")


def _sites_no_disco() -> list[Path]:
    """Dirs que são site de CLIENTE. `_acervo` (fotos por nicho) e `_lib` (assets
    compartilhados) são infraestrutura do motor: não têm dono, não têm index.html,
    não entram na tabela de clientes."""
    if not SITES_DIR.exists():
        return []
    return sorted(d for d in SITES_DIR.iterdir()
                  if d.is_dir() and not d.name.startswith("_") and (d / "index.html").exists())


def _criado_em(d: Path) -> str:
    """Data do site a partir do DISCO — a de verdade não existe pra esses 41.

    mtime do index.html NÃO serve: uma injeção de beacon em lote reescreveu todos no
    mesmo minuto (2026-08-14 20:00), o que dataria o acervo inteiro de "hoje" e jogaria
    41 sites antigos pro topo da galeria (que ordena por criado_em desc).
    ponytail: mtime do DIRETÓRIO — aproxima a geração (as subpáginas e o robots.txt são
    daquele momento) e nunca inventa "hoje". Data exata? Só o birthtime do inode
    (`stat -c %w`), que o Python 3.12 no Linux não expõe — subir pra ele é trocar esta
    linha, se algum dia a ordem exata importar.
    """
    return datetime.fromtimestamp(d.stat().st_mtime, timezone.utc).isoformat()


def _slugs_na_tabela(c) -> set[str]:
    return {r[0] for r in c.execute("SELECT DISTINCT slug FROM sites_gerados")}


def pendentes(c) -> list[Path]:
    """Sites no disco sem nenhuma linha em sites_gerados — os que a UI mostra
    como 'sem registro'."""
    tem = _slugs_na_tabela(c)
    return [d for d in _sites_no_disco() if d.name not in tem]


def backfill(aplicar: bool = False) -> dict:
    """Cria a linha faltante de cada site órfão. Devolve contagem antes/depois."""
    from shared_core.storage import db
    with db.conn() as c:
        captacao.garantir_coluna(c)
        antes = len(_slugs_na_tabela(c))
        faltam = pendentes(c)
        if aplicar and faltam:
            # cliente = slug: é o que a galeria já exibe pros órfãos hoje. Derivar um
            # nome "bonito" do slug seria inventar razão social que ninguém digitou.
            c.executemany(
                "INSERT INTO sites_gerados (cliente,segmento,slug,url,criado_em,origem_captacao) "
                "VALUES (?,?,?,?,?,?)",
                [(d.name, "", d.name, f"{BASE_URL}/{d.name}/", _criado_em(d), captacao.PADRAO)
                 for d in faltam])
            c.commit()
        depois = len(_slugs_na_tabela(c))
        restam = len(pendentes(c))
    return {"aplicado": bool(aplicar), "registrados_antes": antes, "registrados_depois": depois,
            "inseridos": [d.name for d in faltam] if aplicar else [],
            "a_inserir": [d.name for d in faltam], "sem_registro_agora": restam}


if __name__ == "__main__":
    if os.environ.get("BACKFILL_SELFTEST"):  # self-check: DB e disco temporários
        import tempfile

        os.environ["NOEMI_DATA_DIR"] = tempfile.mkdtemp(suffix="_backfill")
        SITES_DIR = Path(tempfile.mkdtemp(suffix="_sites"))
        for nome in ("ja-tem-linha", "orfao-um", "orfao-dois"):
            (SITES_DIR / nome).mkdir()
            (SITES_DIR / nome / "index.html").write_text("<html>x</html>", encoding="utf-8")
        (SITES_DIR / "_lib").mkdir()  # infraestrutura: nunca vira cliente
        (SITES_DIR / "sem-index").mkdir()  # pasta sem site: idem
        # o index reescrito depois (beacon em lote) não pode virar a data do site
        antigo = 1_750_000_000  # 2025-06-15
        os.utime(SITES_DIR / "orfao-um", (antigo, antigo))

        from shared_core.storage import db

        with db.conn() as c:
            c.execute("CREATE TABLE IF NOT EXISTS sites_gerados (id INTEGER PRIMARY KEY "
                      "AUTOINCREMENT, cliente TEXT NOT NULL, segmento TEXT, slug TEXT NOT NULL, "
                      "url TEXT NOT NULL, criado_em TEXT NOT NULL)")
            c.execute("INSERT INTO sites_gerados (cliente,segmento,slug,url,criado_em) VALUES "
                      "('Já Tem','padaria','ja-tem-linha','http://x','2026-01-01')")
            c.commit()

        # 1) dry-run não grava
        r = backfill()
        assert r["a_inserir"] == ["orfao-dois", "orfao-um"], r
        assert r["registrados_depois"] == 1, r

        # 2) aplicar registra só os órfãos de site real
        r = backfill(aplicar=True)
        assert r["registrados_antes"] == 1 and r["registrados_depois"] == 3, r
        assert r["sem_registro_agora"] == 0, r
        assert "_lib" not in r["inseridos"] and "sem-index" not in r["inseridos"], r

        # 3) origem gravada é 'desconhecida' — nada inventado
        with db.conn() as c:
            linhas = {r[0]: r[1:] for r in c.execute(
                "SELECT slug, origem_captacao, criado_em FROM sites_gerados")}
        assert linhas["orfao-um"][0] == captacao.PADRAO, linhas
        assert linhas["ja-tem-linha"][0] is None, "linha existente foi alterada"

        # 4) data vem do disco, não de "agora" (senão o legado sobe pro topo da galeria)
        assert linhas["orfao-um"][1].startswith("2025-06"), linhas["orfao-um"]

        # 5) a linha antiga não foi duplicada nem sobrescrita
        with db.conn() as c:
            assert c.execute("SELECT COUNT(*) FROM sites_gerados WHERE slug='ja-tem-linha'"
                             ).fetchone()[0] == 1

        # 6) idempotente
        r = backfill(aplicar=True)
        assert r["inseridos"] == [] and r["registrados_depois"] == 3, r

        # 7) o site backfillado agora é marcável pelo caminho REAL da UI
        assert "orfao-um" in captacao.por_slug(), "select continuaria desligado"
        assert captacao.marcar("orfao-um", "indicacao_pessoal")["ok"] is True

        print("backfill OK — dry-run não grava, registra só site real (pula _lib e pasta "
              "sem index), origem='desconhecida', data do disco (não 'hoje'), não toca "
              "linha existente, idempotente, e o site backfillado fica marcável")
    else:
        aplicar = "--aplicar" in sys.argv[1:]
        r = backfill(aplicar=aplicar)
        for s in (r["inseridos"] if aplicar else r["a_inserir"]):
            print(("+ " if aplicar else "  (faria) ") + s)
        print(f"\nregistrados: {r['registrados_antes']} -> {r['registrados_depois']}  "
              f"| sem registro: {r['sem_registro_agora']}")
        if not aplicar and r["a_inserir"]:
            print("nada foi gravado. rode com --aplicar pra valer.")
