#!/usr/bin/env python3
"""Varre logs/transcrições atrás de chave colada em texto puro e manda rotacionar.

Por que existe (#6): chave foi colada no chat 5 vezes hoje — Groq (24 de uma vez),
CNPJá, Gemini, Resend. Cada vez, alguém precisou PERCEBER e avisar. Isso é trabalho
de máquina: o padrão de cada provider é reconhecível, e comparar com o que está em
uso diz na hora se a chave exposta é a de produção ou uma já morta.

Não imprime valor de chave — só o provider, o sha curto e ONDE apareceu.

Uso:  python varrer_keys_expostas.py                 # varre os caminhos padrão
      python varrer_keys_expostas.py /caminho /outro # varre o que você mandar
"""
from __future__ import annotations

import hashlib
import os
import re
import subprocess
import sys
from pathlib import Path

# Padrão por provider. Prefixo + tamanho mínimo: pega a chave real sem casar com
# qualquer string aleatória (falso positivo vira ruído e o alerta some).
PADROES = {
    "Groq":     re.compile(r"gsk_[A-Za-z0-9]{40,}"),
    "Resend":   re.compile(r"re_[A-Za-z0-9_]{20,}"),
    "OpenAI":   re.compile(r"sk-[A-Za-z0-9]{32,}"),
    "Anthropic": re.compile(r"sk-ant-[A-Za-z0-9\-_]{30,}"),
    "Google":   re.compile(r"AIza[A-Za-z0-9\-_]{30,}"),
    "CNPJá":    re.compile(r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"
                           r"-[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b"),
}
# Onde chave vaza na prática: transcrição de sessão, log de serviço, histórico de shell.
PADRAO_CAMINHOS = [
    "/root/.claude/projects",
    "/root/.bash_history",
    "/root/noemi-infra/data",
]


def _sha(v: str) -> str:
    return hashlib.sha256(v.encode()).hexdigest()[:8]


def em_uso() -> dict[str, str]:
    """{sha -> onde} das chaves que estão nos .env — pra dizer se a exposta é VIVA."""
    fora: dict[str, str] = {}
    try:
        arqs = subprocess.run(
            ["find", "/root", "-name", "*.env", "-not", "-path", "*/node_modules/*",
             "-not", "-path", "*/.claude/*"], capture_output=True, text=True, timeout=60).stdout.split()
    except Exception:  # noqa: BLE001
        return fora
    for f in arqs:
        try:
            txt = open(f, encoding="utf-8", errors="ignore").read()
        except OSError:
            continue
        for _prov, rx in PADROES.items():
            for m in rx.finditer(txt):
                fora.setdefault(_sha(m.group(0)), f.replace("/root/", ""))
    return fora


def varrer(caminhos: list[str]) -> list[dict]:
    vivas = em_uso()
    achados: dict[str, dict] = {}
    for raiz in caminhos:
        p = Path(raiz)
        arquivos = [p] if p.is_file() else (
            [x for x in p.rglob("*") if x.is_file() and x.stat().st_size < 80_000_000]
            if p.is_dir() else [])
        for arq in arquivos:
            try:
                txt = arq.read_text(encoding="utf-8", errors="ignore")
            except (OSError, ValueError):
                continue
            for prov, rx in PADROES.items():
                for m in rx.finditer(txt):
                    v = m.group(0)
                    s = _sha(v)
                    if s not in achados:
                        achados[s] = {"provider": prov, "sha": s, "onde": [],
                                      "em_uso": vivas.get(s, "")}
                    onde = str(arq).replace("/root/", "")
                    if onde not in achados[s]["onde"]:
                        achados[s]["onde"].append(onde)
    return sorted(achados.values(), key=lambda x: (not x["em_uso"], x["provider"]))


def main() -> None:
    caminhos = sys.argv[1:] or PADRAO_CAMINHOS
    caminhos = [c for c in caminhos if Path(c).exists()]
    achados = varrer(caminhos)
    if not achados:
        print("✅ nenhuma chave em texto puro nos caminhos varridos")
        return
    criticas = [a for a in achados if a["em_uso"]]
    print(f"⚠️  {len(achados)} chave(s) em texto puro · {len(criticas)} AINDA EM USO\n")
    for a in achados:
        marca = "🔴 EM USO" if a["em_uso"] else "⚪ não está em nenhum .env"
        print(f"  {marca}  {a['provider']:10s} sha:{a['sha']}")
        if a["em_uso"]:
            print(f"      usada em: {a['em_uso']}")
        for o in a["onde"][:2]:
            print(f"      exposta em: {o[:88]}")
    if criticas:
        print(f"\n🔴 ROTACIONAR {len(criticas)} chave(s): estão expostas E em produção.")
        sys.exit(1)


if __name__ == "__main__":
    main()
