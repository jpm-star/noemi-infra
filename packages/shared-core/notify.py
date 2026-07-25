"""Notificação out-of-band (Telegram) — interface fixa `telegram(texto) -> bool`.

Um lugar só pro envio (alerta de saúde + ping de venda usam este). Best-effort:
sem token/chat configurado = no-op silencioso (False), nunca levanta. urllib
stdlib, sem dep nova. Env: TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID.
"""
from __future__ import annotations

import os
import urllib.parse
import urllib.request


def telegram(texto: str) -> bool:
    """Manda `texto` pro chat configurado. False se não configurado/falhou —
    fire-and-forget, o chamador nunca depende do retorno."""
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    chat = os.environ.get("TELEGRAM_CHAT_ID", "")
    if not token or not chat:
        return False
    dados = urllib.parse.urlencode({"chat_id": chat, "text": texto}).encode()
    req = urllib.request.Request(f"https://api.telegram.org/bot{token}/sendMessage", data=dados)
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status == 200
    except Exception:  # noqa: BLE001 — notificação nunca derruba o chamador
        return False


if __name__ == "__main__":  # self-check: sem token = no-op False, não levanta
    os.environ.pop("TELEGRAM_BOT_TOKEN", None)
    assert telegram("teste") is False
    print("notify OK — no-op seguro sem token")
