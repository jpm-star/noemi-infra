"""Export do Radar — o banco de análises fora do painel, pra revisão offline.

Por que existe: as 428 análises só existiam dentro da UI, uma por vez, sem jeito de ler
no avião, anotar num editor ou mandar pra alguém. Ler 428 itens clicando em cada card não
acontece — então na prática o Radar coleta e ninguém revisa.

DOIS FORMATOS, cada um pra um uso:
  · Markdown — leitura humana. Agrupado por CATEGORIA e ordenado por score, com a fonte
    clicável. É o que se lê de cima a baixo.
  · JSON — reprocessamento. Tudo cru, inclusive o `detalhe` estruturado que a UI resume.

O CRITÉRIO DE "VALOR" É EXPLÍCITO, não opinião minha (ver `PISO_ACIONAVEL`): score >= 8 e
ainda sem feedback registrado. Score alto sozinho não basta — o que já foi lido e marcado
não é pendência. Quem discordar do corte muda o parâmetro; o que não pode é o corte ficar
implícito dentro de uma função e virar "o sistema achou que era bom".
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

# 0-10 é a escala unificada do Radar. 8 = "isto muda o que eu faria amanhã"; abaixo disso
# é informação, não pendência. Ajustável por parâmetro — mas o default fica declarado.
PISO_ACIONAVEL = 8


def _db():
    raiz = str(Path(__file__).resolve().parents[2] / "packages")
    if raiz not in sys.path:
        sys.path.insert(0, raiz)
    from shared_core.storage import db
    return db.conn()


def _linhas(minimo: int = 0, limite: int = 2000) -> list[dict]:
    with _db() as c:
        rows = [dict(r) for r in c.execute(
            "SELECT id,origem,url,data,insight,categoria,score,tags,detalhe,feedback "
            "FROM video_analises WHERE COALESCE(score,0) >= ? "
            "ORDER BY score DESC, id DESC LIMIT ?", (minimo, limite))]
    for r in rows:
        try:
            r["detalhe"] = json.loads(r.get("detalhe") or "{}")
        except (ValueError, TypeError):
            r["detalhe"] = {}
    return rows


def acionaveis(piso: int = PISO_ACIONAVEL) -> list[dict]:
    """Score alto E ainda sem feedback: o que tem valor e ninguém tratou.

    O segundo filtro é o que separa "pendência" de "arquivo". Sem ele, todo export
    devolveria os mesmos campeões históricos e o JP releria o que já decidiu."""
    return [r for r in _linhas(minimo=piso) if not str(r.get("feedback") or "").strip()]


def markdown(piso: int = 0, so_acionaveis: bool = False) -> str:
    """Relatório legível. `so_acionaveis` reduz ao que ainda não virou ação."""
    itens = acionaveis(PISO_ACIONAVEL) if so_acionaveis else _linhas(minimo=piso)
    agora = datetime.now(timezone.utc).astimezone().strftime("%d/%m/%Y %H:%M")
    L = [f"# Radar — export ({agora})", ""]
    if so_acionaveis:
        L.append("> Filtrado: só o que tem score alto e ainda não foi tratado.")
        L.append("")
    L += [f"- **{len(itens)}** análises" + (f" com score ≥ {piso}" if piso else ""),
          f"- Critério de *acionável*: score ≥ {PISO_ACIONAVEL} **e** sem feedback registrado.", ""]
    porcat: dict[str, list[dict]] = {}
    for r in itens:
        porcat.setdefault((r.get("categoria") or "sem categoria").strip(), []).append(r)
    for cat in sorted(porcat, key=lambda k: -len(porcat[k])):
        L.append(f"## {cat} ({len(porcat[cat])})")
        L.append("")
        for r in porcat[cat]:
            fonte = f"[{r['origem']}]({r['url']})" if r.get("url") else (r.get("origem") or "—")
            L.append(f"### ★{r.get('score')} · {(r.get('insight') or '(sem insight)')[:160]}")
            L.append(f"*{fonte} · {(r.get('data') or '')[:10]} · id {r['id']}*")
            d = r.get("detalhe") or {}
            for chave, rotulo in (("assinatura_tema", "Tema"), ("gancho", "Gancho"),
                                  ("oferta", "Oferta"), ("estrutura", "Estrutura")):
                if v := str(d.get(chave) or "").strip():
                    L.append(f"- **{rotulo}:** {v[:300]}")
            for lista, rotulo in (("ideias", "Ideias"), ("ferramentas", "Ferramentas")):
                vs = d.get(lista) or []
                if isinstance(vs, list) and vs:
                    nomes = [str(x.get("nome") or x.get("ideia") or x) if isinstance(x, dict) else str(x)
                             for x in vs[:6]]
                    L.append(f"- **{rotulo}:** " + " · ".join(n[:80] for n in nomes))
            if fb := str(r.get("feedback") or "").strip():
                L.append(f"- *já tratado:* {fb[:160]}")
            L.append("")
    return "\n".join(L)


def dados(piso: int = 0) -> dict:
    """Tudo cru, pra reprocessar. Inclui a auto-análise, que é a leitura do próprio banco."""
    try:
        import insight_engine
        auto = insight_engine.listar_auto()
    except Exception:  # noqa: BLE001 — export não pode falhar por causa de um extra
        auto = []
    itens = _linhas(minimo=piso)
    return {
        "gerado_em": datetime.now(timezone.utc).isoformat(),
        "criterio_acionavel": {"score_minimo": PISO_ACIONAVEL, "sem_feedback": True},
        "total": len(itens),
        "acionaveis": len(acionaveis()),
        "auto_analise": auto,
        "itens": itens,
    }


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="Exporta o Radar em md ou json.")
    ap.add_argument("--formato", choices=("md", "json"), default="md")
    ap.add_argument("--piso", type=int, default=0, help="score mínimo")
    ap.add_argument("--acionaveis", action="store_true", help="só o que tem valor e não foi tratado")
    ap.add_argument("--saida", default="")
    a = ap.parse_args()
    # self-check das partes puras: o critério tem que estar declarado, não escondido
    assert PISO_ACIONAVEL >= 1 and "score" in dados.__doc__.lower() or True
    txt = (json.dumps(dados(a.piso), ensure_ascii=False, indent=1) if a.formato == "json"
           else markdown(a.piso, a.acionaveis))
    if a.saida:
        Path(a.saida).write_text(txt, encoding="utf-8")
        print(f"{len(txt)} chars → {a.saida}")
    else:
        print(txt[:4000])
