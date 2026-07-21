"""Interface de asset do monorepo — dict puro, disco local por padrão.

Asset: id, owner, produto, bucket, mime, hash, metadata.
ponytail: bucket = pasta em data/buckets/<produto>/; S3/R2 só quando um
segundo produto de verdade precisar de asset remoto.
"""
from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path

from .db import conn, data_dir


def _agora() -> str:
    return datetime.now(timezone.utc).isoformat()


def create_asset(owner: str, produto: str, mime: str, dados: bytes,
                 metadata: dict | None = None) -> dict:
    asset_id = uuid.uuid4().hex
    bucket = produto
    pasta = data_dir() / "buckets" / bucket
    pasta.mkdir(parents=True, exist_ok=True)
    (pasta / asset_id).write_bytes(dados)
    asset = {
        "id": asset_id,
        "owner": owner,
        "produto": produto,
        "bucket": bucket,
        "mime": mime,
        "hash": hashlib.sha256(dados).hexdigest(),
        "metadata": metadata or {},
        "criado_em": _agora(),
    }
    with conn() as c:
        c.execute(
            "INSERT INTO assets (id, owner, produto, bucket, mime, hash, metadata, criado_em) "
            "VALUES (:id, :owner, :produto, :bucket, :mime, :hash, :metadata_json, :criado_em)",
            {**asset, "metadata_json": json.dumps(asset["metadata"], ensure_ascii=False)},
        )
    return asset


def get_asset(asset_id: str) -> dict | None:
    with conn() as c:
        row = c.execute("SELECT * FROM assets WHERE id=?", (asset_id,)).fetchone()
    if not row:
        return None
    asset = dict(row)
    asset["metadata"] = json.loads(asset["metadata"])
    return asset


def asset_file(asset: dict) -> Path:
    return data_dir() / "buckets" / asset["bucket"] / asset["id"]


def delete_asset(asset_id: str) -> None:
    asset = get_asset(asset_id)
    if not asset:
        return
    asset_file(asset).unlink(missing_ok=True)
    with conn() as c:
        c.execute("DELETE FROM assets WHERE id=?", (asset_id,))


def update_asset_meta(asset_id: str, extra_meta: dict) -> dict | None:
    """Mescla extra_meta na metadata do asset, sem tocar nos bytes/arquivo."""
    asset = get_asset(asset_id)
    if not asset:
        return None
    with conn() as c:
        c.execute(
            "UPDATE assets SET metadata=? WHERE id=?",
            (json.dumps({**asset["metadata"], **extra_meta}, ensure_ascii=False), asset_id),
        )
    return get_asset(asset_id)


def replace_asset_bytes(asset_id: str, dados: bytes, mime: str,
                        extra_meta: dict | None = None) -> dict | None:
    """Sobrescreve os bytes de um asset mantendo o MESMO id (e portanto a URL e
    a FK jobs.asset_origem). Atualiza mime/hash e mescla extra_meta. É a base
    da normalização in-place da mídia de entrada."""
    asset = get_asset(asset_id)
    if not asset:
        return None
    asset_file(asset).write_bytes(dados)
    meta = {**asset["metadata"], **(extra_meta or {})}
    with conn() as c:
        c.execute(
            "UPDATE assets SET mime=?, hash=?, metadata=? WHERE id=?",
            (mime, hashlib.sha256(dados).hexdigest(),
             json.dumps(meta, ensure_ascii=False), asset_id),
        )
    return get_asset(asset_id)


def purge_asset_file(asset_id: str) -> bool:
    """Apaga só o ARQUIVO do asset (libera disco), preservando a linha no DB —
    a FK jobs.asset_origem e a proveniência ficam intactas. Marca metadata.
    Usado pela retenção; delete_asset (linha+arquivo) é pra órfão sem FK."""
    asset = get_asset(asset_id)
    if not asset:
        return False
    f = asset_file(asset)
    if not f.exists():
        return False
    f.unlink()
    update_asset_meta(asset_id, {"arquivo_removido": True})
    return True


def registrar_interacao(produto: str, *, cliente: str | None = None,
                        segmento: str | None = None, input: dict | None = None,
                        output: dict | None = None, modelo: str | None = None,
                        handoff_whatsapp: bool | None = None) -> int:
    """Registra UMA interação REAL (não-mock) na tabela interacoes — fundação
    honesta pro tuning futuro. NÃO é tuning: só guarda input/output/segmento/
    handoff pra quando houver volume o histórico já existir. Devolve o id.
    Fica intocada enquanto tudo é mock (o chamador gateia por não-mock)."""
    with conn() as c:
        cur = c.execute(
            "INSERT INTO interacoes (ts, produto, cliente, segmento, input, output, modelo, handoff_whatsapp) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (_agora(), produto, cliente, segmento,
             json.dumps(input, ensure_ascii=False) if input is not None else None,
             json.dumps(output, ensure_ascii=False) if output is not None else None,
             modelo,
             None if handoff_whatsapp is None else int(handoff_whatsapp)),
        )
    return cur.lastrowid


def contar_interacoes(produto: str | None = None) -> int:
    with conn() as c:
        if produto:
            return c.execute("SELECT COUNT(*) FROM interacoes WHERE produto=?", (produto,)).fetchone()[0]
        return c.execute("SELECT COUNT(*) FROM interacoes").fetchone()[0]
