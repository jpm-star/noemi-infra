#!/usr/bin/env python3
"""Descobre o TELEGRAM_CHAT_ID e grava no .env — rode DEPOIS de mandar qualquer
mensagem pro @noemi_alert_bot (senão o getUpdates vem vazio).

  /root/noemi-infra/.venv/bin/python deploy/telegram_chat_id.py            # descobre + grava
  /root/noemi-infra/.venv/bin/python deploy/telegram_chat_id.py --testar   # manda alerta-teste

Lê TELEGRAM_BOT_TOKEN do ambiente/.env. Best-effort, idempotente.
"""
from __future__ import annotations

import json
import os
import re
import sys
import urllib.request
from pathlib import Path

_ENV = Path("/root/noemi-infra/.env")


def _token() -> str:
    tok = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    if not tok and _ENV.exists():  # lê do .env se não estiver no ambiente
        m = re.search(r"^TELEGRAM_BOT_TOKEN=(.+)$", _ENV.read_text(), re.M)
        tok = m.group(1).strip() if m else ""
    return tok


def _chat_id(token: str) -> str | None:
    req = urllib.request.Request(f"https://api.telegram.org/bot{token}/getUpdates")
    with urllib.request.urlopen(req, timeout=10) as r:
        d = json.loads(r.read().decode())
    for upd in reversed(d.get("result", [])):  # o mais recente primeiro
        msg = upd.get("message") or upd.get("channel_post") or {}
        chat = msg.get("chat") or {}
        if chat.get("id") is not None:
            return str(chat["id"])
    return None


def _gravar(chat: str) -> None:
    txt = _ENV.read_text() if _ENV.exists() else ""
    if re.search(r"^TELEGRAM_CHAT_ID=", txt, re.M):
        txt = re.sub(r"^TELEGRAM_CHAT_ID=.*$", f"TELEGRAM_CHAT_ID={chat}", txt, flags=re.M)
    else:
        txt += f"\nTELEGRAM_CHAT_ID={chat}\n"
    _ENV.write_text(txt)
    _ENV.chmod(0o600)


if __name__ == "__main__":
    tok = _token()
    if not tok:
        sys.exit("TELEGRAM_BOT_TOKEN não encontrado (ambiente nem .env)")
    if "--testar" in sys.argv:
        os.environ["TELEGRAM_BOT_TOKEN"] = tok
        sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "packages"))
        from shared_core import notify
        print("alerta-teste enviado:", notify.telegram("✅ Noemi OS conectada — alertas ligados."))
        sys.exit(0)
    chat = _chat_id(tok)
    if not chat:
        sys.exit("getUpdates vazio — mande QUALQUER mensagem pro @noemi_alert_bot e rode de novo.")
    _gravar(chat)
    print(f"TELEGRAM_CHAT_ID={chat} gravado no .env. Rode --testar pra confirmar.")
