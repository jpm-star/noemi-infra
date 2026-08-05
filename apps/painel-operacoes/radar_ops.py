#!/usr/bin/env python3
"""Radar como ORGANISMO: relatório semanal, alerta de padrão 3x e job noturno.

O Radar já colhe e analisa. O que faltava é ele AVISAR sem ser perguntado — hoje o
JP só descobre um padrão abrindo a Caixa de Ideias, e só descobre um gargalo quando
alguma coisa já quebrou.

  relatorio_semanal()  — volume analisado, o que entrou de novo, o que degradou.
  padroes_3x()         — tema/ferramenta que apareceu 3+ vezes: sinal, não ruído.
                         3 é o limiar que o harvest já usa pra "produto candidato".
  noturno()            — janela 2h-6h: lote grande de reprocessamento com a cota
                         inteira livre, sem competir com o uso do dia.

Uso:
    python radar_ops.py --relatorio     # imprime (e manda no Telegram se configurado)
    python radar_ops.py --padroes       # só os padrões 3x
    python radar_ops.py --noturno       # lote grande de reprocessamento
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.parse
import urllib.request
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path

_AQUI = Path(__file__).resolve().parent
sys.path.insert(0, str(_AQUI))
sys.path.insert(0, str(_AQUI.parents[1] / "packages"))

LIMIAR_PADRAO = int(os.environ.get("RADAR_LIMIAR_PADRAO", "3"))
_ESTADO = Path(os.environ.get("RADAR_OPS_ESTADO",
                              str(_AQUI.parents[1] / "data" / "radar_ops.json")))


def _db():
    from shared_core.storage import db
    return db.conn()


def _fonte(detalhe: str) -> str:
    try:
        return json.loads(detalhe or "{}").get("fonte", "") or "?"
    except ValueError:
        return "?"


def relatorio_semanal(dias: int = 7) -> dict:
    """O que o Radar viu na semana. Números que mudam decisão, não vaidade:
    quanto entrou, quanto virou insight de verdade, quanto degradou (= cota/bug),
    e de onde veio o sinal."""
    corte = (datetime.now(timezone.utc) - timedelta(days=dias)).isoformat()
    with _db() as c:
        linhas = [dict(r) for r in c.execute(
            "SELECT id,origem,categoria,score,detalhe,data,substr(insight,1,150) insight "
            "FROM video_analises WHERE data >= ? ORDER BY score DESC", (corte,))]
        total_base = c.execute("SELECT COUNT(*) FROM video_analises").fetchone()[0]
    fontes = Counter(_fonte(x["detalhe"]) for x in linhas)
    degradadas = fontes.get("extrativo", 0)
    bons = [x for x in linhas if x["score"] and x["score"] >= 7]
    return {
        "dias": dias, "analisadas": len(linhas), "base_total": total_base,
        "com_insight": fontes.get("llm", 0) + fontes.get("llm_parcial", 0),
        "degradadas": degradadas,
        "taxa_sucesso": round(100 * (len(linhas) - degradadas) / max(1, len(linhas))),
        "categorias": dict(Counter(x["categoria"] for x in linhas).most_common(5)),
        "origens": dict(Counter(x["origem"] for x in linhas if x["origem"]).most_common(5)),
        "destaques": [{"id": x["id"], "score": x["score"], "insight": x["insight"]}
                      for x in bons[:5]],
    }


def padroes_3x(limiar: int = 0) -> list[dict]:
    """Tema/ferramenta que apareceu N+ vezes. Repetição é o sinal: uma menção é
    curiosidade, três é tendência — é o mesmo limiar que a Caixa já usa."""
    limiar = limiar or LIMIAR_PADRAO
    import radar
    dados = radar.harvest_ideias(400)
    fora: list[dict] = []
    for f in (dados.get("ferramentas") or []):
        if int(f.get("mencoes") or 0) >= limiar:
            fora.append({"tipo": "ferramenta", "nome": f.get("nome", ""),
                         "vezes": f.get("mencoes"), "url": f.get("url", "")})
    # NÃO alertar sobre `tecnicas_persuasao`: vêm de uma TAXONOMIA FIXA de 14 itens,
    # então toda análise marca alguma e "165x especificidade" mede o vocabulário do
    # prompt, não o mundo. Alertar nisso seria ruído garantido — e alerta ruidoso para
    # de ser lido, que é como o alerta morre.
    #
    # Sinal de verdade é o que EMERGE: assinatura de tema (texto livre que o modelo
    # escreve) repetindo entre análises independentes.
    with _db() as c:
        temas = Counter()
        for (t, _s) in c.execute("SELECT detalhe, score FROM video_analises WHERE score >= 7"):
            try:
                d = json.loads(t or "{}")
            except ValueError:
                continue
            a = str(d.get("assinatura_tema") or "").strip().lower()
            if len(a) > 8:
                temas[a[:60]] += 1
    for nome, n in temas.most_common(10):
        if n >= limiar and nome:
            fora.append({"tipo": "tema", "nome": nome, "vezes": n, "url": ""})
    return sorted(fora, key=lambda x: -x["vezes"])


def _ja_avisou(chave: str) -> bool:
    try:
        d = json.loads(_ESTADO.read_text())
    except (OSError, ValueError):
        d = {}
    return chave in d.get("avisados", [])


def _marcar(chaves: list[str]) -> None:
    try:
        d = json.loads(_ESTADO.read_text())
    except (OSError, ValueError):
        d = {}
    d["avisados"] = sorted(set(d.get("avisados", [])) | set(chaves))
    _ESTADO.parent.mkdir(parents=True, exist_ok=True)
    _ESTADO.write_text(json.dumps(d))


def notificar(txt: str) -> bool:
    tok = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    chat = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
    if not (tok and chat):
        print(txt)
        return False
    try:
        u = (f"https://api.telegram.org/bot{tok}/sendMessage?"
             + urllib.parse.urlencode({"chat_id": chat, "text": txt[:3900]}))
        urllib.request.urlopen(u, timeout=20)
        return True
    except Exception:  # noqa: BLE001
        print(txt)
        return False


def texto_relatorio(r: dict) -> str:
    linhas = [f"📡 RADAR — últimos {r['dias']} dias", ""]
    linhas.append(f"analisadas: {r['analisadas']} (base: {r['base_total']})")
    linhas.append(f"viraram insight: {r['com_insight']} · taxa {r['taxa_sucesso']}%")
    if r["degradadas"]:
        linhas.append(f"⚠️ degradadas (LLM fora): {r['degradadas']} — o retry reprocessa sozinho")
    if r["categorias"]:
        linhas.append("")
        linhas.append("por tema: " + " · ".join(f"{k} {v}" for k, v in r["categorias"].items()))
    if r["origens"]:
        linhas.append("de onde veio: " + " · ".join(f"{k} {v}" for k, v in r["origens"].items()))
    if r["destaques"]:
        linhas.append("")
        linhas.append("o que valeu:")
        for d in r["destaques"]:
            linhas.append(f"  ★{d['score']} {d['insight'][:110]}")
    return "\n".join(linhas)


def noturno(lote: int = 20) -> dict:
    """Janela 2h-6h: reprocessa o degradado em LOTE GRANDE. De dia o retry vai de 3 em
    3 pra não competir com uso real; de madrugada a cota está inteira e ociosa."""
    import reanalisar
    return reanalisar.reanalisar(lote, aplicar=True)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--relatorio", action="store_true")
    ap.add_argument("--padroes", action="store_true")
    ap.add_argument("--noturno", action="store_true")
    ap.add_argument("--lote", type=int, default=20)
    a = ap.parse_args()
    if a.noturno:
        r = noturno(a.lote)
        print(f"noturno: {r['reanalisados']}/{r['total']} recuperados · {r['falharam']} falharam")
        return
    if a.padroes or not (a.relatorio or a.noturno):
        ps = padroes_3x()
        if not ps:
            print(f"nenhum padrão com {LIMIAR_PADRAO}+ ocorrências")
        novos = []
        for p in ps:
            marca = "🆕" if not _ja_avisou(f"{p['tipo']}:{p['nome']}") else "  "
            print(f"  {marca} {p['vezes']}x {p['tipo']}: {p['nome'][:60]}")
            if marca == "🆕":
                novos.append(p)
        if novos and not a.padroes:  # só notifica no modo automático
            txt = "🔁 PADRÃO REPETIDO no Radar (3x+):\n\n" + "\n".join(
                f"• {p['vezes']}x {p['tipo']}: {p['nome'][:70]}" for p in novos[:6])
            notificar(txt + "\n\nRepetição é sinal: vale olhar a Caixa de Ideias.")
            _marcar([f"{p['tipo']}:{p['nome']}" for p in novos])
        if not a.relatorio:
            return
    if a.relatorio:
        r = relatorio_semanal()
        txt = texto_relatorio(r)
        print(txt)
        notificar(txt)


if __name__ == "__main__":
    main()
