#!/usr/bin/env python3
"""Alerta de cota em 80% — avisa ANTES de estourar, não depois.

Por que 80% e não 100%: em 100% o alerta é autópsia. O incidente de 2026-08-04
(45 análises do Radar com "score 0") só apareceu quando já tinha acontecido —
ninguém estava olhando o painel na hora. Alerta chega em quem decide; dashboard
espera ser olhado.

Mede o que a API REALMENTE informa, não estimativa:
  - Groq: headers x-ratelimit-remaining-tokens / -requests por modelo.
  - CNPJá: consulta barata; o 429 devolve {"remaining": N}.
Um alerta por chave/dia (estado em disco) — alerta repetido vira ruído e some.

Uso:  python alerta_cota.py            # checa e alerta se <20% restante
      python alerta_cota.py --ver      # só mostra, não notifica
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from datetime import date
from pathlib import Path

_ESTADO = Path(os.environ.get("ALERTA_COTA_ESTADO",
                              "/root/noemi-infra/data/alerta_cota.json"))
LIMIAR = float(os.environ.get("ALERTA_COTA_LIMIAR", "0.20"))  # alerta com <20% sobrando
UA = "curl/8.5.0"  # o WAF da Groq bloqueia o UA padrão do urllib (403/1010)


def _groq(nome: str, key: str, modelo: str) -> dict | None:
    """Consumo REAL da chave via headers de rate-limit. None se não deu pra medir."""
    if not key:
        return None
    corpo = json.dumps({"model": modelo, "max_tokens": 1,
                        "messages": [{"role": "user", "content": "."}]}).encode()
    req = urllib.request.Request("https://api.groq.com/openai/v1/chat/completions",
                                 data=corpo, headers={"Authorization": f"Bearer {key}",
                                                      "Content-Type": "application/json",
                                                      "User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=25) as r:
            h = dict(r.headers)
    except urllib.error.HTTPError as e:
        h = dict(e.headers)
        if e.code == 429:  # já estourou: 0% restante, é o caso mais urgente
            return {"nome": nome, "modelo": modelo, "restante_pct": 0.0, "detalhe": "429 (estourado)"}
    except Exception:  # noqa: BLE001
        return None
    def _n(k):
        v = h.get(k, "")
        try:
            return float(str(v).rstrip("s"))
        except ValueError:
            return None
    rt, lt = _n("x-ratelimit-remaining-tokens"), _n("x-ratelimit-limit-tokens")
    rr, lr = _n("x-ratelimit-remaining-requests"), _n("x-ratelimit-limit-requests")
    pcts = [r / l for r, l in ((rt, lt), (rr, lr)) if r is not None and l]
    if not pcts:
        return None
    return {"nome": nome, "modelo": modelo, "restante_pct": min(pcts),
            "detalhe": f"tokens {rt:.0f}/{lt:.0f}" if rt is not None else f"req {rr:.0f}/{lr:.0f}"}


def _cnpja(key: str) -> dict | None:
    if not key:
        return None
    req = urllib.request.Request("https://api.cnpja.com/office/33000167000101",
                                 headers={"Authorization": key, "User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=25):
            return {"nome": "CNPJá", "modelo": "office", "restante_pct": 1.0, "detalhe": "ok"}
    except urllib.error.HTTPError as e:
        if e.code == 429:
            try:
                d = json.loads(e.read().decode() or "{}")
            except Exception:  # noqa: BLE001
                d = {}
            return {"nome": "CNPJá", "modelo": "office", "restante_pct": 0.0,
                    "detalhe": f"sem crédito (remaining={d.get('remaining', 0)})"}
    except Exception:  # noqa: BLE001
        return None
    return None


def coletar() -> list[dict]:
    fora = []
    for var, modelo in (("GROQ_API_KEY", "llama-3.3-70b-versatile"),
                        ("GROQ_API_KEY", "openai/gpt-oss-120b"),
                        ("GROQ_API_KEY_RESERVA", "llama-3.3-70b-versatile")):
        r = _groq(var, os.environ.get(var, "").strip(), modelo)
        if r:
            fora.append(r)
    c = _cnpja(os.environ.get("CNPJA_API_KEY", "").strip())
    if c:
        fora.append(c)
    return fora


def _ja_alertou(chave: str) -> bool:
    """1 alerta por chave/dia — repetir vira ruído e o JP para de ler."""
    try:
        d = json.loads(_ESTADO.read_text())
    except (OSError, ValueError):
        d = {}
    return d.get(chave) == date.today().isoformat()


def _marcar(chave: str) -> None:
    try:
        d = json.loads(_ESTADO.read_text())
    except (OSError, ValueError):
        d = {}
    d[chave] = date.today().isoformat()
    _ESTADO.parent.mkdir(parents=True, exist_ok=True)
    _ESTADO.write_text(json.dumps(d))


def _notificar(txt: str) -> bool:
    """Telegram (mesmo canal do watchdog). Sem token => só loga."""
    tok = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    chat = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
    if not (tok and chat):
        print(txt)
        return False
    try:
        import urllib.parse
        u = (f"https://api.telegram.org/bot{tok}/sendMessage?"
             + urllib.parse.urlencode({"chat_id": chat, "text": txt}))
        urllib.request.urlopen(u, timeout=20)
        return True
    except Exception:  # noqa: BLE001
        print(txt)
        return False


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ver", action="store_true")
    a = ap.parse_args()
    leituras = coletar()
    if not leituras:
        print("nenhuma chave mensurável (sem key no ambiente?)")
        return
    criticos = []
    for x in leituras:
        pct = x["restante_pct"]
        marca = "🔴" if pct <= 0.05 else ("🟡" if pct < LIMIAR else "🟢")
        print(f"  {marca} {x['nome']:22s} {x['modelo']:26s} "
              f"{pct*100:5.1f}% restante · {x['detalhe']}")
        if pct < LIMIAR:
            criticos.append(x)
    if a.ver or not criticos:
        return
    for x in criticos:
        chave = f"{x['nome']}|{x['modelo']}"
        if _ja_alertou(chave):
            continue
        pct = x["restante_pct"] * 100
        _notificar(f"⚠️ COTA BAIXA — {x['nome']} / {x['modelo']}\n"
                   f"{pct:.0f}% restante ({x['detalhe']}).\n\n"
                   f"Isso derruba análise do Radar e copy de site ANTES de você notar. "
                   f"Trocar a chave dessa função ou esperar o reset.")
        _marcar(chave)


if __name__ == "__main__":
    sys.exit(main())
