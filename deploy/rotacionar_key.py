#!/usr/bin/env python3
"""Troca UMA chave por outra em TODO lugar onde ela aparece, e diz o que reiniciar.

Por que existe: a varredura acha 19 chaves expostas e em produção, espalhadas por 6
arquivos .env em 3 repositórios — e a mesma chave Groq aparece em vários serviços.
Rotacionar à mão é caçar string em arquivo escondido no .gitignore, que é exatamente
como a marca antiga sobreviveu duas correções. Aqui é um comando por chave.

A chave VELHA é identificada por SHA (o que a varredura imprime), nunca digitada de
novo — assim ela não volta a ser colada em lugar nenhum, inclusive no seu histórico
de shell.

Uso:
    python rotacionar_key.py --sha 40ccf0ce --nova gsk_...      # troca
    python rotacionar_key.py --sha 40ccf0ce --nova gsk_... --aplicar
Sem --aplicar é SIMULAÇÃO: mostra arquivo e linha, não escreve nada.
"""
from __future__ import annotations

import argparse
import hashlib
import re
import subprocess
import sys
from pathlib import Path

# Onde chave de produção mora. Inclui caminhos GITIGNORADOS de propósito: foi
# justamente um deploy/*.env ignorado que manteve a produção errada enquanto o
# `grep` do repo versionado voltava limpo.
RAIZES = ("/root/noemi-infra", "/root/sdr-motor", "/root/radar-reels", "/root/jpos")

PADROES = (
    re.compile(r"gsk_[A-Za-z0-9]{40,}"),
    re.compile(r"re_[A-Za-z0-9_]{20,}"),
    re.compile(r"sk-ant-[A-Za-z0-9\-_]{30,}"),
    re.compile(r"sk-[A-Za-z0-9]{32,}"),
    re.compile(r"AIza[A-Za-z0-9\-_]{30,}"),
    re.compile(r"\b[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}"
               r"-[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}\b"),
)

# serviço a reiniciar quando um arquivo muda. Trocar a chave sem reiniciar deixa o
# processo antigo usando a chave revogada — falha silenciosa e confusa.
SERVICOS = {
    "noemi-infra/infra/.env": ["noemi-painel-obs"],
    "noemi-infra/.env": ["noemi-painel-obs"],
    "sdr-motor/.env": ["(container sdr-motor-* — rebuild/swap)"],
    "sdr-motor/deploy/papai.env": ["(container sdr-motor-papai — swap-papai.sh)"],
    "sdr-motor/deploy/papai.runtime.env": ["(container sdr-motor-papai — swap-papai.sh)"],
}


def _sha(v: str) -> str:
    return hashlib.sha256(v.encode()).hexdigest()[:8]


def achar(sha_alvo: str) -> list[tuple[Path, int, str]]:
    """[(arquivo, linha, valor)] de toda ocorrência da chave com aquele sha."""
    fora: list[tuple[Path, int, str]] = []
    for raiz in RAIZES:
        p = Path(raiz)
        if not p.exists():
            continue
        try:
            arqs = subprocess.run(
                ["find", str(p), "-name", "*.env*", "-o", "-name", "*.json", "-o",
                 "-name", "*.sh", "-o", "-name", "*.yml"],
                capture_output=True, text=True, timeout=90).stdout.split()
        except Exception:  # noqa: BLE001
            continue
        for f in arqs:
            fp = Path(f)
            if any(x in f for x in ("/node_modules/", "/.git/", "/.venv/")):
                continue
            try:
                linhas = fp.read_text(encoding="utf-8", errors="ignore").splitlines()
            except OSError:
                continue
            for i, ln in enumerate(linhas, 1):
                for rx in PADROES:
                    for m in rx.finditer(ln):
                        if _sha(m.group(0)) == sha_alvo:
                            fora.append((fp, i, m.group(0)))
    return fora


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sha", required=True, help="sha curto da chave VELHA (da varredura)")
    ap.add_argument("--nova", required=True, help="valor da chave NOVA")
    ap.add_argument("--aplicar", action="store_true", help="escreve (sem isto é simulação)")
    a = ap.parse_args()

    if _sha(a.nova) == a.sha:
        print("ERRO: a chave nova é IGUAL à velha. Gere uma nova de verdade.")
        sys.exit(2)
    if len(a.nova) < 20:
        print("ERRO: chave nova curta demais; conferir se colou inteira.")
        sys.exit(2)

    achados = achar(a.sha)
    if not achados:
        print(f"nenhuma ocorrência do sha {a.sha} — já rotacionada ou sha errado.")
        sys.exit(1)

    arquivos = sorted({str(f) for f, _, _ in achados})
    print(f"{len(achados)} ocorrência(s) em {len(arquivos)} arquivo(s):")
    for f, ln, _v in achados:
        print(f"  {str(f).replace('/root/','')}:{ln}")

    if not a.aplicar:
        print("\n(SIMULAÇÃO — nada foi escrito. Rode de novo com --aplicar)")
    else:
        velho = achados[0][2]
        for f in {f for f, _, _ in achados}:
            txt = f.read_text(encoding="utf-8", errors="ignore")
            f.write_text(txt.replace(velho, a.nova), encoding="utf-8")
        print(f"\n✅ trocada em {len(arquivos)} arquivo(s). Novo sha: {_sha(a.nova)}")

    precisa = sorted({s for f in arquivos for k, v in SERVICOS.items()
                      if f.endswith(k) for s in v})
    if precisa:
        print("\nREINICIAR (senão o processo antigo segue com a chave revogada):")
        for s in precisa:
            print(f"  • {s}")


if __name__ == "__main__":
    main()
