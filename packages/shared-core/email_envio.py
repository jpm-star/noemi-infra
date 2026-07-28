"""Envio de e-mail — abstração simples, provider trocável por baixo (CLAUDE.md:
interface fixa, provider embaixo). Interface: enviar(assunto, corpo, para).

Provider via env EMAIL_PROVIDER (default 'smtp'). Hoje: SMTP (smtplib stdlib — casa
com App Password do Gmail ou qualquer SMTP). Amanhã: sendgrid/mailgun/resend entram
como mais uma função no dispatch, sem tocar quem chama.

INERTE sem credencial: `configurado()` = False e `enviar()` devolve (False, motivo) —
nunca crasha, nunca finge sucesso. Fica pronto esperando o JP colar a credencial no env.

Env (SMTP): SMTP_HOST, SMTP_PORT (587), SMTP_USER, SMTP_PASS, SMTP_FROM (default=USER),
EMAIL_ALERTA_PARA (destinatário default dos alertas).
"""
from __future__ import annotations

import json
import os
import smtplib
import urllib.error
import urllib.request
from email.message import EmailMessage


def _cfg_smtp() -> dict | None:
    """Config SMTP do env, ou None se faltar o essencial (host/user/pass)."""
    host = os.environ.get("SMTP_HOST", "").strip()
    user = os.environ.get("SMTP_USER", "").strip()
    pw = os.environ.get("SMTP_PASS", "").strip()
    if not (host and user and pw):
        return None
    return {"host": host, "port": int(os.environ.get("SMTP_PORT", "587")),
            "user": user, "pw": pw, "from": os.environ.get("SMTP_FROM", user).strip()}


def _enviar_smtp(assunto: str, corpo: str, para: str) -> tuple[bool, str]:
    cfg = _cfg_smtp()
    if not cfg:
        return False, "sem credencial SMTP (SMTP_HOST/USER/PASS vazios)"
    msg = EmailMessage()
    msg["Subject"] = assunto
    msg["From"] = cfg["from"]
    msg["To"] = para
    msg.set_content(corpo)
    try:
        with smtplib.SMTP(cfg["host"], cfg["port"], timeout=20) as s:
            s.starttls()
            s.login(cfg["user"], cfg["pw"])
            s.send_message(msg)
        return True, "enviado"
    except Exception as e:  # noqa: BLE001 — envio best-effort, nunca derruba o chamador
        return False, f"falha SMTP: {str(e)[:120]}"


def _cfg_resend() -> dict | None:
    """Config Resend do env, ou None se faltar key/remetente. RESEND_FROM tem que ser
    de um domínio VERIFICADO no Resend (ex: alertas@jpos.com.br)."""
    key = os.environ.get("RESEND_API_KEY", "").strip()
    remetente = os.environ.get("RESEND_FROM", os.environ.get("SMTP_FROM", "")).strip()
    if not (key and remetente):
        return None
    return {"key": key, "from": remetente}


def _enviar_resend(assunto: str, corpo: str, para: str) -> tuple[bool, str]:
    """POST simples pra API do Resend (from/to/subject/text). Provider trocável — a
    lógica de alerta/variantes não muda, só esta função."""
    cfg = _cfg_resend()
    if not cfg:
        return False, "sem credencial Resend (RESEND_API_KEY/RESEND_FROM vazios)"
    body = json.dumps({"from": cfg["from"], "to": [para], "subject": assunto,
                       "text": corpo}).encode("utf-8")
    req = urllib.request.Request("https://api.resend.com/emails", data=body,
                                 headers={"Authorization": f"Bearer {cfg['key']}",
                                          "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return (200 <= r.status < 300), f"resend {r.status}"
    except urllib.error.HTTPError as e:
        return False, f"resend HTTP {e.code}: {(e.read()[:120] if e.fp else b'').decode(errors='replace')}"
    except Exception as e:  # noqa: BLE001 — envio best-effort, nunca derruba o chamador
        return False, f"falha Resend: {str(e)[:120]}"


# dispatch de provider (trocável): nome lógico -> (checa_config, envia)
_PROVIDERS = {
    "resend": (lambda: _cfg_resend() is not None, _enviar_resend),
    "smtp": (lambda: _cfg_smtp() is not None, _enviar_smtp),
    # "sendgrid": (...), "mailgun": (...)  # entram aqui sem mexer no resto
}


def _provider():
    # Resend é o provider escolhido (JP 2026-07-28); trocável por env EMAIL_PROVIDER.
    nome = os.environ.get("EMAIL_PROVIDER", "resend").strip().lower()
    return _PROVIDERS.get(nome, _PROVIDERS["resend"])


def configurado() -> bool:
    """True se o provider ativo tem credencial (pra o chamador decidir se dispara)."""
    return _provider()[0]()


def enviar(assunto: str, corpo: str, para: str | None = None) -> tuple[bool, str]:
    """(ok, motivo). Inerte (False, motivo) se sem credencial — nunca crasha."""
    dest = (para or os.environ.get("EMAIL_ALERTA_PARA", "")).strip()
    if not dest:
        return False, "sem destinatário (EMAIL_ALERTA_PARA vazio)"
    return _provider()[1](assunto, corpo, dest)


if __name__ == "__main__":  # self-check: inerte sem credencial, envia com provider mockado
    for k in ("SMTP_HOST", "SMTP_USER", "SMTP_PASS", "RESEND_API_KEY", "RESEND_FROM", "EMAIL_PROVIDER"):
        os.environ.pop(k, None)
    # default = resend: sem RESEND_API_KEY => inerte
    assert configurado() is False
    ok, motivo = enviar("x", "y", "jp@x.com")
    assert ok is False and "Resend" in motivo, (ok, motivo)

    # Resend com key+from mas HTTP mockado: prova que monta o POST certo (from/to/subject/text)
    os.environ["RESEND_API_KEY"] = "re_fake"
    os.environ["RESEND_FROM"] = "alertas@jpos.com.br"
    assert configurado() is True
    capt = {}

    class _R:
        status = 200
        def __enter__(self): return self
        def __exit__(self, *a): return False
    def _fake_open(req, timeout=0):
        capt["url"] = req.full_url
        capt["body"] = json.loads(req.data.decode())
        capt["auth"] = req.headers.get("Authorization")
        return _R()
    urllib.request.urlopen = _fake_open
    ok, motivo = enviar("assunto", "corpo", "jp@x.com")
    assert ok and capt["url"] == "https://api.resend.com/emails", capt
    assert capt["body"] == {"from": "alertas@jpos.com.br", "to": ["jp@x.com"],
                            "subject": "assunto", "text": "corpo"}, capt["body"]
    assert capt["auth"] == "Bearer re_fake", capt["auth"]
    os.environ.pop("RESEND_API_KEY", None); os.environ.pop("RESEND_FROM", None)

    # provider mockado prova que a interface funciona quando a credencial existe
    enviados = []
    _PROVIDERS["mock"] = (lambda: True, lambda a, c, p: (enviados.append((a, c, p)) or (True, "enviado")))
    os.environ["EMAIL_PROVIDER"] = "mock"
    assert configurado() is True
    ok, motivo = enviar("assunto", "corpo", "jp@x.com")
    assert ok and enviados == [("assunto", "corpo", "jp@x.com")], (ok, enviados)
    # sem destinatário => inerte
    os.environ.pop("EMAIL_ALERTA_PARA", None)
    assert enviar("a", "b")[0] is False
    print("email_envio OK — inerte sem credencial; provider trocável; envia quando configurado")
