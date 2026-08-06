#!/usr/bin/env python3
"""Watchdog das instâncias WhatsApp/Evolution (RISCO #3 do JPOS_MASTER).

O problema: instâncias caem pra close/connecting sozinhas => a Noemi fica MUDA (o
produto que o JP vende para de responder cliente) e ninguém descobre até alguém
reclamar. O monitor-canais.sh já DETECTA (read-only); este aqui RECONECTA.

Desenho (validação isolada exigida pós-incidente): a decisão fica numa função PURA
`avaliar()` — recebe (instâncias, estado, agora) e devolve o que reiniciar/alertar,
sem I/O. O runner faz o I/O em volta (fetch/restart/alerta/persist). Assim o cérebro
é 100% testável sem tocar na Evolution viva (rode: python evolution_watchdog.py --selftest).

Segurança:
  - backoff: no máx 1 restart por instância a cada COOLDOWN_S; até MAX_TENTATIVAS.
  - grace de `connecting`: reconexão em andamento é NORMAL — só age se travar > GRACE_S.
  - escalonamento: depois de MAX_TENTATIVAS sem voltar, PARA de reiniciar e alerta
    UMA vez "precisa QR humano" (sessão perdida não volta com restart).
  - kill-switch: WATCHDOG_RECONNECT=false => só monitora+alerta (não escreve nada).
  - alerta fora de banda: Telegram (se o WhatsApp caiu, não dá pra avisar por WhatsApp).

systemd timer (a cada ~2min). Reusa shared_core.notify. urllib stdlib, sem dep nova.
"""
from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

_AQUI = Path(__file__).resolve().parent
sys.path.insert(0, str(_AQUI.parents[0] / "packages"))

_ESTADO = _AQUI.parents[0] / "data" / "evolution_watchdog.json"
COOLDOWN_S = int(os.environ.get("WATCHDOG_COOLDOWN_S", "180"))   # entre tentativas
MAX_TENTATIVAS = int(os.environ.get("WATCHDOG_MAX_TENTATIVAS", "3"))
GRACE_S = int(os.environ.get("WATCHDOG_GRACE_S", "300"))          # connecting tolerado


def _nome_estado(it: dict) -> tuple[str, str]:
    """Extrai (nome, estado) de um item do fetchInstances (formato varia por versão)."""
    inst = it.get("instance", it)
    nome = inst.get("instanceName") or inst.get("name") or "?"
    est = inst.get("state") or inst.get("connectionStatus") or inst.get("status") or "?"
    return nome, est


def avaliar(instancias: list[dict], estado: dict, agora: float, *,
            cooldown_s: int = COOLDOWN_S, max_tentativas: int = MAX_TENTATIVAS,
            grace_s: int = GRACE_S) -> dict:
    """PURA (sem I/O): decide o que reiniciar e alertar. Devolve
    {reiniciar:[nomes], alertas:[msgs], estado:novo_estado}. Testável com agora fake."""
    novo = {k: dict(v) for k, v in estado.items()}
    reiniciar: list[str] = []
    alertas: list[str] = []
    vivos: set[str] = set()
    for it in instancias:
        nome, est = _nome_estado(it)
        vivos.add(nome)
        st = novo.get(nome, {})
        if est == "open":
            if st.get("down_since"):  # estava fora e voltou
                alertas.append(f"✅ {nome} reconectou (estava {st.get('ultimo_estado','?')}).")
            novo[nome] = {}  # zera contadores
            continue
        # não-open: down (close/erro) ou connecting
        st = dict(st)
        st["ultimo_estado"] = est
        st.setdefault("down_since", agora)
        # connecting dentro do grace = reconexão normal em andamento: espera.
        if est == "connecting" and (agora - st["down_since"]) < grace_s:
            novo[nome] = st
            continue
        tent = st.get("tentativas", 0)
        if tent >= max_tentativas:
            if not st.get("escalado"):  # alerta de escalonamento só UMA vez
                alertas.append(f"🔴 {nome} segue fora ({est}) após {tent} tentativas — "
                               f"reconectar no painel da Evolution (provável QR/sessão perdida).")
                st["escalado"] = True
            novo[nome] = st
            continue
        if agora - st.get("ultima_acao", 0) >= cooldown_s:  # respeita o backoff
            reiniciar.append(nome)
            st["tentativas"] = tent + 1
            st["ultima_acao"] = agora
            alertas.append(f"♻️ {nome} está {est} — reconectando "
                           f"(tentativa {tent + 1}/{max_tentativas}).")
        novo[nome] = st
    for nome in list(novo):  # some da lista => esquece o estado
        if nome not in vivos:
            del novo[nome]
    return {"reiniciar": reiniciar, "alertas": alertas, "estado": novo}


# ---------- I/O (só o runner usa; a lógica acima é pura) ----------
def _url() -> str:
    return os.environ.get("EVOLUTION_URL", "http://127.0.0.1:8080").rstrip("/")


def _apikey() -> str:
    return os.environ.get("EVOLUTION_APIKEY", "")


def _fetch_http() -> list[dict]:
    req = urllib.request.Request(f"{_url()}/instance/fetchInstances", headers={"apikey": _apikey()})
    with urllib.request.urlopen(req, timeout=15) as r:
        d = json.load(r)
    return d if isinstance(d, list) else d.get("instances", [])


def _restart_http(nome: str) -> None:
    # /instance/restart reestabelece a sessão existente (não pede QR se a sessão vive).
    # quote(): nomes de instância têm espaço ("noemi ajuda papai", e uma com espaço no
    # FIM). urllib não escapa a URL sozinho — sem isto o restart vira 404/400.
    req = urllib.request.Request(f"{_url()}/instance/restart/{urllib.parse.quote(nome)}", method="POST",
                                 headers={"apikey": _apikey()})
    with urllib.request.urlopen(req, timeout=20) as r:
        r.read()


def _alertar_telegram(msg: str) -> None:
    try:
        from shared_core import notify
        notify.telegram(f"[watchdog Evolution] {msg}")
    except Exception:  # noqa: BLE001 — alerta é best-effort, nunca derruba o watchdog
        pass


def _ler_estado() -> dict:
    try:
        return json.loads(_ESTADO.read_text())
    except (OSError, ValueError):
        return {}


def _grava_estado(estado: dict) -> None:
    try:
        _ESTADO.parent.mkdir(parents=True, exist_ok=True)
        _ESTADO.write_text(json.dumps(estado))
    except OSError:
        pass


def rodar(*, _fetch=None, _restart=None, _alertar=None, _agora=None) -> dict:
    fetch = _fetch or _fetch_http
    restart = _restart or _restart_http
    alertar = _alertar or _alertar_telegram
    agora = _agora if _agora is not None else time.time()
    if not _apikey() and _fetch is None:
        return {"erro": "EVOLUTION_APIKEY não configurada"}
    estado = _ler_estado()
    try:
        instancias = fetch()
    except (urllib.error.URLError, TimeoutError, ValueError, OSError) as e:
        alertar(f"⚠️ Evolution inalcançável: {e}")
        return {"erro": str(e)}
    r = avaliar(instancias, estado, agora)
    reconnect_on = os.environ.get("WATCHDOG_RECONNECT", "true").lower() == "true"
    for nome in r["reiniciar"]:
        if reconnect_on:
            try:
                restart(nome)
            except Exception as e:  # noqa: BLE001
                r["alertas"].append(f"✗ falha ao reiniciar {nome}: {str(e)[:120]}")
        else:
            r["alertas"].append(f"(reconnect desligado — {nome} precisa de ação manual)")
    for msg in r["alertas"]:
        alertar(msg)
    _grava_estado(r["estado"])
    return {"reiniciar": r["reiniciar"], "alertados": len(r["alertas"])}


if __name__ == "__main__":
    if "--selftest" in sys.argv:  # VALIDAÇÃO ISOLADA (zero rede) — exigência do JP
        AG = 1_000_000.0  # "agora" fixo (Date.now real é irrelevante aqui)

        # 1) close visto pela 1ª vez => reinicia já (tentativa 1) + alerta
        r = avaliar([{"instance": {"instanceName": "mari", "state": "close"}}], {}, AG)
        assert r["reiniciar"] == ["mari"], r
        assert r["estado"]["mari"]["tentativas"] == 1 and any("reconectando" in a for a in r["alertas"]), r

        # 2) mesmo close DENTRO do cooldown => NÃO reinicia (backoff)
        r2 = avaliar([{"instance": {"instanceName": "mari", "state": "close"}}], r["estado"], AG + 60)
        assert r2["reiniciar"] == [], r2

        # 3) mesmo close APÓS cooldown => reinicia de novo (tentativa 2)
        r3 = avaliar([{"instance": {"instanceName": "mari", "state": "close"}}], r["estado"], AG + 200)
        assert r3["reiniciar"] == ["mari"] and r3["estado"]["mari"]["tentativas"] == 2, r3

        # 4) atingiu MAX_TENTATIVAS => para de reiniciar e ESCALA uma vez (QR humano)
        st = {"mari": {"tentativas": 3, "down_since": AG, "ultima_acao": AG, "ultimo_estado": "close"}}
        r4 = avaliar([{"instance": {"instanceName": "mari", "state": "close"}}], st, AG + 999)
        assert r4["reiniciar"] == [] and any("QR" in a for a in r4["alertas"]), r4
        assert r4["estado"]["mari"]["escalado"] is True
        # não re-escala na próxima
        r4b = avaliar([{"instance": {"instanceName": "mari", "state": "close"}}], r4["estado"], AG + 2000)
        assert r4b["alertas"] == [], r4b

        # 5) voltou pra open => alerta de recuperação + zera
        r5 = avaliar([{"instance": {"instanceName": "mari", "state": "open"}}], r4["estado"], AG + 3000)
        assert any("reconectou" in a for a in r5["alertas"]) and r5["estado"]["mari"] == {}, r5

        # 6) connecting dentro do grace => espera (não reinicia)
        r6 = avaliar([{"instance": {"instanceName": "x", "state": "connecting"}}], {}, AG)
        assert r6["reiniciar"] == [] and r6["alertas"] == [], r6
        # connecting TRAVADO além do grace => trata como down e reinicia
        st6 = {"x": {"down_since": AG, "ultimo_estado": "connecting"}}
        r6b = avaliar([{"instance": {"instanceName": "x", "state": "connecting"}}], st6, AG + GRACE_S + 1)
        assert r6b["reiniciar"] == ["x"], r6b

        # 7) open desde sempre => nada
        r7 = avaliar([{"instance": {"instanceName": "ok", "state": "open"}}], {}, AG)
        assert r7 == {"reiniciar": [], "alertas": [], "estado": {"ok": {}}}, r7

        # 8) runner com I/O mockado: um close reinicia e persiste (sem rede real)
        chamadas = {"restart": [], "alertas": []}
        out = rodar(_fetch=lambda: [{"instance": {"instanceName": "mari", "state": "close"}}],
                    _restart=lambda n: chamadas["restart"].append(n),
                    _alertar=lambda m: chamadas["alertas"].append(m), _agora=AG + 10_000)
        assert chamadas["restart"] == ["mari"], chamadas
        print("evolution_watchdog OK — backoff, grace, escalonamento, recuperação e runner (isolado, zero rede)")
    else:
        print(json.dumps(rodar(), ensure_ascii=False))
