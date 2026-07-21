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
