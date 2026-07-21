"""Cost tracking via decorator — todo provider de IA passa por aqui."""
from __future__ import annotations

import functools
import time

from shared_core.obs import log_span


def track_cost(provider: str):
    def deco(fn):
        @functools.wraps(fn)
        def wrapper(asset: dict, config: dict) -> dict:
            t0 = time.monotonic()
            try:
                out = fn(asset, config)
                log_span("ai.video.generate", provider=provider, ok=True,
                         dur_s=round(time.monotonic() - t0, 2),
                         modelo=out.get("modelo"),
                         custo_creditos=out.get("custo_creditos", 0),
                         asset=asset.get("id"))
                return out
            except Exception as e:
                log_span("ai.video.generate", provider=provider, ok=False,
                         dur_s=round(time.monotonic() - t0, 2),
                         erro=str(e), asset=asset.get("id"))
                raise
        return wrapper
    return deco
