#!/usr/bin/env python3
"""Alerta de saúde out-of-band (Telegram) — pra saber NA HORA se um serviço cai
no meio da prospecção (ex.: WhatsApp/Evolution desconectou).

Roda por timer/cron. Reusa agg.motores() (mesmo sinal do painel) + checa o
estado da instância Evolution se configurada. Dispara Telegram SÓ nas transições
(up→down e recuperação), lendo/gravando o estado anterior em data/alerta_estado.json
— não spama a cada minuto. Sem token configurado = no-op seguro (exit 0).

Env:
  TELEGRAM_BOT_TOKEN   token do bot (@BotFather)     [obrigatório p/ enviar]
  TELEGRAM_CHAT_ID     chat/grupo destino            [obrigatório p/ enviar]
  EVOLUTION_URL        base da Evolution API         [opcional — checa WhatsApp]
  EVOLUTION_APIKEY     apikey da Evolution           [opcional]
  EVOLUTION_INSTANCE   nome da instância             [opcional]

Cron:  * * * * * /root/noemi-infra/.venv/bin/python /root/noemi-infra/deploy/alerta_saude.py
"""
from __future__ import annotations

import json
import os
import sys
import urllib.request
from pathlib import Path

_AQUI = Path(__file__).resolve().parent
sys.path.insert(0, str(_AQUI.parents[0] / "apps" / "painel-operacoes"))
sys.path.insert(0, str(_AQUI.parents[0] / "packages"))

_ESTADO = _AQUI.parents[0] / "data" / "alerta_estado.json"


def _servicos_fora() -> list[str]:
    """Nomes dos serviços fora do ar (motores do painel + Evolution/WhatsApp)."""
    fora: list[str] = []
    try:
        import agg
        fora += [m["nome"] for m in agg.motores() if m.get("status") != "up"]
    except Exception as e:  # noqa: BLE001 — alerta nunca morre por erro de import
        fora.append(f"painel(agg) erro: {e}")
    est = _evolution_estado()
    if est is not None and est != "open":
        fora.append(f"WhatsApp/Evolution ({est})")
    return fora


def _evolution_estado() -> str | None:
    """Estado da instância Evolution ('open' = conectado). None se não configurada
    ou inacessível (não vira alerta — só sinaliza quando REALMENTE != open)."""
    url = os.environ.get("EVOLUTION_URL", "").rstrip("/")
    inst = os.environ.get("EVOLUTION_INSTANCE", "")
    if not url or not inst:
        return None
    req = urllib.request.Request(
        f"{url}/instance/connectionState/{inst}",
        headers={"apikey": os.environ.get("EVOLUTION_APIKEY", ""), "User-Agent": "noemi-alerta/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            d = json.loads(r.read().decode("utf-8"))
        # formato Evolution: {"instance":{"state":"open"}}
        return (d.get("instance") or {}).get("state") or d.get("state")
    except Exception:  # noqa: BLE001 — inacessível ≠ desconectado; não alerta
        return None


def _mudancas(anterior: set[str], atual: set[str]) -> tuple[list[str], list[str]]:
    """(novos_problemas, recuperados) entre a leitura anterior e a atual."""
    return sorted(atual - anterior), sorted(anterior - atual)


def _telegram(texto: str) -> bool:
    from shared_core import notify  # notificador compartilhado (painel usa o mesmo)
    ok = notify.telegram(texto)
    if not ok:
        print("[alerta] Telegram não enviado (sem token/chat ou falha):", texto)
    return ok


def rodar() -> int:
    atual = set(_servicos_fora())
    try:
        anterior = set(json.loads(_ESTADO.read_text("utf-8")).get("fora", []))
    except (OSError, ValueError):
        anterior = set()
    novos, recuperados = _mudancas(anterior, atual)
    if novos:
        _telegram("🔴 NOEMI OS — caiu: " + ", ".join(novos)
                  + ("\nAinda fora: " + ", ".join(sorted(atual - set(novos))) if atual - set(novos) else ""))
    if recuperados:
        _telegram("🟢 NOEMI OS — voltou: " + ", ".join(recuperados)
                  + ("\nAinda fora: " + ", ".join(sorted(atual)) if atual else " — tudo no ar."))
    _ESTADO.parent.mkdir(parents=True, exist_ok=True)
    _ESTADO.write_text(json.dumps({"fora": sorted(atual)}, ensure_ascii=False), "utf-8")
    print(f"[alerta] fora={sorted(atual) or 'nenhum'} novos={novos} recuperados={recuperados}")
    return 0


if __name__ == "__main__":
    if "--selftest" in sys.argv:  # lógica de transição (sem rede)
        assert _mudancas(set(), {"WhatsApp"}) == (["WhatsApp"], [])
        assert _mudancas({"WhatsApp"}, set()) == ([], ["WhatsApp"])
        assert _mudancas({"A"}, {"A", "B"}) == (["B"], [])  # só o novo, sem re-alertar A
        print("alerta_saude OK — transições: novo alerta, recuperação, sem re-spam")
    else:
        sys.exit(rodar())
