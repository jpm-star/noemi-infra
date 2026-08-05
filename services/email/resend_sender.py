"""Sender Resend — plugado no `outbound.processar_fila(enviar=...)`.

O outbound já tem fila, teto diário e retry; só faltava o transporte. Este módulo é
só o transporte: recebe (to, subject, body) e devolve o message_id.

Dois gotchas que custaram tempo e ficam registrados aqui:
  1. O WAF da Cloudflare na frente do Resend devolve 403 "error code: 1010" pro
     User-Agent padrão do urllib. Tem que mandar UA explícito — curl passa, urllib não.
  2. Sem domínio verificado, o Resend só entrega pro e-mail DONO DA CONTA. Isso não é
     erro de código: é DNS. `dominio_verificado()` diz na cara qual é o caso.
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request

_API = "https://api.resend.com"
_UA = "curl/8.5.0"  # ver gotcha 1


class NaoVerificado(RuntimeError):
    """Domínio não verificado no Resend — é DNS, não código."""


def _req(caminho: str, *, dados: dict | None = None, metodo: str = "GET") -> dict:
    key = os.environ.get("RESEND_API_KEY", "").strip()
    if not key:
        raise RuntimeError("RESEND_API_KEY ausente")
    corpo = json.dumps(dados).encode() if dados is not None else None
    r = urllib.request.Request(f"{_API}{caminho}", data=corpo, method=metodo,
                               headers={"Authorization": f"Bearer {key}",
                                        "Content-Type": "application/json",
                                        "User-Agent": _UA})
    with urllib.request.urlopen(r, timeout=30) as z:
        return json.loads(z.read().decode() or "{}")


def dominio_verificado() -> tuple[bool, str]:
    """(ok, detalhe). Sem domínio verificado o envio em massa NÃO sai — checar antes
    de processar a fila evita marcar 30 e-mails como 'failed' à toa."""
    try:
        d = _req("/domains")
    except Exception as e:  # noqa: BLE001
        return False, f"não deu pra consultar: {str(e)[:80]}"
    ds = d.get("data") or []
    ok = [x for x in ds if str(x.get("status", "")).lower() == "verified"]
    if ok:
        return True, ", ".join(x.get("name", "") for x in ok)
    return False, (f"{len(ds)} domínio(s), nenhum verificado" if ds
                   else "nenhum domínio cadastrado — verifique em resend.com/domains")


def enviar(to: str, subject: str, body: str) -> str:
    """Envia 1 e-mail. Devolve o message_id. Levanta em falha (o outbound marca
    'failed' e não perde o registro)."""
    remetente = os.environ.get("RESEND_FROM", "").strip() or "onboarding@resend.dev"
    try:
        d = _req("/emails", dados={"from": remetente, "to": [to],
                                   "subject": subject, "text": body}, metodo="POST")
    except urllib.error.HTTPError as e:
        txt = ""
        try:
            txt = e.read().decode()[:200]
        except Exception:  # noqa: BLE001
            pass
        if "not verified" in txt.lower() or "only send testing" in txt.lower():
            raise NaoVerificado(txt) from e
        raise RuntimeError(f"HTTP {e.code}: {txt}") from e
    mid = d.get("id") or ""
    if not mid:
        raise RuntimeError(f"resposta sem id: {str(d)[:120]}")
    return mid


if __name__ == "__main__":  # self-check: diz o estado, não envia nada
    ok, detalhe = dominio_verificado()
    print(f"domínio verificado: {ok} — {detalhe}")
    print(f"remetente configurado: {os.environ.get('RESEND_FROM', '(vazio)')}")
    if not ok:
        print("\n⚠️  Envio em massa BLOQUEADO até verificar o domínio (é DNS, não código).")
