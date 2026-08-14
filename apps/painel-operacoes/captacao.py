"""Origem de captação do cliente — indicação pessoal vs. prospecção fria.

Por que existe: o JP vai instalar T1 grátis em 5 leads que já conhece em
Lins/Cafelândia, em troca de indicação. A pergunta que isso responde não é "os 5
sites ficaram prontos", é "quantos viraram T2 fechado por essa via". Sem a tag, a
resposta vira anedota.

Onde mora: coluna `origem_captacao` em `sites_gerados` — a tabela onde o cliente
NASCE quando é provisionado. Assim a tag existe antes da primeira visita.

NÃO reusa `insights_cliente.origem_ref`: aquele campo é a proveniência do ACHADO
("beacon"), não o canal de aquisição do CLIENTE. São duas perguntas diferentes e
juntá-las apaga as duas.

Retrocompatibilidade: os 52 sites já provisionados ficam com NULL, que este módulo
lê como "desconhecida". Nada quebra e nada é inventado — desconhecida é a verdade
sobre eles, não um erro.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "packages"))  # repo/packages

PADRAO = "desconhecida"
# Conjunto FECHADO de propósito: é o que torna a taxa de conversão por via
# calculável. Precisa de uma via nova (ex: "inbound")? Uma linha aqui.
ORIGENS = (PADRAO, "indicacao_pessoal", "prospeccao_fria")


def garantir_coluna(c) -> None:
    """Cria `origem_captacao` se não existir. Idempotente — pode rodar sempre."""
    cols = {r[1] for r in c.execute("PRAGMA table_info(sites_gerados)")}
    if "origem_captacao" not in cols:
        c.execute("ALTER TABLE sites_gerados ADD COLUMN origem_captacao TEXT")


def normalizar(v: str | None) -> str:
    """Valor cru → origem válida. Vazio/None/desconhecido → 'desconhecida'."""
    s = (v or "").strip().lower().replace("-", "_").replace(" ", "_")
    return s if s in ORIGENS else PADRAO


def marcar(chave: str, origem: str) -> dict:
    """Marca a origem de um cliente já provisionado. `chave` = slug OU nome da empresa.
    Devolve {"ok":bool, ...} — nunca levanta por origem inválida, explica."""
    from shared_core.storage import db
    o = (origem or "").strip().lower().replace("-", "_").replace(" ", "_")
    if o not in ORIGENS:
        return {"ok": False, "erro": f"origem {origem!r} inválida. Use uma de: {', '.join(ORIGENS)}"}
    k = (chave or "").strip()
    if not k:
        return {"ok": False, "erro": "informe o slug ou o nome da empresa"}
    with db.conn() as c:
        garantir_coluna(c)
        n = c.execute("UPDATE sites_gerados SET origem_captacao=? WHERE slug=? OR cliente=?",
                      (o, k, k)).rowcount
        c.commit()
    if not n:
        return {"ok": False, "erro": f"nenhum site provisionado com slug ou nome {k!r}"}
    return {"ok": True, "chave": k, "origem": o, "linhas": n}


def por_slug() -> dict[str, str]:
    """slug -> origem, para todos os sites provisionados. Slug ausente = 'desconhecida'."""
    from shared_core.storage import db
    with db.conn() as c:
        garantir_coluna(c)
        return {r[0]: normalizar(r[1]) for r in c.execute(
            "SELECT slug, origem_captacao FROM sites_gerados WHERE slug IS NOT NULL")}


def de_cliente(chave: str) -> str:
    """Origem de UM cliente (slug ou nome). Nunca levanta: desconhecido → 'desconhecida'."""
    from shared_core.storage import db
    try:
        with db.conn() as c:
            garantir_coluna(c)
            r = c.execute("SELECT origem_captacao FROM sites_gerados "
                          "WHERE slug=? OR cliente=? ORDER BY id DESC LIMIT 1",
                          (chave, chave)).fetchone()
    except Exception:  # noqa: BLE001 — atribuição nunca derruba o relatório
        return PADRAO
    return normalizar(r[0] if r else None)


def placar() -> dict[str, int]:
    """Quantos sites provisionados por via. É o numerador da pergunta do JP."""
    from shared_core.storage import db
    out: dict[str, int] = {o: 0 for o in ORIGENS}
    with db.conn() as c:
        garantir_coluna(c)
        # DISTINCT no par: sites_gerados tem linha repetida por regeração do mesmo slug
        for _slug, o in c.execute("SELECT DISTINCT slug, origem_captacao FROM sites_gerados"):
            out[normalizar(o)] += 1
    return out


def _uso() -> str:
    return (f"uso:\n"
            f"  python captacao.py marcar <slug-ou-nome> <{'|'.join(ORIGENS[1:])}>\n"
            f"  python captacao.py listar\n"
            f"  python captacao.py placar")


if __name__ == "__main__":
    import os

    if os.environ.get("CAPTACAO_SELFTEST"):  # self-check: DB temp, sem rede
        import tempfile
        os.environ["NOEMI_DATA_DIR"] = tempfile.mkdtemp(suffix="_captacao")
        from shared_core.storage import db

        with db.conn() as c:  # tabela como ela é hoje, SEM a coluna nova
            c.execute("CREATE TABLE IF NOT EXISTS sites_gerados (id INTEGER PRIMARY KEY "
                      "AUTOINCREMENT, cliente TEXT NOT NULL, segmento TEXT, slug TEXT NOT NULL, "
                      "url TEXT NOT NULL, criado_em TEXT NOT NULL, prospect_id INTEGER)")
            c.execute("INSERT INTO sites_gerados (cliente,segmento,slug,url,criado_em) "
                      "VALUES ('Padaria do Zé','padaria','padaria-do-ze','http://x','2026-01-01')")
            c.commit()

        # 1) cliente ANTERIOR à coluna (o caso de retrocompatibilidade) => desconhecida
        assert de_cliente("padaria-do-ze") == PADRAO, "site legado não deveria virar erro"

        # 2) migração é idempotente
        with db.conn() as c:
            garantir_coluna(c); garantir_coluna(c); c.commit()

        # 3) marcar por slug e por NOME da empresa
        assert marcar("padaria-do-ze", "indicacao_pessoal")["ok"] is True
        assert de_cliente("padaria-do-ze") == "indicacao_pessoal"
        assert de_cliente("Padaria do Zé") == "indicacao_pessoal", "busca por nome falhou"

        # 4) origem inválida NÃO grava e explica
        r = marcar("padaria-do-ze", "boca_a_boca")
        assert r["ok"] is False and "inválida" in r["erro"], r
        assert de_cliente("padaria-do-ze") == "indicacao_pessoal", "valor bom foi sobrescrito"

        # 5) cliente inexistente é erro claro, não silêncio
        assert marcar("nao-existe", "prospeccao_fria")["ok"] is False

        # 6) normalização tolerante na ENTRADA, fechada na SAÍDA
        assert normalizar("Indicacao-Pessoal") == "indicacao_pessoal"
        assert normalizar(None) == PADRAO and normalizar("qualquer coisa") == PADRAO

        # 7) placar conta por via
        assert placar()["indicacao_pessoal"] == 1, placar()
        print("captacao OK — legado vira 'desconhecida' (não erro), migração idempotente, "
              "marca por slug e por nome, recusa origem inválida sem apagar a boa, placar")
    else:
        a = sys.argv[1:]
        if a[:1] == ["marcar"] and len(a) == 3:
            r = marcar(a[1], a[2])
            print(("✓ " if r["ok"] else "✗ ") + str(r.get("erro") or
                  f"{r['chave']} marcado como {r['origem']} ({r['linhas']} linha(s))"))
            sys.exit(0 if r["ok"] else 1)
        elif a[:1] == ["listar"]:
            for slug, o in sorted(por_slug().items()):
                print(f"{o:20} {slug}")
        elif a[:1] == ["placar"]:
            for k, v in placar().items():
                print(f"{v:4}  {k}")
        else:
            print(_uso())
            sys.exit(2)
