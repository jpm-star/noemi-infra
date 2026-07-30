"""Guarda de testes (raiz) — NUNCA rodar pytest contra banco de PRODUÇÃO.

Causa raiz do incidente que truncou prod: uma DSN/caminho de banco de produção
exportado no shell + suíte que escreve/trunca. Este hook aborta a suíte inteira
ANTES de coletar qualquer teste se alguma variável de banco apontar pra prod
(sem marcador `_test`). Escape hatch explícito: `ALLOW_PROD_DB=1`.
"""
from __future__ import annotations

import os

import pytest

# arquivos de banco de PRODUÇÃO conhecidos deste repo (SQLite)
_PROD_MARKERS = ("data/leads.db", "data/noemi.db", "data/leads_massa.db",
                 "sdr_motor", "evolution")
# variáveis que apontam banco e que, se setadas pra prod, são perigosas em teste
_VARS_BANCO = ("LEADS_DB", "NOEMI_DB", "DATABASE_URL", "SQLALCHEMY_DATABASE_URI",
               "NOEMI_DATA_DIR", "DSN", "PGDATABASE")


def _e_teste(valor: str) -> bool:
    v = valor.lower()
    return "_test" in v or "/tmp/" in v or "tmpdir" in v or "tempfile" in v or "memory" in v


def _aponta_prod(valor: str) -> bool:
    if _e_teste(valor):
        return False
    v = valor.lower()
    # arquivo/nome de prod conhecido, OU uma DSN de rede (://) sem 'test'
    return any(m in v for m in _PROD_MARKERS) or ("://" in v and "test" not in v)


def pytest_configure(config) -> None:  # roda antes da coleta
    if os.environ.get("ALLOW_PROD_DB") == "1":
        return  # o operador assumiu o risco conscientemente
    suspeitos = {var: os.environ[var] for var in _VARS_BANCO
                 if os.environ.get(var) and _aponta_prod(os.environ[var])}
    if suspeitos:
        pytest.exit(
            "GUARDA DE TESTES ABORTOU: variável(is) de banco apontando pra PRODUÇÃO "
            f"(sem marcador _test): {suspeitos}. Rodar pytest assim pode TRUNCAR dados "
            "reais. Aponte pra um banco _test/temp, ou exporte ALLOW_PROD_DB=1 se souber "
            "o que está fazendo.",
            returncode=3)
