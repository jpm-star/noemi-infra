"""Logging de interação REAL (não-mock) — fundação honesta pro tuning futuro.

Prova o contrato central: mock NUNCA registra (tabela fica vazia até tráfego
real); geração real registra input/output/segmento/cliente/modelo.
"""
import asyncio
import base64
import json

import jobs
import worker
from shared_core import storage
from shared_core.storage.db import conn

PNG_1PX = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="
)


def test_registrar_e_contar_roundtrip():
    n0 = storage.contar_interacoes("motor-b-video")
    iid = storage.registrar_interacao(
        produto="motor-b-video", cliente="jp", segmento="imobiliaria",
        input={"prompt": "casa"}, output={"url": "x"}, modelo="claude-opus-4-8",
        handoff_whatsapp=True)
    assert iid > 0
    assert storage.contar_interacoes("motor-b-video") == n0 + 1
    with conn() as c:
        row = c.execute("SELECT * FROM interacoes WHERE id=?", (iid,)).fetchone()
    assert row["handoff_whatsapp"] == 1
    assert json.loads(row["input"])["prompt"] == "casa"


def test_mock_nao_registra():
    asset = storage.create_asset("t", jobs.PRODUTO, "image/png", PNG_1PX)
    job = jobs.criar(asset["id"], {"duration": 1})
    n0 = storage.contar_interacoes()
    asyncio.run(worker.processar(job))
    assert jobs.obter(job["id"])["estado"] == "completed"
    assert storage.contar_interacoes() == n0, "mock não pode registrar interação"


def test_geracao_real_registra(monkeypatch):
    asset = storage.create_asset("cliente-x", jobs.PRODUTO, "image/png", PNG_1PX)
    job = jobs.criar(asset["id"], {"duration": 1, "prompt": "casa na praia", "segmento": "imobiliaria"})

    def fake_generate(origem, config):  # simula provider real (não-mock)
        return {"bytes": PNG_1PX, "mime": "video/mp4", "modelo": "claude-opus-4-8",
                "meta": {"url_provider": "https://x/v.mp4"}}

    monkeypatch.setattr(worker.video, "generate", fake_generate)
    n0 = storage.contar_interacoes("motor-b-video")
    asyncio.run(worker.processar(job))
    assert jobs.obter(job["id"])["estado"] == "completed"
    assert storage.contar_interacoes("motor-b-video") == n0 + 1
    with conn() as c:
        row = c.execute("SELECT * FROM interacoes ORDER BY id DESC LIMIT 1").fetchone()
    assert row["produto"] == "motor-b-video" and row["cliente"] == "cliente-x"
    assert row["segmento"] == "imobiliaria" and row["modelo"] == "claude-opus-4-8"
    assert json.loads(row["input"])["prompt"] == "casa na praia"
    assert row["handoff_whatsapp"] is None  # não aplicável ao vídeo
