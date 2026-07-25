#!/usr/bin/env python3
"""OLHOS — ponte WhatsApp → Radar de Vídeo (autorizada e ESCOPADA pelo JP).

Puxa do Evolution SÓ as mensagens que o JP manda do número "dificil" pra
instância "noemi ajuda papai", A PARTIR DE AGORA (marca um start_ts na 1ª
execução; nada anterior é lido). Extrai links de vídeo, roda o Radar
(transcreve+insight+guarda) e devolve o insight no Telegram. Ignora todo o
resto das conversas — só links, só desse canal.

Escopo (env):
  EVOLUTION_URL, EVOLUTION_APIKEY (global)
  OLHOS_INSTANCE      instância a consultar (default: noemi ajuda papai)
  OLHOS_FROM_NUMBER   número do "dificil" (só mensagens dele contam)

Estado em data/olhos_estado.json (start_ts + urls já processadas). systemd timer.
"""
from __future__ import annotations

import json
import os
import re
import sys
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

_AQUI = Path(__file__).resolve().parent
sys.path.insert(0, str(_AQUI.parents[0] / "apps" / "painel-operacoes"))
sys.path.insert(0, str(_AQUI.parents[0] / "packages"))

_ESTADO = _AQUI.parents[0] / "data" / "olhos_estado.json"
_URL_RE = re.compile(r"https?://[^\s]+")


def _estado() -> dict:
    try:
        return json.loads(_ESTADO.read_text("utf-8"))
    except (OSError, ValueError):
        return {}


def _salvar_estado(e: dict) -> None:
    _ESTADO.parent.mkdir(parents=True, exist_ok=True)
    _ESTADO.write_text(json.dumps(e, ensure_ascii=False), "utf-8")


def _texto_da_msg(m: dict) -> str:
    msg = m.get("message") or {}
    return (msg.get("conversation")
            or (msg.get("extendedTextMessage") or {}).get("text")
            or "")


def _num(jid: str) -> str:
    return re.sub(r"\D", "", (jid or "").split("@")[0])


def links_novos(msgs: list[dict], from_number: str, desde_ts: float,
                ja_vistas: set[str]) -> list[tuple[str, float]]:
    """(url, ts) dos links inéditos que o JP mandou depois de desde_ts. PURA."""
    fromn = re.sub(r"\D", "", from_number or "")
    out: list[tuple[str, float]] = []
    for m in msgs:
        ts = float(m.get("messageTimestamp") or 0)
        if ts <= desde_ts:
            continue
        k = m.get("key") or {}
        # do JP: fromMe (ele mandou da papai) OU remetente = número do dificil
        dele = k.get("fromMe") or (fromn and _num(k.get("remoteJid") or k.get("participant") or "") == fromn)
        if not dele:
            continue
        for url in _URL_RE.findall(_texto_da_msg(m)):
            url = url.rstrip(").,")
            if url not in ja_vistas:
                out.append((url, ts))
    return out


def _buscar_msgs(instancia: str, limite: int = 30) -> list[dict]:
    """Últimas mensagens da instância via Evolution. [] se indisponível."""
    url = os.environ.get("EVOLUTION_URL", "").rstrip("/")
    key = os.environ.get("EVOLUTION_APIKEY", "")
    if not url or not key:
        return []
    corpo = json.dumps({"where": {}, "limit": limite}).encode()
    req = urllib.request.Request(
        f"{url}/chat/findMessages/{urllib.parse.quote(instancia)}", data=corpo, method="POST",
        headers={"Content-Type": "application/json", "apikey": key, "User-Agent": "noemi-olhos/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            d = json.loads(r.read().decode())
    except Exception:  # noqa: BLE001
        return []
    m = d.get("messages")
    return (m.get("records") if isinstance(m, dict) else m) or []


def rodar(*, buscar=None, analisar=None, notificar=None) -> dict:
    """Processa os links novos do canal dificil→papai. Deps injetáveis (teste)."""
    inst = os.environ.get("OLHOS_INSTANCE", "noemi ajuda papai")
    fromn = os.environ.get("OLHOS_FROM_NUMBER", "")
    est = _estado()
    agora = datetime.now(timezone.utc).timestamp()
    desde = est.get("start_ts")
    if desde is None:  # 1ª execução: marca o "a partir de agora", não lê o passado
        _salvar_estado({"start_ts": agora, "urls": []})
        return {"iniciado": True, "desde": agora, "processados": 0}
    vistas = set(est.get("urls", []))
    msgs = (buscar or _buscar_msgs)(inst)
    novos = links_novos(msgs, fromn, desde, vistas)
    feitos = []
    for url, ts in novos:
        try:
            a = (analisar or _analisar_real)(url)
            vistas.add(url)
            feitos.append({"url": url, "insight": (a or {}).get("insight", "")[:400]})
            (notificar or _notificar_real)(
                f"👁️ RADAR — {(a or {}).get('categoria','?')} (★{(a or {}).get('score','?')})\n"
                f"{(a or {}).get('insight','')[:500]}\n{url}")
        except Exception as e:  # noqa: BLE001 — um link falho não trava os outros
            feitos.append({"url": url, "erro": str(e)[:120]})
    est["urls"] = list(vistas)[-500:]
    _salvar_estado(est)
    return {"processados": len([f for f in feitos if "insight" in f]), "detalhe": feitos}


def _analisar_real(url: str):
    import radar
    return radar.analisar(url, origem="whatsapp:dificil")


def _notificar_real(texto: str) -> bool:
    from shared_core import notify
    return notify.telegram(texto)


if __name__ == "__main__":
    if "--selftest" in sys.argv:  # extração/dedup/escopo (sem rede)
        msgs = [
            {"messageTimestamp": 100, "key": {"fromMe": True},
             "message": {"conversation": "olha essa dica https://youtu.be/abc top"}},
            {"messageTimestamp": 90, "key": {"fromMe": True},  # antes do corte
             "message": {"conversation": "https://youtu.be/velho"}},
            {"messageTimestamp": 110, "key": {"fromMe": False, "remoteJid": "5599@s.whatsapp.net"},
             "message": {"conversation": "de outro contato https://spam.com"}},  # não é o JP
        ]
        novos = links_novos(msgs, from_number="", desde_ts=95, ja_vistas={"https://youtu.be/ja"})
        assert novos == [("https://youtu.be/abc", 100.0)], novos
        # 1ª execução marca start_ts e não processa passado
        import tempfile
        _ESTADO = Path(tempfile.mktemp())
        globals()["_ESTADO"] = _ESTADO
        r = rodar(buscar=lambda i: msgs, analisar=lambda u: {"insight": "x", "categoria": "marketing", "score": 4},
                  notificar=lambda t: True)
        assert r.get("iniciado"), r
        # 2ª execução processa o link novo do JP
        r2 = rodar(buscar=lambda i: msgs, analisar=lambda u: {"insight": "ok", "categoria": "marketing", "score": 5},
                   notificar=lambda t: True)
        # start_ts=agora > ts das msgs (100/110) → nada novo; força desde antigo:
        _salvar_estado({"start_ts": 95, "urls": []})
        r3 = rodar(buscar=lambda i: msgs, analisar=lambda u: {"insight": "ok", "categoria": "marketing", "score": 5},
                   notificar=lambda t: True)
        assert r3["processados"] == 1, r3
        print("olhos OK — extrai link do JP, respeita 'a partir de agora', dedup, ignora terceiros")
    else:
        print(json.dumps(rodar(), ensure_ascii=False))
