"""Interface FIXA de geração de vídeo: video.generate(asset, config).

Nenhum app chama provider pelo nome (higgsfield/kling) — só esta função.

>>> PONTO DE TROCA mock → real (ver README raiz): MOCK_MODE=false no ambiente
>>> roteia pra providers/higgsfield_video.generate. Nada mais muda.

Contrato de retorno (dict): bytes, mime, modelo, custo_creditos, meta.
"""
from __future__ import annotations

import os


def generate(asset: dict, config: dict) -> dict:
    if os.environ.get("MOCK_MODE", "true").lower() != "false":
        from .providers import mock_video
        return mock_video.generate(asset, config)
    from .providers import higgsfield_video
    return higgsfield_video.generate(asset, config)
