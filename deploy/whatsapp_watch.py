#!/usr/bin/env python3
"""Watcher de reconexão do WhatsApp — se uma instância cai ('close'), tenta
reconectar (Evolution /instance/connect) e avisa o JP no Telegram. Só alerta na
TRANSIÇÃO (não spama). Timer systemd. Reusa notify.

Env: EVOLUTION_URL, EVOLUTION_APIKEY (global), WA_INSTANCIAS (csv, default as 2
importantes), TELEGRAM_* (pro alerta).
"""
from __future__ import annotations

import json
import os
import sys
import urllib.request
from pathlib import Path

_AQUI = Path(__file__).resolve().parent
sys.path.insert(0, str(_AQUI.parents[0] / "packages"))
_ESTADO = _AQUI.parents[0] / "data" / "wa_watch.json"
_INSTANCIAS = os.environ.get("WA_INSTANCIAS", "noemi ajuda papai,dificil")


def _api(metodo: str, inst: str, post: bool = False) -> dict:
    url = os.environ.get("EVOLUTION_URL", "").rstrip("/")
    key = os.environ.get("EVOLUTION_APIKEY", "")
    if not url or not key:
        return {}
    import urllib.parse
    req = urllib.request.Request(f"{url}/{metodo}/{urllib.parse.quote(inst)}",
                                 headers={"apikey": key, "User-Agent": "noemi-wa-watch/1.0"},
                                 method="POST" if post else "GET")
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return json.loads(r.read().decode())
    except Exception:  # noqa: BLE001
        return {}


def _estado_instancia(inst: str) -> str | None:
    d = _api("instance/connectionState", inst)
    return (d.get("instance") or {}).get("state") or d.get("state")


def rodar(*, estado_fn=None, reconecta_fn=None, avisa_fn=None) -> dict:
    estado_fn = estado_fn or _estado_instancia
    reconecta_fn = reconecta_fn or (lambda i: _api("instance/connect", i))
    if avisa_fn is None:
        from shared_core import notify
        avisa_fn = notify.telegram
    try:
        antes = json.loads(_ESTADO.read_text())
    except (OSError, ValueError):
        antes = {}
    agora, acoes = {}, []
    for inst in [i.strip() for i in _INSTANCIAS.split(",") if i.strip()]:
        st = estado_fn(inst)
        agora[inst] = st or "?"
        caiu = st is not None and st != "open"
        # só age na TRANSIÇÃO open→close (não a cada tick)
        if caiu and antes.get(inst) == "open":
            reconecta_fn(inst)  # dispara reconexão (pode gerar QR novo)
            avisa_fn(f"🔴 WhatsApp *{inst}* caiu ({st}) — tentei reconectar. "
                     f"Se pedir QR, escaneia em {os.environ.get('EVOLUTION_URL','a Evolution')}.")
            acoes.append(f"reconectando {inst}")
        elif st == "open" and antes.get(inst) not in (None, "open"):
            avisa_fn(f"🟢 WhatsApp *{inst}* reconectou.")
            acoes.append(f"voltou {inst}")
    _ESTADO.parent.mkdir(parents=True, exist_ok=True)
    _ESTADO.write_text(json.dumps(agora, ensure_ascii=False))
    return {"estados": agora, "acoes": acoes}


if __name__ == "__main__":
    if "--selftest" in sys.argv:  # transição open→close dispara reconexão+aviso (sem rede)
        import tempfile
        _ESTADO = Path(tempfile.mktemp()); globals()["_ESTADO"] = _ESTADO
        _ESTADO.write_text(json.dumps({"dificil": "open"}))
        globals()["_INSTANCIAS"] = "dificil"
        recon, avisos = [], []
        r = rodar(estado_fn=lambda i: "close", reconecta_fn=lambda i: recon.append(i),
                  avisa_fn=lambda t: avisos.append(t))
        assert recon == ["dificil"] and any("caiu" in a for a in avisos), (recon, avisos)
        # 2a rodada: segue close, NÃO re-alerta (não é mais transição)
        recon.clear(); avisos.clear()
        rodar(estado_fn=lambda i: "close", reconecta_fn=lambda i: recon.append(i), avisa_fn=lambda t: avisos.append(t))
        assert recon == [] and avisos == [], "não pode re-spammar"
        print("whatsapp_watch OK — reconecta+avisa na queda, não re-spamma")
    else:
        print(json.dumps(rodar(), ensure_ascii=False))
