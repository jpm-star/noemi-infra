"""Recuperação em lote dos 14 demos que `casar_demos.py` não conseguiu ver.

Por que existe: 13 destes sites foram gerados por uma versão anterior do motor, que escrevia
`<title>Academia Bellator</title>` em vez de `<title>academia em Assis | Academia Bellator</title>`.
`casar_demos.sites()` descarta quem não segue o padrão — então esses 13 saem do universo antes
de qualquer pontuação. O 14º (`academia-prime-gym`) tem `<title>` certo, mas a cidade vem
`'Bauru - SP'` e o lead diz `'Bauru'`: cidade não bate, sobra 1 token distintivo, score 0.

Ver `RELATORIO_DEMOS_ORFAOS.md` para a medição completa.

Por que a tabela é escrita à mão e não gerada: casar por nome afrouxado é exatamente o que o
usuário proibiu. Cada linha abaixo foi conferida uma a uma contra o CRM. É uma correção de
14 linhas feita uma vez, não uma regra nova de matching.

    python recuperar_demos_lote.py            # mostra o que faria
    python recuperar_demos_lote.py --aplicar  # grava
    python recuperar_demos_lote.py --check    # autoteste

Idempotente por herança: usa `casar_demos.aplicar()`, que só grava onde `demo_url` está vazia.
"""

import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import casar_demos as cd  # noqa: E402

# (lead_id, nome esperado no CRM, pasta em /var/www/sites)
# O nome esperado não é decoração: gravar por ID fixo num banco que pode ser reimportado é a
# única forma deste script apontar o demo de um negócio para o telefone de outro. Se o nome
# mudou, o ID já não é quem eu conferi — aborta em vez de gravar.
LOTE = [
    (739, "Academia Bellator", "academia-bellator"),
    (546, "Academia Body Express", "academia-body-express-botucatu"),
    (567, "Academia Cia Bio Fit", "academia-cia-bio-fit-jau"),
    (553, "CTM Academia", "ctm-academia-marilia"),
    (701, "Espaço Vip", "espaco-vip-adamantina"),
    (544, "Academia Forma e Força", "academia-forma-e-forca-marilia"),
    (627, "Malibu Exclusive", "malibu-exclusive-aracatuba"),
    (584, "Red Dragon Gym", "red-dragon-gym-presidente-prudente"),
    (556, "Academia Ricodo", "academia-ricodo-botucatu"),
    (555, "Academia Tito Coló", "academia-tito-colo-jau"),
    (690, "Academia VidAtiva", "academia-vidativa-birigui"),
    (708, "Winner Academia", "winner-academia-marilia"),
    (554, "Academia XPLOUD", "academia-xploud-assis"),
    # este não é formato de <title>, é normalização de cidade: 'Bauru - SP' vs 'Bauru'
    (54, "ACADEMIA PRIME GYM", "academia-prime-gym"),
]

# 6 destes negócios têm DUAS pastas (`academia-bellator` e `academia-bellator-assis`, e o mesmo
# par com prefixo `academia-` para CTM, Espaço Vip, Malibu, Red Dragon, Winner). Critério usado
# acima: ganha a pasta com mais conteúdo; empate, o slug mais curto. Só a Bellator tem diferença
# real (13 arquivos com foto contra 1 arquivo); os outros 5 pares são byte a byte iguais fora o
# próprio slug. As pastas perdedoras continuam no ar — ninguém aponta para elas.


def pares(db: Path | None = None) -> list[dict]:
    """Valida cada linha do LOTE contra disco e CRM. Erro em qualquer uma aborta o lote todo:
    meia gravação num CRM é pior que nenhuma, porque ninguém sabe onde parou."""
    db = db or cd.LEADS_DB
    with sqlite3.connect(db) as c:
        linhas = c.execute("SELECT id, empresa, demo_url FROM tracker_prospects").fetchall()
    atual = {i: (e, d) for i, e, d in linhas}
    out, erros = [], []
    for lid, nome, slug in LOTE:
        if not (cd.SITES_DIR / slug / "index.html").is_file():
            erros.append(f"#{lid}: pasta {slug!r} não existe em {cd.SITES_DIR}")
            continue
        if lid not in atual:
            erros.append(f"#{lid}: lead sumiu do CRM")
            continue
        emp, demo = atual[lid]
        # o CRM tem sufixos que o site não tem ('Malibu Exclusive Araçatuba - SP', 'Winner
        # Academia - Unidade I'). Basta o nome esperado ser prefixo do que está gravado.
        esperado, tem = cd._norm(nome).split(), cd._norm(emp).split()
        if tem[:len(esperado)] != esperado:
            erros.append(f"#{lid}: esperava {nome!r}, CRM tem {emp!r} — IDs andaram")
            continue
        out.append({"lead_id": lid, "empresa": emp, "slug": slug,
                    "url": f"{cd.BASE_SITES}/{slug}/", "demo_atual": demo or ""})
    if erros:
        raise SystemExit("ABORTADO, nada gravado:\n  " + "\n  ".join(erros))
    return out


def _autoteste() -> None:
    import tempfile

    with tempfile.TemporaryDirectory() as d:
        db = Path(d) / "t.db"
        with sqlite3.connect(db) as c:
            c.execute("CREATE TABLE tracker_prospects (id INTEGER PRIMARY KEY, empresa TEXT, "
                      "demo_url TEXT)")
            # o CRM de mentira reproduz os sufixos reais que quase derrubaram a checagem
            sufixo = {627: " Araçatuba - SP", 708: " - Unidade I", 690: " Birigui"}
            c.executemany("INSERT INTO tracker_prospects VALUES (?,?,?)",
                          [(i, n + sufixo.get(i, ""), "") for i, n, _ in LOTE])
            c.execute("UPDATE tracker_prospects SET demo_url='https://mao.humana/ja/' WHERE id=554")

        assert len(pares(db)) == len(LOTE), "sufixo do CRM não pode reprovar o nome"

        # ID que virou outra empresa aborta o lote INTEIRO, não só a própria linha
        with sqlite3.connect(db) as c:
            c.execute("UPDATE tracker_prospects SET empresa='Padaria do Zé' WHERE id=739")
        try:
            pares(db)
            raise AssertionError("devia ter abortado com ID trocado")
        except SystemExit as e:
            assert "IDs andaram" in str(e), e
        with sqlite3.connect(db) as c:
            c.execute("UPDATE tracker_prospects SET empresa='Academia Bellator' WHERE id=739")

        # grava 13: o #554 já tem demo_url posta à mão e mão humana ganha do script
        n = cd.aplicar(pares(db), db)
        assert n == len(LOTE) - 1, f"devia gravar {len(LOTE) - 1}, gravou {n}"
        with sqlite3.connect(db) as c:
            urls = dict(c.execute("SELECT id, demo_url FROM tracker_prospects"))
        assert urls[554] == "https://mao.humana/ja/", urls[554]
        assert urls[739].endswith("/academia-bellator/"), urls[739]
        assert urls[54].endswith("/academia-prime-gym/"), urls[54]

        # rodar de novo não regrava nada
        assert cd.aplicar(pares(db), db) == 0, "não é idempotente"
    print("autoteste ok")


if __name__ == "__main__":
    if "--check" in sys.argv[1:]:
        _autoteste()
        sys.exit(0)

    lote = pares()
    novos = [p for p in lote if not p["demo_atual"].strip()]
    for p in lote:
        marca = "" if p in novos else "  (já tem demo_url — não mexo)"
        print(f"  #{p['lead_id']:<5} {p['empresa'][:34]:<34} -> {p['url']}{marca}")
    print(f"\n{len(lote)} conferidos · {len(novos)} a gravar")

    if "--aplicar" in sys.argv[1:]:
        print(f"gravados: {cd.aplicar(lote)} demo_url")
    else:
        print("nada gravado. rode com --aplicar pra valer.")
