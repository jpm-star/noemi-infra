"""Observabilidade mínima: log_span() fire-and-forget.

ponytail: JSONL local em data/obs.jsonl; mesmo contrato vira export pro
Langfuse quando houver credencial — nenhum chamador muda.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone


def log_span(nome: str, **campos) -> None:
    try:
        from shared_core.storage.db import data_dir  # tardio: evita ciclo de import

        linha = {"ts": datetime.now(timezone.utc).isoformat(), "span": nome, **campos}
        with open(data_dir() / "obs.jsonl", "a", encoding="utf-8") as f:
            f.write(json.dumps(linha, ensure_ascii=False, default=str) + "\n")
    except Exception:
        pass  # observabilidade nunca derruba fluxo de negócio
