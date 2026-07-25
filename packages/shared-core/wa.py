"""WhatsApp — checagem de número ANTES de enviar (protege a reputação do chip).

39% dos disparos batendo em número sem WhatsApp queima o número novo. Esta
função pergunta à Evolution quais números REALMENTE têm WhatsApp, pra o enviador
pular os mortos. Interface fixa `tem_whatsapp(numeros) -> {numero: bool}`.

Best-effort: sem Evolution configurada / erro = {} (desconhecido). O enviador
decide a política (recomendado: na dúvida, NÃO enviar pra número não confirmado
quando a checagem está disponível; se a checagem caiu, seguir normal e logar).

Env: EVOLUTION_URL, EVOLUTION_APIKEY, EVOLUTION_INSTANCE (mesma instância do SDR).
urllib stdlib, sem dep nova.
"""
from __future__ import annotations

import json
import os
import re
import urllib.request


def _so_digitos(n: str) -> str:
    return re.sub(r"\D", "", n or "")


def tem_whatsapp(numeros: list[str]) -> dict[str, bool]:
    """{numero_normalizado: True/False} pros que a Evolution confirmou. Números
    sem resposta NÃO entram no dict (desconhecido ≠ morto). {} se não configurado."""
    url = os.environ.get("EVOLUTION_URL", "").rstrip("/")
    inst = os.environ.get("EVOLUTION_INSTANCE", "")
    apikey = os.environ.get("EVOLUTION_APIKEY", "")
    nums = [_so_digitos(n) for n in numeros if _so_digitos(n)]
    if not url or not inst or not nums:
        return {}
    corpo = json.dumps({"numbers": nums}).encode()
    req = urllib.request.Request(
        f"{url}/chat/whatsappNumbers/{inst}", data=corpo, method="POST",
        headers={"Content-Type": "application/json", "apikey": apikey,
                 "User-Agent": "noemi-wa/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            dados = json.loads(r.read().decode())
    except Exception:  # noqa: BLE001 — checagem indisponível ≠ número morto
        return {}
    out: dict[str, bool] = {}
    for item in dados if isinstance(dados, list) else []:
        num = _so_digitos(str(item.get("number") or item.get("jid") or ""))
        if num:
            out[num] = bool(item.get("exists"))
    return out


def filtrar_vivos(numeros: list[str]) -> tuple[list[str], list[str]]:
    """(vivos, mortos) — mortos = confirmados SEM WhatsApp (pular no disparo).
    Números não confirmados (checagem fora) contam como vivos (não bloqueia à toa)."""
    mapa = tem_whatsapp(numeros)
    vivos, mortos = [], []
    for n in numeros:
        d = _so_digitos(n)
        (mortos if mapa.get(d) is False else vivos).append(n)
    return vivos, mortos


if __name__ == "__main__":  # self-check: sem Evolution = {} (não bloqueia à toa)
    for k in ("EVOLUTION_URL", "EVOLUTION_INSTANCE"):
        os.environ.pop(k, None)
    assert tem_whatsapp(["11999998888"]) == {}
    vivos, mortos = filtrar_vivos(["11999998888", "abc"])
    assert vivos == ["11999998888", "abc"] and mortos == [], (vivos, mortos)
    assert _so_digitos("+55 (11) 99999-8888") == "5511999998888"
    print("wa OK — sem Evolution não bloqueia; normaliza número")
